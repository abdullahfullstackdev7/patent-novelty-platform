"""Gateway behaviour: failover, retries, breaker, budgets, quota, cache, modes and repair.

Real tables, scripted fake providers and a fake clock, so nothing sleeps and nothing calls out.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from llm_fixtures import DISCLOSURE
from llm_support import CELLS_OK, ELEMENTS_OK, FakeProvider, Reply, call_rows, count, make_gateway
from sqlalchemy import text

from app.db.models import LlmCall
from app.llm import prompts
from app.llm.errors import (
    AllProvidersUnavailable,
    InvalidOutput,
    LocalOnly,
    OutputTruncated,
    PromptTooLarge,
    ProviderRateLimited,
    ProviderRejected,
    ProviderTimeout,
    ProviderUnavailable,
)
from app.llm.store import LlmSettings, LlmSettingsStore

SPEC = prompts.PARSE_ELEMENTS


@pytest.fixture(autouse=True)
def clean_llm(engine):
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE llm_calls, llm_cache, app_settings"))


def user(n: int = 0) -> str:
    """A distinct request per n, so tests do not hit each other's cache entries."""
    return prompts.parse_elements_user(**{**DISCLOSURE, "title": f"Case {n}"})


def pair(groq=None, gemini=None):
    return {
        "groq": FakeProvider("groq", groq or []),
        "gemini": FakeProvider("gemini", gemini or []),
    }


def tripped(name, error_cls=ProviderUnavailable, **kwargs):
    return error_cls(f"{name} down", provider=name, **kwargs)


# ---- the normal path -----------------------------------------------------------


def test_groq_answers_first_and_everything_is_accounted(session_factory, settings, engine):
    providers = pair(groq=[Reply(ELEMENTS_OK, 300, 60, cached=100)])
    gateway, sleeps, _ = make_gateway(session_factory, settings, providers)
    out = gateway.run(SPEC, user())

    assert out.provider == "groq" and out.cache_hit is False
    assert [e.text for e in out.value.elements] == ["alpha", "beta"]
    assert (out.tokens_in, out.tokens_out, out.total_tokens) == (300, 60, 360)
    assert len(providers["groq"].calls) == 1 and providers["gemini"].calls == []
    assert providers["groq"].model == "openai/gpt-oss-20b"
    call = providers["groq"].calls[0]
    assert call.task == "parse_elements" and call.max_tokens == 500
    assert call.schema["required"] == ["elements"] and call.messages[0].role == "system"

    assert call_rows(session_factory) == [("groq", "parse_elements", "ok", 300, 60, False)]
    with engine.connect() as conn:
        cached_tokens = conn.execute(text("SELECT cached_tokens FROM llm_calls")).scalar_one()
        stored = conn.execute(text("SELECT response::text FROM llm_cache")).scalar_one()
    assert cached_tokens == 100
    assert "alpha" not in stored and "ciphertext" in stored  # cache is encrypted at rest
    assert gateway.buckets["groq"].used_tokens() == 260  # cached tokens do not count


def test_identical_request_is_served_from_the_cache_at_zero_tokens(session_factory, settings):
    providers = pair(groq=[Reply(ELEMENTS_OK)])
    gateway, _, _ = make_gateway(session_factory, settings, providers)
    first = gateway.run(SPEC, user())
    again = gateway.run(SPEC, user().replace("\n", "\n\n"))  # whitespace is normalized
    assert again.cache_hit is True and again.provider is None and again.result is None
    assert again.total_tokens == 0 and again.value == first.value
    assert len(providers["groq"].calls) == 1
    assert call_rows(session_factory)[-1] == ("cache", "parse_elements", "ok", 0, 0, True)
    assert gateway.quota.usage("groq").requests == 1  # cache hits never touch the quota

    other = gateway.run(SPEC, user(1))
    assert other.cache_hit is False and len(providers["groq"].calls) == 2


def test_cache_key_covers_the_task_and_prompt_text(session_factory, settings):
    providers = pair(groq=[Reply(ELEMENTS_OK), Reply(ELEMENTS_OK)])
    gateway, _, _ = make_gateway(session_factory, settings, providers)
    gateway.run(SPEC, user())
    bumped = prompts.PromptSpec("parse_elements", 1, SPEC.output_model, 500)
    assert gateway.run(bumped, user()).cache_hit is True  # same spec, same key
    other_task = prompts.PromptSpec("chart_cells", 1, SPEC.output_model, 500)
    assert gateway.run(other_task, user()).cache_hit is False


# ---- failover, retries, backoff ------------------------------------------------


def test_429_with_a_long_retry_after_fails_over_without_waiting(session_factory, settings):
    providers = pair(
        groq=[tripped("groq", ProviderRateLimited, retry_after=30)], gemini=[Reply(ELEMENTS_OK)]
    )
    gateway, sleeps, _ = make_gateway(session_factory, settings, providers)
    out = gateway.run(SPEC, user())
    assert out.provider == "gemini"
    assert len(providers["groq"].calls) == 1 and sleeps == []  # no retry, no waiting
    assert gateway.breakers["groq"].snapshot().failures == 1
    assert call_rows(session_factory) == [
        ("groq", "parse_elements", "rate_limited", 0, 0, False),
        ("gemini", "parse_elements", "ok", 300, 60, False),
    ]


def test_429_with_a_short_retry_after_is_retried_on_the_same_provider(session_factory, settings):
    providers = pair(groq=[tripped("groq", ProviderRateLimited, retry_after=2), Reply(ELEMENTS_OK)])
    gateway, sleeps, _ = make_gateway(session_factory, settings, providers)
    out = gateway.run(SPEC, user())
    assert out.provider == "groq" and len(providers["groq"].calls) == 2
    assert providers["gemini"].calls == []
    assert sleeps == [pytest.approx(2.1)]  # the hint, plus a little jitter
    assert gateway.breakers["groq"].snapshot().failures == 0  # success resets the count


@pytest.mark.parametrize("error_cls", [ProviderTimeout, ProviderUnavailable])
def test_timeouts_and_5xx_back_off_exponentially_then_fail_over(
    session_factory, settings, error_cls
):
    providers = pair(
        groq=[tripped("groq", error_cls)] * 3,
        gemini=[Reply(ELEMENTS_OK)],
    )
    gateway, sleeps, _ = make_gateway(session_factory, settings, providers, llm_retry_attempts=3)
    out = gateway.run(SPEC, user())
    assert out.provider == "gemini" and len(providers["groq"].calls) == 3
    assert sleeps == [pytest.approx(0.5), pytest.approx(1.0)]  # exponential, jitter fixed at 1.0
    statuses = [row[2] for row in call_rows(session_factory)]
    assert statuses.count("ok") == 1 and len(statuses) == 4


def test_rejected_and_truncated_answers_fail_over_without_touching_the_breaker(
    session_factory, settings
):
    for error_cls in (ProviderRejected, OutputTruncated):
        providers = pair(groq=[tripped("groq", error_cls)], gemini=[Reply(ELEMENTS_OK)])
        gateway, sleeps, _ = make_gateway(session_factory, settings, providers)
        out = gateway.run(SPEC, user(hash(error_cls) % 1000))
        assert out.provider == "gemini" and len(providers["groq"].calls) == 1 and sleeps == []
        assert gateway.breakers["groq"].snapshot().failures == 0


def test_when_every_provider_fails_the_caller_gets_all_providers_unavailable(
    session_factory, settings
):
    providers = pair(groq=[tripped("groq")] * 2, gemini=[tripped("gemini")] * 2)
    gateway, _, _ = make_gateway(session_factory, settings, providers)
    with pytest.raises(AllProvidersUnavailable) as failure:
        gateway.run(SPEC, user())
    assert len(failure.value.attempts) == 2
    assert "groq" in str(failure.value) and "gemini" in str(failure.value)
    assert count(session_factory, "llm_cache") == 0  # nothing is cached for a failed run
    assert [r[2] for r in call_rows(session_factory)] == ["error"] * 4


def test_no_provider_configured_is_reported_clearly(session_factory, settings):
    gateway, _, _ = make_gateway(session_factory, settings, {})
    with pytest.raises(AllProvidersUnavailable, match="no provider"):
        gateway.run(SPEC, user())


# ---- circuit breaker -----------------------------------------------------------


def test_breaker_opens_after_three_failures_skips_groq_then_recovers(session_factory, settings):
    providers = pair(
        groq=[tripped("groq")] * 3 + [Reply(ELEMENTS_OK)],
        gemini=[Reply(ELEMENTS_OK)] * 5,
    )
    gateway, _, clock = make_gateway(session_factory, settings, providers, llm_retry_attempts=1)
    for n in range(3):
        assert gateway.run(SPEC, user(n)).provider == "gemini"
    assert gateway.breakers["groq"].snapshot().state == "open"
    assert len(providers["groq"].calls) == 3

    assert gateway.run(SPEC, user(3)).provider == "gemini"
    assert len(providers["groq"].calls) == 3  # skipped without a call while open

    clock.advance(61)  # the 60 s cool-down passed: one trial call is allowed
    assert gateway.run(SPEC, user(4)).provider == "groq"
    assert len(providers["groq"].calls) == 4
    assert gateway.breakers["groq"].snapshot().state == "closed"


def test_a_failed_trial_call_reopens_the_breaker(session_factory, settings):
    providers = pair(groq=[tripped("groq")] * 4, gemini=[Reply(ELEMENTS_OK)] * 5)
    gateway, _, clock = make_gateway(session_factory, settings, providers, llm_retry_attempts=1)
    for n in range(3):
        gateway.run(SPEC, user(n))
    clock.advance(61)
    gateway.run(SPEC, user(3))  # trial fails, falls back to gemini
    assert gateway.breakers["groq"].snapshot().state == "open"
    gateway.run(SPEC, user(4))
    assert len(providers["groq"].calls) == 4  # not called again until the next cool-down


# ---- per-minute token bucket ---------------------------------------------------


def test_predicted_minute_overflow_switches_to_gemini_without_calling_groq(
    session_factory, settings
):
    providers = pair(gemini=[Reply(ELEMENTS_OK)])
    gateway, sleeps, _ = make_gateway(session_factory, settings, providers)
    gateway.buckets["groq"].record(7900)  # almost the whole 8,000 tokens per minute
    out = gateway.run(SPEC, user())
    assert out.provider == "gemini" and providers["groq"].calls == [] and sleeps == []


def test_groq_only_mode_waits_for_the_bucket_when_the_wait_is_short(session_factory, settings):
    providers = pair(groq=[Reply(ELEMENTS_OK)])
    gateway, sleeps, clock = make_gateway(session_factory, settings, providers)
    gateway.store.save(LlmSettings("groq", "openai/gpt-oss-20b", "gemini-3.1-flash-lite"), None)
    gateway.buckets["groq"].record(7900)
    clock.advance(50)  # the 7,900 tokens leave the window in 10 s
    out = gateway.run(SPEC, user())
    assert out.provider == "groq" and sleeps == [pytest.approx(10)]


def test_groq_only_mode_gives_up_when_the_wait_is_long(session_factory, settings):
    providers = pair(groq=[Reply(ELEMENTS_OK)])
    gateway, sleeps, _ = make_gateway(session_factory, settings, providers)
    gateway.store.save(LlmSettings("groq", "openai/gpt-oss-20b", "gemini-3.1-flash-lite"), None)
    gateway.buckets["groq"].record(7900)
    with pytest.raises(AllProvidersUnavailable, match="per-minute budget"):
        gateway.run(SPEC, user())
    assert sleeps == [] and providers["groq"].calls == []


def test_remaining_tokens_header_makes_the_next_big_request_switch_provider(
    session_factory, settings
):
    providers = pair(
        groq=[Reply(ELEMENTS_OK, remaining=100, reset=30)], gemini=[Reply(ELEMENTS_OK)]
    )
    gateway, _, _ = make_gateway(session_factory, settings, providers)
    assert gateway.run(SPEC, user(0)).provider == "groq"
    assert gateway.run(SPEC, user(1)).provider == "gemini"  # header says only 100 tokens left
    assert len(providers["groq"].calls) == 1


# ---- request size ---------------------------------------------------------------


def test_oversized_request_skips_groq_in_auto_mode(session_factory, settings):
    huge = prompts.parse_elements_user(**{**DISCLOSURE, "problem": "word " * 3000})
    big = "x" * 16_000  # about 4,000 tokens, over the 3,500 request budget
    providers = pair(gemini=[Reply(ELEMENTS_OK)])
    gateway, _, _ = make_gateway(session_factory, settings, providers)
    out = gateway.run(SPEC, huge + big)
    assert out.provider == "gemini" and providers["groq"].calls == []


def test_oversized_request_is_refused_when_only_groq_is_allowed(session_factory, settings):
    providers = pair(groq=[Reply(ELEMENTS_OK)])
    gateway, _, _ = make_gateway(session_factory, settings, providers)
    gateway.store.save(LlmSettings("groq", "openai/gpt-oss-20b", "gemini-3.1-flash-lite"), None)
    with pytest.raises(PromptTooLarge):
        gateway.run(SPEC, "x" * 16_000)
    assert providers["groq"].calls == []


# ---- daily quota ----------------------------------------------------------------


def add_usage(session_factory, provider: str, tokens: int, when: datetime | None = None, **kw):
    with session_factory() as session:
        session.add(
            LlmCall(
                task="seed",
                provider=provider,
                model="m",
                tokens_in=tokens,
                tokens_out=0,
                status=kw.get("status", "ok"),
                cache_hit=kw.get("cache_hit", False),
                **({"created_at": when} if when else {}),
            )  # fmt: skip
        )
        session.commit()


def test_daily_token_quota_exhaustion_skips_the_provider(session_factory, settings):
    add_usage(session_factory, "groq", 199_900)
    providers = pair(gemini=[Reply(ELEMENTS_OK)])
    gateway, _, _ = make_gateway(session_factory, settings, providers)
    out = gateway.run(SPEC, user())
    assert out.provider == "gemini" and providers["groq"].calls == []
    usage = gateway.quota.usage("groq")
    assert usage.tokens == 199_900 and usage.tokens_percent == pytest.approx(99.95, abs=0.06)


def test_daily_request_quota_exhaustion_skips_the_provider(session_factory, settings):
    for _ in range(2):
        add_usage(session_factory, "groq", 10)
    providers = pair(groq=[Reply(ELEMENTS_OK)], gemini=[Reply(ELEMENTS_OK)])
    gateway, _, _ = make_gateway(session_factory, settings, providers, groq_rpd=2)
    assert gateway.run(SPEC, user()).provider == "gemini"


def test_only_todays_successful_uncached_calls_count_towards_the_quota(session_factory, settings):
    add_usage(session_factory, "groq", 150_000, datetime.now(UTC) - timedelta(days=1, hours=2))
    add_usage(session_factory, "groq", 150_000, cache_hit=True)
    add_usage(session_factory, "groq", 150_000, status="rate_limited")
    add_usage(session_factory, "gemini", 150_000)
    providers = pair(groq=[Reply(ELEMENTS_OK)])
    gateway, _, _ = make_gateway(session_factory, settings, providers)
    assert gateway.quota.usage("groq").tokens == 0
    assert gateway.run(SPEC, user()).provider == "groq"


def test_quota_exhausted_everywhere_ends_in_all_providers_unavailable(session_factory, settings):
    add_usage(session_factory, "groq", 199_900)
    add_usage(session_factory, "gemini", 1)
    gateway, _, _ = make_gateway(session_factory, settings, pair(), gemini_rpd=1)
    with pytest.raises(AllProvidersUnavailable, match="daily quota"):
        gateway.run(SPEC, user())


# ---- modes ----------------------------------------------------------------------


def test_global_local_only_mode_makes_no_calls(session_factory, settings):
    providers = pair(groq=[Reply(ELEMENTS_OK)])
    gateway, _, _ = make_gateway(session_factory, settings, providers)
    gateway.store.save(
        LlmSettings("local_only", "openai/gpt-oss-20b", "gemini-3.1-flash-lite"), None
    )
    with pytest.raises(LocalOnly):
        gateway.run(SPEC, user())
    assert providers["groq"].calls == [] and call_rows(session_factory) == []


def test_case_level_modes_override_or_restrict_the_global_mode(session_factory, settings):
    providers = pair(groq=[Reply(ELEMENTS_OK)], gemini=[Reply(ELEMENTS_OK)])
    gateway, _, _ = make_gateway(session_factory, settings, providers)
    with pytest.raises(LocalOnly):
        gateway.run(SPEC, user(0), case_mode="local_only")
    assert gateway.run(SPEC, user(1), case_mode="gemini").provider == "gemini"
    assert providers["groq"].calls == []
    assert gateway.effective_mode("auto") == "auto" and gateway.effective_mode("groq") == "groq"


def test_forced_provider_modes_do_not_fall_back(session_factory, settings):
    providers = pair(groq=[tripped("groq")] * 2, gemini=[Reply(ELEMENTS_OK)])
    gateway, _, _ = make_gateway(session_factory, settings, providers)
    gateway.store.save(LlmSettings("groq", "openai/gpt-oss-20b", "gemini-3.1-flash-lite"), None)
    with pytest.raises(AllProvidersUnavailable):
        gateway.run(SPEC, user())
    assert providers["gemini"].calls == []


def test_admin_chosen_model_ids_reach_the_provider_and_the_log(session_factory, settings):
    providers = pair(groq=[Reply(ELEMENTS_OK)])
    gateway, _, _ = make_gateway(session_factory, settings, providers)
    gateway.store.save(LlmSettings("auto", "openai/gpt-oss-120b", "gemini-3.1-flash"), None)
    gateway.run(SPEC, user())
    assert providers["groq"].model == "openai/gpt-oss-120b"
    with session_factory() as session:
        assert (
            session.execute(text("SELECT model FROM llm_calls")).scalar_one()
            == "openai/gpt-oss-120b"
        )


def test_settings_store_defaults_persistence_and_cache_ttl(session_factory, settings):
    from llm_support import Clock

    clock = Clock()
    first = LlmSettingsStore(session_factory, settings, clock)
    second = LlmSettingsStore(session_factory, settings, clock)
    defaults = first.get()
    assert (defaults.mode, defaults.groq_model) == ("auto", "openai/gpt-oss-20b")
    assert defaults.gemini_model == "gemini-3.1-flash-lite" == first.defaults().gemini_model

    second.save(LlmSettings("groq", "openai/gpt-oss-120b", "gemini-3.1-flash"), None)
    assert second.get().mode == "groq"  # the writer sees it at once
    assert first.get().mode == "auto"  # another process sees it after the cache TTL
    clock.advance(6)
    assert first.get() == LlmSettings("groq", "openai/gpt-oss-120b", "gemini-3.1-flash")
    second.save(LlmSettings("gemini", "openai/gpt-oss-20b", "gemini-3.1-flash"), None)  # upsert
    assert count(session_factory, "app_settings") == 1


# ---- validation and repair ------------------------------------------------------


def test_invalid_field_is_repaired_with_a_call_that_carries_only_that_field(
    session_factory, settings
):
    broken = {"elements": [{"id": "E1", "text": "kept text"}, {"id": "X9", "text": "other text"}]}
    providers = pair(groq=[Reply(broken), Reply({"value": "E2"})])
    gateway, _, _ = make_gateway(session_factory, settings, providers)
    out = gateway.run(SPEC, user())

    assert [e.id for e in out.value.elements] == ["E1", "E2"]
    assert len(providers["groq"].calls) == 2 and len(out.calls) == 2
    repair = providers["groq"].calls[1]
    assert repair.task == "parse_elements.repair"
    assert "X9" in repair.user and "pattern" in repair.user
    assert "kept text" not in repair.user and "other text" not in repair.user  # only the field
    assert DISCLOSURE["problem"] not in repair.user  # nor the disclosure
    assert repair.schema["properties"]["value"]["type"] == "string"
    assert out.total_tokens == 720
    assert set(call_rows(session_factory)) == {
        ("groq", "parse_elements", "invalid_output", 300, 60, False),
        ("groq", "parse_elements.repair", "ok", 300, 60, False),
    }
    assert gateway.run(SPEC, user()).cache_hit is True  # the repaired value was cached


def test_only_one_repair_is_attempted(session_factory, settings):
    broken = {"elements": [{"id": "X9", "text": "t"}]}
    providers = pair(groq=[Reply(broken), Reply({"value": "ZZ"}), Reply({"value": "E1"})])
    gateway, _, _ = make_gateway(session_factory, settings, providers)
    with pytest.raises(InvalidOutput, match="still invalid"):
        gateway.run(SPEC, user())
    assert len(providers["groq"].calls) == 2
    assert count(session_factory, "llm_cache") == 0


def test_output_that_is_not_json_is_repaired_from_a_short_raw_snippet(session_factory, settings):
    garbage = "Sure! Here is the answer: " + "blah " * 400
    providers = pair(groq=[Reply(raw_text=garbage), Reply({"value": ELEMENTS_OK})])
    gateway, _, _ = make_gateway(session_factory, settings, providers)
    out = gateway.run(SPEC, user())
    assert [e.id for e in out.value.elements] == ["E1", "E2"]
    repair = providers["groq"].calls[1]
    assert "Sure! Here is the answer" in repair.user and "not valid JSON" in repair.user
    assert len(repair.user) < 1200  # truncated, not the whole answer


def test_empty_list_is_repaired_at_the_list_level(session_factory, settings):
    fixed = [{"id": "E1", "text": "x"}]
    providers = pair(groq=[Reply({"elements": []}), Reply({"value": fixed})])
    gateway, _, _ = make_gateway(session_factory, settings, providers)
    assert gateway.run(SPEC, user()).value.elements[0].text == "x"
    assert providers["groq"].calls[1].schema["properties"]["value"]["type"] == "array"


def test_over_long_rationale_is_truncated_for_free_not_repaired(session_factory, settings):
    long_reason = " ".join(f"word{i}" for i in range(60))
    cells = {"cells": [{"e": "E1", "s": "p", "p": "P1", "r": long_reason}]}
    providers = pair(groq=[Reply(cells)])
    gateway, _, _ = make_gateway(session_factory, settings, providers)
    out = gateway.run(prompts.CHART_CELLS, prompts.chart_cells_user("US1", []))
    assert len(providers["groq"].calls) == 1 and len(out.value.cells[0].r.split()) == 25


def test_summary_over_350_words_is_repaired(session_factory, settings):
    long_summary = " ".join(["word"] * 400)
    providers = pair(groq=[Reply({"summary": long_summary}), Reply({"value": "A short summary."})])
    gateway, _, _ = make_gateway(session_factory, settings, providers)
    out = gateway.run(prompts.EXEC_SUMMARY, prompts.exec_summary_user({"risk": "low"}))
    assert out.value.summary == "A short summary."
    assert "350 words" in providers["groq"].calls[1].user


def test_chart_task_runs_end_to_end(session_factory, settings):
    providers = pair(groq=[Reply(CELLS_OK, 700, 120)])
    gateway, _, _ = make_gateway(session_factory, settings, providers)
    out = gateway.run(prompts.CHART_CELLS, prompts.chart_cells_user("US1", []))
    assert out.value.cells[0].s == "d" and out.total_tokens == 820


def test_repair_that_cannot_run_reports_invalid_output(session_factory, settings):
    broken = {"elements": [{"id": "X9", "text": "t"}]}
    providers = pair(
        groq=[Reply(broken), tripped("groq"), tripped("groq")], gemini=[tripped("gemini")] * 2
    )
    gateway, _, _ = make_gateway(session_factory, settings, providers)
    with pytest.raises(InvalidOutput, match="repair unavailable"):
        gateway.run(SPEC, user())


# ---- admin view -----------------------------------------------------------------


def test_status_reports_quota_minute_budget_and_breaker_state(session_factory, settings):
    providers = {"groq": FakeProvider("groq", [Reply(ELEMENTS_OK, 300, 60)])}
    gateway, _, _ = make_gateway(session_factory, settings, providers)
    gateway.run(SPEC, user())
    status = gateway.status()
    groq, gemini = status["providers"]
    assert status["mode"] == "auto" and (groq["name"], gemini["name"]) == ("groq", "gemini")
    assert groq["configured"] is True and gemini["configured"] is False
    assert groq["breaker"]["state"] == "closed"
    assert groq["minute"] == {"tokens_used": 360, "tokens_limit": 8000, "requests_used": 1,
                              "requests_limit": 30}  # fmt: skip
    assert groq["day"]["tokens_used"] == 360 and groq["day"]["tokens_limit"] == 200_000
    assert groq["day"]["requests_used"] == 1 and groq["day"]["requests_limit"] == 1000
    assert gemini["day"]["requests_limit"] == 250 and gemini["day"]["tokens_limit"] is None
    assert groq["model"] == "openai/gpt-oss-20b" and gemini["model"] == "gemini-3.1-flash-lite"


def test_provider_failures_never_leak_keys_into_logs(session_factory, settings, caplog):
    secret = "gsk_abcdefghijklmnopqrstuvwxyz0123456789"
    providers = pair(groq=[ProviderUnavailable(f"auth failed for {secret}", provider="groq")] * 2,
                     gemini=[Reply(ELEMENTS_OK)])  # fmt: skip
    gateway, _, _ = make_gateway(session_factory, settings, providers)
    with caplog.at_level("DEBUG"):
        gateway.run(SPEC, user())
    assert secret not in caplog.text
