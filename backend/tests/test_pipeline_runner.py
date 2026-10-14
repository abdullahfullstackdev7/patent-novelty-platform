"""The pipeline end to end on the fixture corpus: fake embedder, fake reranker, scripted LLM."""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from llm_support import call_rows, count
from pipeline_support import E1, E2, E3, ELEMENTS, PRIORITY, PipelineLLM, make_case, make_runner
from sqlalchemy import text
from support import FakeEmbedder

from app.llm.errors import ProviderUnavailable
from app.pipeline import classify
from app.pipeline.runner import STAGES, RunOptions
from app.services.disclosures import save_disclosure


@pytest.fixture(autouse=True)
def clean_pipeline_tables(engine):
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE llm_calls, llm_cache, app_settings"))


@pytest.fixture
def world(users, seeded, session_factory, settings):
    """A case owned by the attorney on the fixture corpus, plus a scripted LLM and a runner."""
    llm = PipelineLLM()
    runner, gateway = make_runner(session_factory, settings, llm)
    case_id = make_case(session_factory, settings, users["attorney"].id)
    return type("World", (), {"llm": llm, "runner": runner, "gateway": gateway, "case_id": case_id,
                              "sessions": session_factory, "settings": settings, "users": users})()  # fmt: skip


def cells(session_factory, case_id, patent_id=None):
    sql = (
        "SELECT e.key, c.patent_id, c.status, c.method, c.confidence, c.passage_id, c.excerpt, "
        "c.char_start, c.char_end, c.input_hash, c.id FROM chart_cells c "
        "JOIN claim_charts ch ON ch.id = c.chart_id "
        "JOIN disclosure_elements e ON e.id = c.element_id WHERE ch.case_id = :c "
        + ("AND c.patent_id = :p " if patent_id else "")
        + "ORDER BY c.patent_id, e.key"
    )
    params = {"c": case_id, **({"p": patent_id} if patent_id else {})}
    with session_factory() as session:
        return session.execute(text(sql), params).all()


def one(session_factory, sql, **params):
    with session_factory() as session:
        return session.execute(text(sql), params).one()


def scalar(session_factory, sql, **params):
    with session_factory() as session:
        return session.execute(text(sql), params).scalar_one()


def test_assumptions_about_the_fixture_corpus(world):
    """The expected verdicts below rely on these similarities, so fail clearly if they drift."""
    from conftest import CORPUS

    embedder = FakeEmbedder()
    queries = embedder.encode_queries([E1, E2, E3])
    best: dict[str, list[float]] = {}
    for pid, _source, _title, abstract, published, _cpc, claims in CORPUS:
        if published >= PRIORITY:
            continue
        scores = embedder.encode_documents([abstract, *claims]) @ queries.T
        best[pid] = [round(float(v), 3) for v in scores.max(axis=0)]
    assert best["US100A1"][0] > 0.99  # E1 copies a claim: locally "disclosed"
    assert 0.40 < best["US100A1"][1] < 0.80  # E2 is ambiguous for US100A1 only
    assert best["US100A1"][2] < 0.30  # E3 matches nothing
    others = [scores[1] for pid, scores in best.items() if pid != "US100A1"]
    assert max(others) < 0.35  # so exactly one reference needs the LLM


def test_full_run_charts_searches_assesses_and_writes_the_report(world):
    summary = world.runner.run(world.case_id)

    assert summary.references[0] == "US100A1" and len(summary.references) == 3
    assert summary.search_reused is False and summary.cells_total == 9 == summary.cells_computed
    assert summary.report_version == 1 and summary.report_created is True
    assert summary.risk_level in {"low", "medium", "medium_high", "high"}

    rows = {(r.patent_id, r.key): r for r in cells(world.sessions, world.case_id)}
    first = rows[("US100A1", "E1")]
    assert (first.status, first.method) == ("disclosed", "local") and float(first.confidence) > 0.9
    second = rows[("US100A1", "E2")]
    assert (second.status, second.method) == ("partial", "llm")  # the scripted model says partial
    third = rows[("US100A1", "E3")]
    assert (third.status, third.method) == ("not_found", "local")
    assert {r.method for r in rows.values()} <= {"local", "llm"}

    # the persisted search run: ten at most, only before the priority date
    assert scalar(world.sessions, "SELECT count(*) FROM search_results") <= 10
    assert (
        scalar(world.sessions, "SELECT count(*) FROM search_results WHERE patent_id = 'US106A1'")
        == 0
    )
    assert scalar(world.sessions, "SELECT count(*) FROM search_results WHERE in_chart") == 3
    assert scalar(world.sessions, "SELECT count(*) FROM search_runs") == 1

    case = one(world.sessions, "SELECT status, stage, risk_level, risk_score FROM cases")
    assert (case.status, case.stage) == ("draft", "done") and case.risk_level == summary.risk_level
    assert float(case.risk_score) == summary.risk_score
    assert scalar(world.sessions, "SELECT status FROM claim_charts") == "done"
    assert scalar(world.sessions, "SELECT state FROM reports") == "draft"


def test_every_excerpt_is_a_verbatim_substring_of_its_source_chunk(world):
    world.runner.run(world.case_id)
    checked = 0
    with world.sessions() as session:
        for row in cells(world.sessions, world.case_id):
            if row.excerpt is None:
                continue
            source = session.execute(
                text("SELECT text FROM patent_chunks WHERE id = :i"), {"i": row.passage_id}
            ).scalar_one()
            assert source[row.char_start : row.char_end] == row.excerpt
            assert classify.excerpt_is_verbatim(row.excerpt, source, row.char_start, row.char_end)
            checked += 1
    assert checked >= 6


def test_token_accounting_matches_the_call_log_and_stays_small(world):
    summary = world.runner.run(world.case_id)
    logged = scalar(
        world.sessions, "SELECT COALESCE(sum(tokens_in + tokens_out), 0) FROM llm_calls"
    )
    assert summary.tokens == logged > 0
    assert summary.llm_calls == len(world.llm.calls)
    assert set(world.llm.tasks()) == {"chart_cells", "exec_summary"}
    assert (
        world.llm.tasks().count("chart_cells") == 1
    )  # one batched call, only US100A1 is ambiguous
    assert summary.tokens < 9000  # well inside the per-case budget on this small case
    for task, user in world.llm.calls:  # only the ambiguous element is ever sent
        if task == "chart_cells":
            assert '"e":"E2"' in user and '"e":"E1"' not in user and '"e":"E3"' not in user


def test_rerun_of_an_unchanged_case_costs_zero_tokens_and_creates_nothing_new(world):
    first = world.runner.run(world.case_id)
    calls_before = len(world.llm.calls)
    rows_before = {
        (r.patent_id, r.key): (r.id, r.input_hash) for r in cells(world.sessions, world.case_id)
    }

    again = world.runner.run(world.case_id)
    assert again.search_reused is True
    assert again.tokens == 0 and again.llm_calls == 0
    assert again.cells_reused == first.cells_total and again.cells_computed == 0
    assert again.report_created is False and again.report_version == 1
    assert len(world.llm.calls) == calls_before  # the model was not called again
    assert scalar(world.sessions, "SELECT count(*) FROM search_runs") == 1
    assert {
        (r.patent_id, r.key): (r.id, r.input_hash) for r in cells(world.sessions, world.case_id)
    } == rows_before
    assert scalar(world.sessions, "SELECT count(*) FROM report_versions") == 1


def test_forcing_a_new_search_still_costs_zero_tokens_for_identical_requests(world):
    world.runner.run(world.case_id)
    calls_before = len(world.llm.calls)
    forced = world.runner.run(world.case_id, RunOptions(references=3, force_search=True))
    assert (
        forced.search_reused is False
        and scalar(world.sessions, "SELECT count(*) FROM search_runs") == 2
    )
    assert forced.tokens == 0 and len(world.llm.calls) == calls_before  # chart cells unchanged too


def test_editing_one_element_recomputes_only_its_cells(world):
    world.runner.run(world.case_id)
    before = {(r.patent_id, r.key): r for r in cells(world.sessions, world.case_id)}
    edited = [E1, E2 + " in response to a temperature rise", E3]
    with world.sessions() as session:
        save_disclosure(session, world.settings, world.case_id, title="Thermal runaway detector",
                        technical_field="Battery safety", problem="Thermal runaway is detected too late to isolate the pack.",
                        solution="Measure impedance and gas, then open a contactor.",
                        elements=[(t, "user") for t in edited])  # fmt: skip
        session.commit()
    calls_before = len(world.llm.calls)

    summary = world.runner.run(world.case_id)
    after = {(r.patent_id, r.key): r for r in cells(world.sessions, world.case_id)}
    shared = {pid for pid, _ in before} & {pid for pid, _ in after}
    assert "US100A1" in shared
    for pid in shared:
        assert after[(pid, "E1")].id == before[(pid, "E1")].id  # untouched cells are reused
        assert after[(pid, "E1")].input_hash == before[(pid, "E1")].input_hash
        assert after[(pid, "E3")].input_hash == before[(pid, "E3")].input_hash
        assert after[(pid, "E2")].input_hash != before[(pid, "E2")].input_hash
    assert summary.cells_reused >= 2 * len(shared)
    new_calls = world.llm.calls[calls_before:]
    assert all(task != "chart_cells" or ('"e":"E2"' in user and '"e":"E1"' not in user)
               for task, user in new_calls)  # fmt: skip
    assert summary.report_created is True and summary.report_version == 2


def test_attorney_override_survives_a_rerun_and_is_cleared_only_when_inputs_change(world):
    world.runner.run(world.case_id)
    with world.sessions() as session:
        cell = session.execute(
            text(
                "SELECT c.id FROM chart_cells c JOIN disclosure_elements e ON e.id = c.element_id "
                "WHERE c.patent_id = 'US100A1' AND e.key = 'E2'"
            )
        ).scalar_one()
        session.execute(
            text(
                "UPDATE chart_cells SET status = 'disclosed', original = '{\"status\": \"partial\"}', "
                "override_reason = 'attorney read claim 2', overridden_at = now() WHERE id = :i"
            ),
            {"i": cell},
        )
        session.commit()  # fmt: skip

    world.runner.run(world.case_id)  # nothing changed: the override must stay
    kept = scalar(world.sessions, "SELECT status FROM chart_cells WHERE id = :i", i=cell)
    assert kept == "disclosed"
    assert (
        scalar(world.sessions, "SELECT count(*) FROM review_events WHERE event_type = 'cell_reset'")
        == 0
    )

    with world.sessions() as session:  # now the element changes: the stale override goes
        save_disclosure(session, world.settings, world.case_id, title="Thermal runaway detector",
                        technical_field="Battery safety", problem="Thermal runaway is detected too late to isolate the pack.",
                        solution="Measure impedance and gas, then open a contactor.",
                        elements=[(t, "user") for t in (E1, E2 + " quickly", E3)])  # fmt: skip
        session.commit()
    world.runner.run(world.case_id)
    row = one(
        world.sessions,
        "SELECT status, override_reason, overridden_at FROM chart_cells WHERE id = :i",
        i=cell,
    )
    assert row.status == "partial" and row.override_reason is None and row.overridden_at is None
    assert (
        scalar(world.sessions, "SELECT count(*) FROM review_events WHERE event_type = 'cell_reset'")
        == 1
    )


def test_stages_run_in_the_documented_order_and_progress_is_visible(world, monkeypatch):
    seen = []
    original = world.runner._set_stage
    monkeypatch.setattr(
        world.runner,
        "_set_stage",
        lambda case_id, name: (seen.append(name), original(case_id, name))[1],
    )
    world.runner.run(world.case_id)
    assert seen == list(STAGES[:-1])  # every stage but "done", which _finish writes
    assert scalar(world.sessions, "SELECT stage FROM cases") == "done"


def test_reference_count_option_is_honoured_and_clamped(world):
    one = world.runner.run(world.case_id, RunOptions(references=1, force_search=True))
    assert len(one.references) == 1
    many = world.runner.run(world.case_id, RunOptions(references=9, force_search=True))
    assert len(many.references) == 5
    assert scalar(world.sessions, "SELECT count(DISTINCT patent_id) FROM chart_cells") == 5
    options = RunOptions.from_payload({"options": {"references": 2, "force_search": True}})
    assert (options.references, options.force_search) == (2, True)
    assert RunOptions.from_payload({}).references == 3


def test_excluded_and_pinned_references_are_respected(world):
    world.runner.run(world.case_id)
    with world.sessions() as session:
        session.execute(
            text("UPDATE search_results SET excluded = true WHERE patent_id = 'US100A1'")
        )
        session.execute(text("UPDATE search_results SET in_chart = false"))
        session.commit()
    again = world.runner.run(world.case_id)  # same search run reused, selection recomputed
    assert "US100A1" not in again.references and len(again.references) == 3
    assert (
        scalar(world.sessions, "SELECT count(*) FROM chart_cells WHERE patent_id = 'US100A1'") == 0
    )

    with world.sessions() as session:  # pin one specific result
        session.execute(text("UPDATE search_results SET in_chart = false"))
        session.execute(
            text("UPDATE search_results SET in_chart = true WHERE patent_id = 'US104A1'")
        )
        session.commit()
    pinned = world.runner.run(world.case_id)
    assert pinned.references == ["US104A1"]


# ---- degraded modes ---------------------------------------------------------------------------


def test_llm_outage_falls_back_to_local_rules_and_a_labelled_template_report(
    users, seeded, session_factory, settings
):
    llm = PipelineLLM(fail_with=ProviderUnavailable("down", provider="groq"))
    runner, _ = make_runner(session_factory, settings, llm, llm_retry_attempts=1)
    case_id = make_case(session_factory, settings, users["attorney"].id)
    summary = runner.run(case_id)

    assert summary.llm_used is False and summary.llm_error == "AllProvidersUnavailable"
    assert summary.tokens == 0 and summary.report_version == 1
    ambiguous = [r for r in cells(session_factory, case_id) if r.key == "E2"]
    assert ambiguous and all(r.method == "local" for r in ambiguous)
    from app.security.crypto import open_json

    with session_factory() as session:
        content = open_json(
            session.execute(text("SELECT content FROM report_versions")).scalar_one(), settings
        )
    assert content["generated_by"] == "Machine summary, no LLM" and content["llm"] == {
        "used": False
    }
    assert content["executive_summary"].startswith("Machine summary, no LLM.")


def test_local_only_case_never_calls_a_provider(users, seeded, session_factory, settings):
    llm = PipelineLLM()
    runner, _ = make_runner(session_factory, settings, llm)
    case_id = make_case(session_factory, settings, users["attorney"].id, llm_mode="local_only")
    summary = runner.run(case_id)
    assert llm.calls == [] and call_rows(session_factory) == []
    assert summary.llm_used is False and summary.llm_error == "local_only" and summary.tokens == 0
    assert summary.references and summary.cells_total == 3 * len(summary.references)


def test_unverifiable_citations_are_downgraded_and_counted(
    users, seeded, session_factory, settings
):
    llm = PipelineLLM(status_for=lambda element: "d", cite=lambda item: "NOT-A-REAL-PASSAGE")
    runner, _ = make_runner(session_factory, settings, llm)
    case_id = make_case(session_factory, settings, users["attorney"].id)
    summary = runner.run(case_id)
    assert summary.charting.downgraded >= 1
    e2 = next(r for r in cells(session_factory, case_id, "US100A1") if r.key == "E2")
    assert e2.status == "partial" and e2.method == "llm"  # "disclosed" without a valid citation


def test_an_excerpt_that_is_not_in_the_source_is_never_stored(
    users, seeded, session_factory, settings, monkeypatch
):
    monkeypatch.setattr(
        classify, "best_excerpt", lambda passage, element, max_words=40: ("INVENTED TEXT", 0, 13)
    )
    runner, _ = make_runner(session_factory, settings, PipelineLLM())
    case_id = make_case(session_factory, settings, users["attorney"].id)
    summary = runner.run(case_id)
    rows = cells(session_factory, case_id)
    assert summary.excerpts_rejected == sum(1 for r in rows if r.passage_id) > 0
    assert all(r.excerpt is None and r.char_start is None for r in rows)
    first = next(r for r in rows if r.key == "E1" and r.patent_id == "US100A1")
    assert first.status == "partial"  # a disclosed cell without evidence is downgraded


def test_no_prior_art_before_the_priority_date_gives_a_low_risk_report(
    users, seeded, session_factory, settings
):
    runner, _ = make_runner(session_factory, settings, PipelineLLM())
    case_id = make_case(
        session_factory, settings, users["attorney"].id, priority_date=date(1990, 1, 1)
    )
    summary = runner.run(case_id)
    assert summary.references == [] and summary.cells_total == 0
    assert (summary.risk_level, summary.risk_score) == ("low", 0)
    assert (
        summary.report_version == 1
        and scalar(session_factory, "SELECT count(*) FROM chart_cells") == 0
    )


def test_a_case_without_elements_fails_permanently(users, seeded, session_factory, settings):
    from app.db.models import Case
    from app.pipeline.queue import PermanentError

    with session_factory() as session:
        case = Case(owner_id=users["attorney"].id, title="empty", priority_date=PRIORITY)
        session.add(case)
        session.commit()
        empty_id = case.id
    runner, _ = make_runner(session_factory, settings, PipelineLLM())
    with pytest.raises(PermanentError, match="no disclosure"):
        runner.run(empty_id)
    with pytest.raises(PermanentError, match="no longer exists"):
        runner.run(uuid.uuid4())
    assert ELEMENTS and count(session_factory, "llm_cache") == 0
