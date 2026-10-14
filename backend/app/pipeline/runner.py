"""Pipeline runner: intake, search, reference selection, passages, charting, risk, report.

Every stage is idempotent and resumable. A rerun of an unchanged case reuses the stored search
run, skips every chart cell whose input hash is unchanged, hits the LLM cache for the rest, and
creates no new report version when the content is identical, so it costs zero LLM tokens.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.billing import metering
from app.config import Settings
from app.db.models import (
    Case,
    ChartCell,
    ClaimChart,
    PatentChunk,
    ReviewEvent,
    SearchResult,
    SearchRun,
)
from app.llm import prompts
from app.llm.errors import AllProvidersUnavailable, InvalidOutput, LocalOnly, PromptTooLarge
from app.llm.gateway import LLMGateway
from app.pipeline import classify
from app.pipeline.assessment import (
    ReferenceInfo,
    cells_by_reference,
    charted_references,
    element_keys,
    latest_run,
    load_assessment,
)
from app.pipeline.charting import CellDraft, ChartingStats, cell_input_hash, chart_reference
from app.pipeline.passages import Passage, build_passages, load_chunks, select_for_elements
from app.pipeline.queue import PermanentError
from app.search.embedding import Embedder, Reranker
from app.search.schemas import DisclosureQuery
from app.search.service import SearchService
from app.services import reports as report_service
from app.services.disclosures import load_disclosure

logger = logging.getLogger("priorart.pipeline")
STAGES = ("intake", "search", "reference_selection", "passage_selection", "charting",
          "risk", "report", "done")  # fmt: skip
MAX_REFERENCES = 5
SUMMARY_WORDS_IN = 400


@dataclass
class RunOptions:
    references: int = 3
    force_search: bool = False

    @classmethod
    def from_payload(cls, payload: dict | None, default_references: int = 3) -> RunOptions:
        data = (payload or {}).get("options") or {}
        return cls(
            references=int(data.get("references", default_references)),
            force_search=bool(data.get("force_search", False)),
        )


@dataclass
class RunSummary:
    case_id: uuid.UUID
    references: list[str] = field(default_factory=list)
    search_reused: bool = False
    cells_total: int = 0
    cells_reused: int = 0
    cells_computed: int = 0
    excerpts_rejected: int = 0
    tokens: int = 0
    llm_calls: int = 0
    cache_hits: int = 0
    llm_used: bool = False
    llm_error: str | None = None
    risk_level: str | None = None
    risk_score: int | None = None
    report_version: int | None = None
    report_created: bool = False
    charting: ChartingStats = field(default_factory=ChartingStats)
    seconds: dict[str, float] = field(default_factory=dict)


@dataclass
class _Context:
    case_id: uuid.UUID
    title: str
    technical_field: str
    problem: str
    solution: str
    content_hash: str
    elements: list[tuple[str, str]]  # (key, text) in order
    priority_date: date
    case_mode: str


def _cap_words(text: str, limit: int) -> str:
    words = text.split()
    return text if len(words) <= limit else " ".join(words[:limit])


class PipelineRunner:
    def __init__(
        self,
        sessions: sessionmaker[Session],
        settings: Settings,
        gateway: LLMGateway | None,
        embedder: Embedder,
        reranker: Reranker | None,
    ) -> None:
        self.sessions = sessions
        self.settings = settings
        self.gateway = gateway
        self.embedder = embedder
        self.reranker = reranker

    # ------------------------------------------------------------------ orchestration

    def run(self, case_id: uuid.UUID, options: RunOptions | None = None) -> RunSummary:
        options = options or RunOptions(self.settings.pipeline_references)
        options.references = max(1, min(options.references, MAX_REFERENCES))
        summary = RunSummary(case_id)

        def stage(name: str) -> float:
            self._set_stage(case_id, name)
            return time.perf_counter()

        mark = stage("intake")
        ctx = self._intake(case_id)
        summary.seconds["intake"] = time.perf_counter() - mark

        mark = stage("search")
        run_id, summary.search_reused = self._search(ctx, options)
        summary.seconds["search"] = time.perf_counter() - mark

        mark = stage("reference_selection")
        references = self._select_references(ctx, run_id, options)
        summary.references = [r.patent_id for r in references]
        summary.seconds["reference_selection"] = time.perf_counter() - mark

        mark = stage("passage_selection")
        picks = self._select_passages(ctx, references)
        summary.seconds["passage_selection"] = time.perf_counter() - mark

        mark = stage("charting")
        self._chart(ctx, references, picks, summary)
        summary.seconds["charting"] = time.perf_counter() - mark

        mark = stage("risk")
        self._assess(ctx, summary)
        summary.seconds["risk"] = time.perf_counter() - mark

        mark = stage("report")
        self._report(ctx, summary)
        summary.seconds["report"] = time.perf_counter() - mark

        self._finish(case_id)
        return summary

    def _set_stage(self, case_id: uuid.UUID, name: str) -> None:
        with self.sessions() as session:
            case = session.get(Case, case_id)
            if case is None:
                raise PermanentError("case no longer exists")
            case.stage = name
            case.updated_at = datetime.now(UTC)
            session.commit()

    # ------------------------------------------------------------------ 1. intake

    def _intake(self, case_id: uuid.UUID) -> _Context:
        with self.sessions() as session:
            case = session.get(Case, case_id)
            if case is None:
                raise PermanentError("case not found")
            data = load_disclosure(session, self.settings, case_id)
            if data is None or not data.elements:
                raise PermanentError("the case has no disclosure elements")
            return _Context(
                case_id=case_id,
                title=data.title,
                technical_field=data.technical_field,
                problem=data.problem,
                solution=data.solution,
                content_hash=data.content_hash or "",
                elements=[(e.key, e.text) for e in data.elements],
                priority_date=case.priority_date or date.today(),
                case_mode=case.llm_mode,
            )

    # ------------------------------------------------------------------ 2. search

    def _search(self, ctx: _Context, options: RunOptions) -> tuple[uuid.UUID, bool]:
        digest = hashlib.sha256(
            json.dumps(
                [
                    ctx.content_hash,
                    ctx.priority_date.isoformat(),
                    self.settings.rerank_depth,
                    self.settings.result_limit,
                ]
            ).encode()  # fmt: skip
        ).hexdigest()
        if not options.force_search:
            with self.sessions() as session:
                run = latest_run(session, ctx.case_id)
                if run is not None and run.params.get("input_hash") == digest:
                    stored = session.scalar(
                        select(func.count())
                        .select_from(SearchResult)
                        .where(SearchResult.run_id == run.id)
                    )
                    if stored:
                        return run.id, True

        query = DisclosureQuery(
            title=ctx.title,
            summary=_cap_words(f"{ctx.problem} {ctx.solution}".strip(), SUMMARY_WORDS_IN),
            elements=[text for _, text in ctx.elements],
            priority_date=ctx.priority_date,
        )
        service = SearchService(self.sessions, self.embedder, self.reranker, self.settings)
        response = service.search(query)
        with self.sessions() as session:
            run = SearchRun(
                case_id=ctx.case_id,
                params={
                    "input_hash": digest,
                    "priority_date": ctx.priority_date.isoformat(),
                    "elements": len(ctx.elements),
                },  # fmt: skip
                suggested_cpc=[
                    {"subclass": c.subclass, "votes": c.votes} for c in response.suggested_cpc
                ],
                timings_ms={k: round(v, 1) for k, v in response.timings_ms.items()},
                status="done",
            )
            session.add(run)
            session.flush()
            for rank, hit in enumerate(response.hits, start=1):
                session.add(
                    SearchResult(
                        run_id=run.id, patent_id=hit.patent_id, rank=rank, score=hit.score,
                        fused_score=hit.fused_score, rerank_score=hit.rerank_score,
                        matched_chunk_ids=hit.matched_chunk_ids,
                    )
                )  # fmt: skip
            session.commit()
            return run.id, False

    # ------------------------------------------------------------------ 3. reference selection

    def _select_references(
        self, ctx: _Context, run_id: uuid.UUID, options: RunOptions
    ) -> list[ReferenceInfo]:
        """Pinned references (in_chart) win, otherwise the top N that were not excluded."""
        with self.sessions() as session:
            results = session.scalars(
                select(SearchResult)
                .where(SearchResult.run_id == run_id)
                .order_by(SearchResult.rank)
            ).all()
            if options.force_search:
                for row in results:
                    row.in_chart = False
            pinned = [r for r in results if r.in_chart and not r.excluded]
            chosen = (
                pinned[:MAX_REFERENCES]
                if pinned
                else [r for r in results if not r.excluded][: options.references]
            )
            chosen_ids = {r.id for r in chosen}
            for row in results:
                row.in_chart = row.id in chosen_ids
            session.commit()
            return charted_references(session, ctx.case_id)

    # ------------------------------------------------------------------ 4. passage selection

    def _select_passages(
        self, ctx: _Context, references: list[ReferenceInfo]
    ) -> dict[str, dict[str, list[Passage]]]:
        if not references:
            return {}
        vectors = self.embedder.encode_queries([text for _, text in ctx.elements])
        picks: dict[str, dict[str, list[Passage]]] = {}
        for ref in references:
            with self.sessions() as session:
                chunks = load_chunks(session, ref.patent_id)
            passages, matrix = build_passages(
                ref.patent_id, chunks, self.embedder, self.settings.pipeline_passage_words
            )
            chosen = select_for_elements(
                passages, matrix, vectors, self.settings.pipeline_passages_per_element
            )
            picks[ref.patent_id] = {key: chosen[i] for i, (key, _) in enumerate(ctx.elements)}
        return picks

    # ------------------------------------------------------------------ 5. charting

    def _chart(
        self,
        ctx: _Context,
        references: list[ReferenceInfo],
        picks: dict[str, dict[str, list[Passage]]],
        summary: RunSummary,
    ) -> None:
        with self.sessions() as session:
            chart = session.scalar(select(ClaimChart).where(ClaimChart.case_id == ctx.case_id))
            if chart is None:
                chart = ClaimChart(case_id=ctx.case_id, status="running")
                session.add(chart)
            chart.status = "running"
            session.flush()
            chart_id = chart.id
            element_ids = {key: eid for eid, key in element_keys(session, ctx.case_id)}
            known = {
                pid: {key: cell.input_hash for key, cell in cells.items()}
                for pid, cells in cells_by_reference(session, ctx.case_id).items()
            }
            session.commit()

        texts = dict(ctx.elements)
        for ref in references:
            ref_picks = picks.get(ref.patent_id, {})
            todo: dict[str, str] = {}
            for key, text in ctx.elements:
                digest = cell_input_hash(text, ref_picks.get(key, []), self.settings)
                if known.get(ref.patent_id, {}).get(key) == digest:
                    summary.cells_reused += 1
                else:
                    todo[key] = text
            if todo:
                drafts, stats = chart_reference(
                    self.gateway, ref.patent_id, todo, ref_picks, self.settings,
                    case_id=ctx.case_id, case_mode=ctx.case_mode,
                )  # fmt: skip
                summary.charting.merge(stats)
                summary.cells_computed += len(drafts)
                self._store_cells(
                    ctx.case_id, chart_id, element_ids, ref.patent_id, drafts, summary
                )
        summary.cells_total = summary.cells_reused + summary.cells_computed

        keep = [r.patent_id for r in references]
        with self.sessions() as session:
            session.execute(
                delete(ChartCell).where(
                    ChartCell.chart_id == chart_id, ChartCell.patent_id.not_in(keep)
                )
                if keep
                else delete(ChartCell).where(ChartCell.chart_id == chart_id)
            )
            chart = session.get(ClaimChart, chart_id)
            chart.status = "done"
            session.commit()
        stats = summary.charting
        summary.tokens += stats.tokens
        summary.llm_calls += stats.llm_calls
        summary.cache_hits += stats.cache_hits
        summary.llm_used = summary.llm_used or stats.llm_used
        summary.llm_error = summary.llm_error or stats.error
        del texts

    def _store_cells(
        self,
        case_id: uuid.UUID,
        chart_id: uuid.UUID,
        element_ids: dict[str, uuid.UUID],
        patent_id: str,
        drafts: dict[str, CellDraft],
        summary: RunSummary,
    ) -> None:
        with self.sessions() as session:
            chunk_ids = {d.passage.chunk_id for d in drafts.values() if d.passage}
            chunk_text = (
                dict(
                    session.execute(
                        select(PatentChunk.id, PatentChunk.text).where(
                            PatentChunk.id.in_(chunk_ids)
                        )
                    ).all()
                )
                if chunk_ids
                else {}
            )
            for key, draft in drafts.items():
                status, confidence_value = draft.status, draft.confidence
                excerpt, start, end = draft.excerpt, draft.char_start, draft.char_end
                if draft.passage is not None and not classify.excerpt_is_verbatim(
                    excerpt, chunk_text.get(draft.passage.chunk_id, ""), start, end
                ):
                    # Never show text that is not in the source: drop it and trust the cell less.
                    excerpt = start = end = None
                    status = classify.downgrade(status)
                    confidence_value = round(confidence_value * 0.5, 3)
                    summary.excerpts_rejected += 1
                cell = session.scalar(
                    select(ChartCell).where(
                        ChartCell.chart_id == chart_id,
                        ChartCell.element_id == element_ids[key],
                        ChartCell.patent_id == patent_id,
                    )
                )
                if cell is None:
                    cell = ChartCell(chart_id=chart_id, element_id=element_ids[key], patent_id=patent_id,
                                     status=status, confidence=confidence_value, method=draft.method)  # fmt: skip
                    session.add(cell)
                    session.flush()
                elif cell.overridden_at is not None:
                    session.add(
                        ReviewEvent(
                            case_id=case_id,
                            user_id=None,
                            cell_id=cell.id,
                            event_type="cell_reset",
                            comment="The element or its passages changed, so the attorney override was cleared",
                        )  # fmt: skip
                    )
                cell.status, cell.confidence, cell.method = status, confidence_value, draft.method
                cell.passage_id = draft.passage.chunk_id if draft.passage else None
                cell.excerpt, cell.char_start, cell.char_end = excerpt, start, end
                cell.rationale = draft.rationale
                cell.input_hash = draft.input_hash
                cell.original = cell.override_reason = cell.overridden_by = cell.overridden_at = (
                    None
                )
                cell.updated_at = datetime.now(UTC)
            session.commit()

    # ------------------------------------------------------------------ 6. risk

    def _assess(self, ctx: _Context, summary: RunSummary) -> None:
        with self.sessions() as session:
            assessment, _ = load_assessment(session, ctx.case_id)
            case = session.get(Case, ctx.case_id)
            case.risk_level = assessment.level
            case.risk_score = assessment.score
            session.commit()
        summary.risk_level, summary.risk_score = assessment.level, assessment.score

    # ------------------------------------------------------------------ 7. report

    def _executive_summary(self, ctx: _Context, summary: RunSummary) -> str | None:
        """One LLM call over ids and statuses only (no passage text). None means use the template."""
        if self.gateway is None:
            return None
        with self.sessions() as session:
            assessment, references = load_assessment(session, ctx.case_id)
        facts = {
            "risk": assessment.level,
            "score": assessment.score,
            "refs": [r.patent_id for r in references],
            "elements": [
                {"e": row.element, "disclosed_by": row.disclosed_by, "partial_in": row.partial_in}
                for row in assessment.per_element
            ],
        }
        try:
            out = self.gateway.run(
                prompts.EXEC_SUMMARY, prompts.exec_summary_user(facts),
                case_id=ctx.case_id, case_mode=ctx.case_mode,
            )  # fmt: skip
        except LocalOnly:
            summary.llm_error = summary.llm_error or "local_only"
            return None
        except (AllProvidersUnavailable, PromptTooLarge, InvalidOutput) as failure:
            summary.llm_error = summary.llm_error or type(failure).__name__
            return None
        summary.tokens += out.total_tokens
        summary.llm_calls += len(out.calls)
        summary.cache_hits += int(out.cache_hit)
        summary.llm_used = True
        return out.value.summary

    def _report(self, ctx: _Context, summary: RunSummary) -> None:
        text = self._executive_summary(ctx, summary)
        with self.sessions() as session:
            case = session.get(Case, ctx.case_id)
            content = report_service.build_draft_content(
                session, self.settings, case, summary=text, llm_used=text is not None
            )
            report = report_service.get_or_create_report(session, ctx.case_id)
            current = (
                report_service.get_version(session, report) if report.current_version else None
            )
            if current is None or current.content_hash != report_service.canonical_hash(content):
                report_service.add_version(session, self.settings, report, content, None)
                summary.report_created = True
            report.state = "draft"
            summary.report_version = report.current_version
            session.commit()

    def _finish(self, case_id: uuid.UUID) -> None:
        with self.sessions() as session:
            case = session.get(Case, case_id)
            case.status = "draft"
            case.stage = "done"
            case.updated_at = datetime.now(UTC)
            metering.record_report_generated(session, case)  # once per case, reruns are free
            session.commit()
