import argparse
import io
import json
import tarfile
import zipfile
from pathlib import Path

import build_corpus
import pandas as pd
import pytest
import validate_corpus
from build_corpus import clean_hupd_text, iso_date, iter_patentsview, title_case

SENTENCE = "The controller receives sensor readings and updates the stored model parameters. "
LONG_TEXT = SENTENCE * 12  # about 120 words, one passage


def make_args(out: Path, **overrides) -> argparse.Namespace:
    values = {
        "hupd": None,
        "patentsview_years": None,
        "patentsview_dir": "",
        "demo_jsonl": None,
        "cpc": build_corpus.TARGET_CPC,
        "max_hupd": 1000,
        "max_patentsview": 1000,
        "max_summary_chunks": 20,
        "max_description_chunks": 40,
        "demo_size": 4,
        "write_demo": False,
        "out": out,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def hupd_record(number: str, cpc: str = "G06N3000", claims: str | None = None) -> dict:
    return {
        "publication_number": f"US{number}A1-20160804",
        "title": "SYSTEM AND METHOD FOR LEARNING",
        "main_cpc_label": cpc,
        "cpc_labels": [cpc] if cpc.startswith("F16") else [cpc, "H04L9000"],
        "filing_date": "20160128",
        "date_published": "20160804",
        "patent_issue_date": "",
        "abstract": "A system learns models. " * 5,
        "claims": (
            "1. A method comprising: training a model. 2. The method of claim 1, wherein X."
            if claims is None
            else claims
        ),
        "summary": "<SOH> SUMMARY <EOH>" + LONG_TEXT,
        "full_description": LONG_TEXT * 3,
    }


def write_tar(path: Path, records: list[dict]) -> Path:
    with tarfile.open(path, "w:gz") as tar:
        for index, record in enumerate(records):
            data = json.dumps(record).encode()
            info = tarfile.TarInfo(f"sample/2016/{index}.json")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return path


def test_helpers():
    assert iso_date("20160804") == "2016-08-04"
    assert iso_date("") is None
    assert title_case("SYSTEM AND METHOD FOR THE LEARNING") == "System and Method for the Learning"
    cleaned = clean_hupd_text(
        '<SOH> HEAD <EOH>under 35 U.S.C. �119 detailed-description description="D" end="lead"? body'
    )
    assert "§119" in cleaned and "description=" not in cleaned and "HEAD" not in cleaned


def test_build_from_hupd_filters_dedupes_and_writes_demo(tmp_path, monkeypatch):
    monkeypatch.setattr(build_corpus, "DEMO", tmp_path / "demo")
    records = [
        hupd_record("1001"),
        hupd_record("1001"),  # duplicate id
        hupd_record("1002", cpc="F16H0001"),  # outside target CPC areas
        hupd_record("1003", claims=""),  # no claims
        hupd_record("1004", cpc="A61B1000"),
    ]
    archive = write_tar(tmp_path / "hupd.tar.gz", records)
    out = tmp_path / "out"
    summary = build_corpus.build(make_args(out, hupd=[archive], write_demo=True))

    assert summary["patents"] == 2
    assert summary["dropped"] == {"dropped_duplicate_patent_id": 1, "dropped_no_claims": 1}
    corpus = pd.read_parquet(out / "corpus.parquet")
    chunks = pd.read_parquet(out / "chunks.parquet")
    assert set(corpus["patent_id"]) == {"US1001A1", "US1004A1"}
    assert corpus.loc[corpus.patent_id == "US1001A1", "cpc_subclasses"].iloc[0].tolist() == [
        "G06N",
        "H04L",
    ]
    assert set(chunks["chunk_type"]) == {"claim", "abstract", "summary", "description"}
    assert validate_corpus.check(corpus, chunks) == []

    # chunk offsets reproduce the text for summary and description passages
    demo = tmp_path / "demo" / "patents.jsonl"
    assert len(demo.read_text(encoding="utf-8").splitlines()) == 2

    # round trip: demo JSONL rebuilds an identical corpus
    rebuilt = build_corpus.build(make_args(tmp_path / "out2", demo_jsonl=str(demo)))
    assert rebuilt["patents"] == 2
    chunks2 = pd.read_parquet(tmp_path / "out2" / "chunks.parquet")
    claims1 = chunks[chunks.chunk_type == "claim"].sort_values("chunk_id")["text"].tolist()
    claims2 = chunks2[chunks2.chunk_type == "claim"].sort_values("chunk_id")["text"].tolist()
    assert claims1 == claims2


def write_zip(path: Path, rows: list[list[str]]) -> None:
    text = "\n".join("\t".join(row) for row in rows) + "\n"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(path.name.removesuffix(".zip"), text)


@pytest.fixture
def patentsview_dir(tmp_path: Path) -> Path:
    d = tmp_path / "pv"
    d.mkdir()
    write_zip(
        d / "g_patent.tsv.zip",
        [
            ["patent_id", "patent_type", "patent_date", "patent_title", "num_claims"],
            ["10000001", "utility", "2020-01-07", "Neural widget", "2"],
            ["10000002", "utility", "2020-01-14", "Gearbox", "1"],  # wrong CPC
            ["D0900001", "design", "2020-01-14", "Ornamental", "1"],  # design patent
            ["9000001", "utility", "2014-01-07", "Old", "1"],  # out of range
        ],
    )
    write_zip(
        d / "g_cpc_current.tsv.zip",
        [
            ["patent_id", "cpc_sequence", "cpc_section", "cpc_class", "cpc_subclass", "cpc_group"],
            ["10000001", "1", "G", "G06", "G06N", "G06N3/08"],
            ["10000001", "0", "H", "H04", "H04L", "H04L9/32"],
            ["10000002", "0", "F", "F16", "F16H", "F16H1/00"],
        ],
    )
    write_zip(
        d / "g_patent_abstract.tsv.zip",
        [["patent_id", "patent_abstract"], ["10000001", "A neural widget learns."]],
    )
    write_zip(
        d / "g_assignee_disambiguated.tsv.zip",
        [
            [
                "patent_id",
                "assignee_sequence",
                "disambig_assignee_individual_name_first",
                "disambig_assignee_individual_name_last",
                "disambig_assignee_organization",
            ],
            ["10000001", "1", "", "", "Second Corp"],
            ["10000001", "0", "", "", "First Corp"],
        ],
    )
    write_zip(
        d / "g_claims_2020.tsv.zip",
        [
            ["patent_id", "claim_sequence", "claim_text", "dependent", "claim_number", "exemplary"],
            ["10000001", "1", "2. The widget of claim 1, wherein Y.", "claim 1", "2", "0"],
            ["10000001", "0", "1. A widget comprising a neural core.", "", "1", "1"],
        ],
    )
    write_zip(
        d / "g_brf_sum_text_2020.tsv.zip",
        [["patent_id", "summary_text"], ["10000001", LONG_TEXT.strip()]],
    )
    return d


def test_patentsview_join(patentsview_dir):
    records = list(iter_patentsview(patentsview_dir, [2020], set(build_corpus.TARGET_CPC), 100))
    assert len(records) == 1
    rec = records[0]
    assert rec.patent_id == "US10000001" and rec.source == "PV_GRANT"
    assert rec.assignee == "First Corp"
    assert rec.grant_date == rec.publication_date == "2020-01-07"
    assert rec.cpc_codes == ["H04L9/32", "G06N3/08"]  # ordered by cpc_sequence
    assert [(c.number, c.is_independent, c.parent) for c in rec.claims] == [
        (1, True, None),
        (2, False, 1),
    ]
    assert rec.claims[0].text == "A widget comprising a neural core."


def test_patentsview_missing_column_names_the_table(patentsview_dir):
    write_zip(patentsview_dir / "g_patent.tsv.zip", [["id", "kind"], ["1", "utility"]])
    with pytest.raises(KeyError, match="g_patent"):
        list(iter_patentsview(patentsview_dir, [2020], set(build_corpus.TARGET_CPC), 10))


def test_validator_detects_duplicates_and_bad_dependents():
    corpus = pd.DataFrame(
        {
            "patent_id": ["a", "a"],
            "title": ["t", "t"],
            "publication_date": ["2020-01-01"] * 2,
            "source": ["HUPD_APP"] * 2,
        }
    )
    chunks = pd.DataFrame(
        {
            "chunk_id": ["a:claim:1", "a:claim:2"],
            "patent_id": ["a", "a"],
            "chunk_type": ["claim", "claim"],
            "claim_number": [1, 2],
            "is_independent": [False, False],
            "parent_claim": [1, 5],
            "seq": [1, 2],
            "text": ["x", "y"],
            "char_start": [0, 0],
            "char_end": [1, 1],
        }
    )
    problems = validate_corpus.check(corpus, chunks)
    assert any("duplicate patent_id" in p for p in problems)
    assert any("reference a later claim" in p for p in problems)
    assert any("without an independent claim" in p for p in problems)
