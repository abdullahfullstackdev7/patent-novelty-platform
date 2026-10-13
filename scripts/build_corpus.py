"""Build corpus.parquet and chunks.parquet from HUPD archives and PatentsView bulk tables.

Examples:
    python scripts/build_corpus.py --hupd dataset/raw/hupd/data/sample-jan-2016.tar.gz --write-demo
    python scripts/build_corpus.py --patentsview-years 2020 2021 --max-patentsview 60000
    python scripts/build_corpus.py --demo-jsonl dataset/demo/patents.jsonl --out dataset/processed

Outputs (default dataset/processed/):
    corpus.parquet   one row per patent document
    chunks.parquet   one row per claim, abstract, summary passage and description passage
    build_stats.json row counts, drop reasons and duplicate counts for dataset/README.md
    dataset/demo/patents.jsonl   deterministic sample for tests and the quick start path

Chunk offsets (char_start, char_end) index into the cleaned source field the chunk came from
(the claim text for claims, the abstract, the summary or the description), and text always
equals field[char_start:char_end].
"""

from __future__ import annotations

import argparse
import json
import math
import re
import tarfile
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from _common import DEMO, PROCESSED, RAW
from text_utils import (
    Claim,
    chunk_passages,
    classify_claim,
    clean_text,
    parse_claims,
    strip_claim_numbering,
)

TARGET_CPC = ["G06N", "G06F", "G06Q", "G16H", "H04L", "H04W", "H01M", "B60L", "A61B", "C12N"]
SOURCE_HUPD = "HUPD_APP"
SOURCE_PV = "PV_GRANT"
MAX_DEMO_WORDS = 1500

CHUNK_SCHEMA = pa.schema(
    [
        ("chunk_id", pa.string()),
        ("patent_id", pa.string()),
        ("chunk_type", pa.string()),
        ("claim_number", pa.int32()),
        ("is_independent", pa.bool_()),
        ("parent_claim", pa.int32()),
        ("seq", pa.int32()),
        ("text", pa.string()),
        ("char_start", pa.int32()),
        ("char_end", pa.int32()),
        ("n_words", pa.int32()),
    ]
)

# Canonical name -> accepted column names. Confirm against the PatentsView data dictionary.
COLUMN_ALIASES: dict[str, dict[str, list[str]]] = {
    "g_patent": {
        "patent_id": ["patent_id"],
        "patent_type": ["patent_type", "type"],
        "patent_date": ["patent_date", "date"],
        "title": ["patent_title", "title"],
    },
    "g_patent_abstract": {"patent_id": ["patent_id"], "abstract": ["patent_abstract", "abstract"]},
    "g_cpc_current": {
        "patent_id": ["patent_id"],
        "sequence": ["cpc_sequence", "sequence"],
        "subclass": ["cpc_subclass", "subclass_id"],
        "group": ["cpc_group", "group_id"],
    },
    "g_assignee_disambiguated": {
        "patent_id": ["patent_id"],
        "sequence": ["assignee_sequence", "sequence"],
        "organization": ["disambig_assignee_organization", "organization"],
        "first": ["disambig_assignee_individual_name_first", "name_first"],
        "last": ["disambig_assignee_individual_name_last", "name_last"],
    },
    "g_claims": {
        "patent_id": ["patent_id"],
        "sequence": ["claim_sequence", "sequence"],
        "text": ["claim_text", "text"],
    },
    "g_brf_sum_text": {"patent_id": ["patent_id"], "text": ["summary_text", "text"]},
}


@dataclass
class PatentRecord:
    patent_id: str
    source: str
    title: str
    abstract: str = ""
    claims: list[Claim] = field(default_factory=list)
    summary: str = ""
    description: str = ""
    filing_date: str | None = None
    publication_date: str | None = None
    grant_date: str | None = None
    assignee: str | None = None
    cpc_codes: list[str] = field(default_factory=list)
    url: str = ""

    @property
    def main_subclass(self) -> str:
        return self.cpc_codes[0][:4] if self.cpc_codes else ""

    @property
    def cpc_subclasses(self) -> list[str]:
        """Unique CPC subclasses in order. The first four characters of any CPC code."""
        return list(dict.fromkeys(code[:4] for code in self.cpc_codes if code))


def iso_date(value: Any) -> str | None:
    text = str(value or "").strip()
    if re.fullmatch(r"\d{8}", text):
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text[:10]):
        return text[:10]
    return None


_XML_RESIDUE = re.compile(r'[\w-]+\s+description="[^"]*"(?:\s+end="[^"]*")?\s*\??')


def clean_hupd_text(text: str | None) -> str:
    """Drop <SOH> heading <EOH> markers and XML residue, repair the lost section sign."""
    text = re.sub(r"<SOH>.*?<EOH>", " ", text or "", flags=re.DOTALL)
    text = _XML_RESIDUE.sub(" ", text)
    text = re.sub(r"�(?=\s?\d)", "§", text).replace("�", "")
    return clean_text(text)


_SMALL_WORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "by",
    "for",
    "in",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}


def title_case(text: str) -> str:
    """HUPD titles are upper case. Capitalize words and keep short function words lower."""
    words = clean_text(text).lower().split()
    return " ".join(
        word if index and word in _SMALL_WORDS else word.capitalize()
        for index, word in enumerate(words)
    )


def truncate_words(text: str, limit: int) -> str:
    """Cut at a sentence end at or before `limit` words."""
    words = text.split()
    if len(words) <= limit:
        return text
    cut = len(" ".join(words[:limit]))
    end = text.rfind(". ", 0, cut)
    return text[: end + 1] if end > 0 else text[:cut]


# ---------------------------------------------------------------- HUPD


def iter_hupd(archive: Path, cpc_filter: set[str]) -> Iterator[PatentRecord]:
    with tarfile.open(archive, "r:*") as tar:
        for member in tar:
            if not member.isfile() or not member.name.endswith(".json"):
                continue
            handle = tar.extractfile(member)
            if handle is None:
                continue
            try:
                raw = json.load(handle)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            labels = [str(label) for label in raw.get("cpc_labels") or []]
            main = str(raw.get("main_cpc_label") or "")
            if main:
                if main in labels:
                    labels.remove(main)
                labels.insert(0, main)
            if not any(label[:4] in cpc_filter for label in labels):
                continue
            patent_id = str(raw.get("publication_number") or "").split("-")[0]
            if not patent_id:
                continue
            yield PatentRecord(
                patent_id=patent_id,
                source=SOURCE_HUPD,
                title=title_case(raw.get("title")),
                abstract=clean_hupd_text(raw.get("abstract")),
                claims=parse_claims(raw.get("claims")),
                summary=clean_hupd_text(raw.get("summary")),
                description=clean_hupd_text(raw.get("full_description")),
                filing_date=iso_date(raw.get("filing_date")),
                publication_date=iso_date(raw.get("date_published")),
                grant_date=iso_date(raw.get("patent_issue_date")),
                assignee=None,
                cpc_codes=labels,
                url=f"https://patents.google.com/patent/{patent_id}",
            )


# ---------------------------------------------------------------- PatentsView


def _resolve(frame: pd.DataFrame, table: str) -> pd.DataFrame:
    """Rename source columns to canonical names using COLUMN_ALIASES."""
    rename: dict[str, str] = {}
    for canonical, options in COLUMN_ALIASES[table].items():
        found = next((name for name in options if name in frame.columns), None)
        if found is None:
            raise KeyError(
                f"{table}: none of {options} in columns {list(frame.columns)}. "
                "Check the data dictionary and update COLUMN_ALIASES."
            )
        rename[found] = canonical
    return frame[list(rename)].rename(columns=rename)


def _read_tsv(path: Path, table: str, chunksize: int = 250_000) -> Iterator[pd.DataFrame]:
    reader = pd.read_csv(
        path, sep="\t", dtype=str, keep_default_na=False, chunksize=chunksize,
        quoting=3, on_bad_lines="skip", encoding="utf-8", encoding_errors="replace",
    )  # fmt: skip
    for frame in reader:
        yield _resolve(frame, table)


def _find(directory: Path, name: str) -> Path:
    for candidate in (f"{name}.tsv.zip", f"{name}.tsv"):
        if (directory / candidate).exists():
            return directory / candidate
    raise FileNotFoundError(f"{name}.tsv(.zip) not found in {directory}")


def iter_patentsview(
    directory: Path, years: list[int], cpc_filter: set[str], limit: int
) -> Iterator[PatentRecord]:
    """Join PatentsView tables for utility patents granted in `years` within target CPC areas."""
    year_prefixes = tuple(str(year) for year in years)
    candidates: dict[str, dict[str, str]] = {}
    for frame in _read_tsv(_find(directory, "g_patent"), "g_patent"):
        frame = frame[
            (frame["patent_type"].str.lower() == "utility")
            & frame["patent_date"].str.startswith(year_prefixes)
        ]
        for row in frame.itertuples(index=False):
            candidates[row.patent_id] = {"date": row.patent_date, "title": row.title}

    cpc: dict[str, list[tuple[str, str]]] = {}
    for frame in _read_tsv(_find(directory, "g_cpc_current"), "g_cpc_current"):
        frame = frame[frame["patent_id"].isin(candidates)]
        frame = frame.assign(order=pd.to_numeric(frame["sequence"], errors="coerce"))
        for row in frame.sort_values("order", kind="stable").itertuples(index=False):
            cpc.setdefault(row.patent_id, []).append((row.subclass, row.group))
    selected = [
        pid
        for pid in sorted(candidates)
        if any(sub in cpc_filter for sub, _group in cpc.get(pid, []))
    ][:limit]
    chosen = set(selected)

    abstracts: dict[str, str] = {}
    for frame in _read_tsv(_find(directory, "g_patent_abstract"), "g_patent_abstract"):
        for row in frame[frame["patent_id"].isin(chosen)].itertuples(index=False):
            abstracts[row.patent_id] = row.abstract

    assignees: dict[str, tuple[float, str]] = {}
    for frame in _read_tsv(
        _find(directory, "g_assignee_disambiguated"), "g_assignee_disambiguated"
    ):
        for row in frame[frame["patent_id"].isin(chosen)].itertuples(index=False):
            name = row.organization or f"{row.first} {row.last}".strip()
            order = pd.to_numeric(row.sequence, errors="coerce")
            if name and (row.patent_id not in assignees or order < assignees[row.patent_id][0]):
                assignees[row.patent_id] = (order, name)

    claims_raw: dict[str, list[tuple[int, str]]] = {}
    summaries: dict[str, list[str]] = {}
    for year in years:
        for frame in _read_tsv(_find(directory, f"g_claims_{year}"), "g_claims"):
            for row in frame[frame["patent_id"].isin(chosen)].itertuples(index=False):
                claims_raw.setdefault(row.patent_id, []).append(
                    (int(pd.to_numeric(row.sequence, errors="coerce")), row.text)
                )
        try:
            summary_path = _find(directory, f"g_brf_sum_text_{year}")
        except FileNotFoundError:
            continue
        for frame in _read_tsv(summary_path, "g_brf_sum_text"):
            for row in frame[frame["patent_id"].isin(chosen)].itertuples(index=False):
                summaries.setdefault(row.patent_id, []).append(row.text)

    for pid in selected:
        claims: list[Claim] = []
        for number, (_seq, text) in enumerate(sorted(claims_raw.get(pid, [])), start=1):
            body = strip_claim_numbering(clean_text(text), number)
            if not body:
                continue
            independent, parent = classify_claim(number, body)
            claims.append(Claim(number, body, independent, parent))
        yield PatentRecord(
            patent_id=f"US{pid}",
            source=SOURCE_PV,
            title=clean_text(candidates[pid]["title"]),
            abstract=clean_text(abstracts.get(pid)),
            claims=claims,
            summary=clean_text(" ".join(summaries.get(pid, []))),
            grant_date=iso_date(candidates[pid]["date"]),
            publication_date=iso_date(candidates[pid]["date"]),
            assignee=assignees.get(pid, (0, None))[1],
            cpc_codes=[group for _sub, group in cpc.get(pid, [])],
            url=f"https://patents.google.com/patent/US{pid}",
        )


# ---------------------------------------------------------------- demo JSONL


def record_to_demo(rec: PatentRecord) -> dict[str, Any]:
    return {
        "patent_id": rec.patent_id,
        "source": rec.source,
        "title": rec.title,
        "abstract": rec.abstract,
        "claims": [
            {
                "number": c.number,
                "text": c.text,
                "is_independent": c.is_independent,
                "parent": c.parent,
            }
            for c in rec.claims
        ],
        "summary": truncate_words(rec.summary, MAX_DEMO_WORDS),
        "description": truncate_words(rec.description, MAX_DEMO_WORDS),
        "filing_date": rec.filing_date,
        "publication_date": rec.publication_date,
        "grant_date": rec.grant_date,
        "assignee": rec.assignee,
        "cpc_codes": rec.cpc_codes,
        "url": rec.url,
    }


def iter_demo(path: Path) -> Iterator[PatentRecord]:
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            raw = json.loads(line)
            claims = [
                Claim(c["number"], c["text"], c["is_independent"], c["parent"])
                for c in raw.pop("claims")
            ]
            yield PatentRecord(claims=claims, **raw)


def pick_demo(buckets: dict[str, list[PatentRecord]], size: int) -> list[PatentRecord]:
    """Round-robin over main CPC subclasses so the sample covers every technology area."""
    picked: list[PatentRecord] = []
    queues = [list(records) for _key, records in sorted(buckets.items())]
    while len(picked) < size and any(queues):
        for queue in queues:
            if queue and len(picked) < size:
                picked.append(queue.pop(0))
    return sorted(picked, key=lambda record: record.patent_id)


# ---------------------------------------------------------------- chunking + writing


def build_chunks(rec: PatentRecord, max_summary: int, max_description: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    def add(kind: str, seq: int, text: str, start: int, end: int, claim: Claim | None = None):
        rows.append(
            {
                "chunk_id": f"{rec.patent_id}:{kind}:{seq}",
                "patent_id": rec.patent_id,
                "chunk_type": kind,
                "claim_number": claim.number if claim else None,
                "is_independent": claim.is_independent if claim else None,
                "parent_claim": claim.parent if claim else None,
                "seq": seq,
                "text": text,
                "char_start": start,
                "char_end": end,
                "n_words": len(text.split()),
            }
        )

    for claim in rec.claims:
        add("claim", claim.number, claim.text, 0, len(claim.text), claim)
    if rec.abstract:
        add("abstract", 0, rec.abstract, 0, len(rec.abstract))
    for kind, text, cap in (
        ("summary", rec.summary, max_summary),
        ("description", rec.description, max_description),
    ):
        for seq, (passage, start, end) in enumerate(chunk_passages(text)[:cap]):
            add(kind, seq, passage, start, end)
    return rows


def corpus_row(rec: PatentRecord) -> dict[str, Any]:
    return {
        "patent_id": rec.patent_id,
        "source": rec.source,
        "title": rec.title,
        "abstract": rec.abstract,
        "filing_date": rec.filing_date,
        "publication_date": rec.publication_date,
        "grant_date": rec.grant_date,
        "assignee": rec.assignee,
        "cpc_codes": rec.cpc_codes,
        "cpc_subclasses": rec.cpc_subclasses,
        "main_subclass": rec.main_subclass,
        "n_claims": len(rec.claims),
        "n_independent": sum(c.is_independent for c in rec.claims),
        "n_summary_words": len(rec.summary.split()),
        "url": rec.url,
    }


def build(args: argparse.Namespace) -> dict[str, Any]:
    cpc_filter = set(args.cpc)
    streams: list[tuple[str, Iterator[PatentRecord], int]] = []
    for archive in args.hupd or []:
        streams.append((SOURCE_HUPD, iter_hupd(Path(archive), cpc_filter), args.max_hupd))
    if args.patentsview_years:
        streams.append(
            (
                SOURCE_PV,
                iter_patentsview(
                    Path(args.patentsview_dir),
                    args.patentsview_years,
                    cpc_filter,
                    args.max_patentsview,
                ),
                args.max_patentsview,
            )
        )
    if args.demo_jsonl:
        streams.append(("DEMO", iter_demo(Path(args.demo_jsonl)), 10**9))

    args.out.mkdir(parents=True, exist_ok=True)
    writer = pq.ParquetWriter(args.out / "chunks.parquet", CHUNK_SCHEMA, compression="zstd")
    corpus: list[dict[str, Any]] = []
    seen: set[str] = set()
    stats: Counter[str] = Counter()
    per_source: Counter[str] = Counter()
    chunks_by_type: Counter[str] = Counter()
    buffer: list[dict[str, Any]] = []
    demo_buckets: dict[str, list[PatentRecord]] = {}
    demo_quota = math.ceil(args.demo_size / max(len(cpc_filter), 1)) + 2

    def flush() -> None:
        if buffer:
            writer.write_table(pa.Table.from_pylist(buffer, schema=CHUNK_SCHEMA))
            buffer.clear()

    for source, stream, limit in streams:
        for rec in stream:
            if per_source[source] >= limit:
                break
            if rec.patent_id in seen:
                stats["dropped_duplicate_patent_id"] += 1
                continue
            if not rec.claims:
                stats["dropped_no_claims"] += 1
                continue
            if not rec.abstract and not rec.summary:
                stats["dropped_no_text"] += 1
                continue
            seen.add(rec.patent_id)
            per_source[source] += 1
            corpus.append(corpus_row(rec))
            rows = build_chunks(rec, args.max_summary_chunks, args.max_description_chunks)
            for row in rows:
                chunks_by_type[row["chunk_type"]] += 1
            buffer.extend(rows)
            if len(buffer) >= 20_000:
                flush()
            bucket = demo_buckets.setdefault(rec.main_subclass, [])
            if len(bucket) < demo_quota:
                bucket.append(rec)
    flush()
    writer.close()

    pd.DataFrame(corpus).to_parquet(args.out / "corpus.parquet", index=False, compression="zstd")

    if args.write_demo and corpus:
        picked = pick_demo(demo_buckets, args.demo_size)
        DEMO.mkdir(parents=True, exist_ok=True)
        with (DEMO / "patents.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
            for rec in picked:
                handle.write(json.dumps(record_to_demo(rec), ensure_ascii=False) + "\n")
        stats["demo_patents"] = len(picked)

    summary = {
        "patents": len(corpus),
        "chunks": sum(chunks_by_type.values()),
        "patents_by_source": dict(per_source),
        "chunks_by_type": dict(chunks_by_type),
        "dropped": {k: v for k, v in stats.items() if k.startswith("dropped")},
        "demo_patents": stats.get("demo_patents", 0),
    }
    (args.out / "build_stats.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--hupd", nargs="*", help="HUPD .tar.gz archives")
    parser.add_argument("--patentsview-years", nargs="*", type=int)
    parser.add_argument("--patentsview-dir", default=str(RAW / "patentsview"))
    parser.add_argument("--demo-jsonl", help="build from a demo JSONL instead of raw sources")
    parser.add_argument("--cpc", nargs="*", default=TARGET_CPC, help="CPC subclass filter")
    parser.add_argument("--max-hupd", type=int, default=20_000)
    parser.add_argument("--max-patentsview", type=int, default=60_000)
    parser.add_argument("--max-summary-chunks", type=int, default=20)
    parser.add_argument("--max-description-chunks", type=int, default=40)
    parser.add_argument("--demo-size", type=int, default=500)
    parser.add_argument("--write-demo", action="store_true", help="write the demo JSONL")
    parser.add_argument("--out", type=Path, default=PROCESSED)
    args = parser.parse_args()
    if not (args.hupd or args.patentsview_years or args.demo_jsonl):
        parser.error("give --hupd, --patentsview-years or --demo-jsonl")
    build(args)


if __name__ == "__main__":
    main()
