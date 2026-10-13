"""Download PatentsView granted-patent bulk tables (CC BY 4.0, attribute PatentsView).

PatentsView moved into the USPTO Open Data Portal (https://data.uspto.gov/bulkdata). The
legacy S3 location is no longer publicly readable at the time of writing, so the base URL is
configurable. Resolve the current file URLs from the portal, then either:

    PATENTSVIEW_BASE_URL=https://<host>/<path> python scripts/download_patentsview.py --years 2020
    python scripts/download_patentsview.py --from-dir <folder with already downloaded zips>

`--from-dir` registers manually downloaded files (copy plus checksum) without any network call.
Always compare column names with the data dictionary published next to the files before
running build_corpus.py. The loader maps columns through COLUMN_ALIASES in build_corpus.py.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

from _common import RAW, download_resumable, record_download

LICENSE = "CC BY 4.0 (attribution: PatentsView)"
DEFAULT_BASE = "https://s3.amazonaws.com/data.patentsview.org/download"
STATIC_FILES = [
    "g_patent.tsv.zip",
    "g_patent_abstract.tsv.zip",
    "g_cpc_current.tsv.zip",
    "g_assignee_disambiguated.tsv.zip",
]
YEARLY_PATTERNS = ["g_claims_{year}.tsv.zip", "g_brf_sum_text_{year}.tsv.zip"]
CITATION_FILE = "g_us_patent_citation.tsv.zip"  # evaluation ground truth only (Phase 10)
DEST = RAW / "patentsview"


def wanted_files(years: list[int], with_citations: bool) -> list[str]:
    files = list(STATIC_FILES)
    for year in years:
        files.extend(pattern.format(year=year) for pattern in YEARLY_PATTERNS)
    if with_citations:
        files.append(CITATION_FILE)
    return files


def register(path: Path, url: str) -> None:
    entry = record_download(f"patentsview:{path.name}", url, path, LICENSE)
    print(f"{path.name}: {entry['bytes']:,} bytes sha256={entry['sha256']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--years", nargs="+", type=int, required=True, help="e.g. 2015 2016")
    parser.add_argument("--citations", action="store_true", help="also fetch g_us_patent_citation")
    parser.add_argument("--from-dir", type=Path, help="register files downloaded manually")
    args = parser.parse_args()

    base = os.environ.get("PATENTSVIEW_BASE_URL", DEFAULT_BASE).rstrip("/")
    failures = 0
    for name in wanted_files(args.years, args.citations):
        target = DEST / name
        try:
            if args.from_dir:
                source = args.from_dir / name
                if not source.exists():
                    raise FileNotFoundError(source)
                DEST.mkdir(parents=True, exist_ok=True)
                if not target.exists():
                    shutil.copy2(source, target)
                register(target, f"manual:{source.name}")
            else:
                download_resumable(f"{base}/{name}", target)
                register(target, f"{base}/{name}")
        except Exception as error:  # report every file, then fail once at the end
            failures += 1
            print(f"FAILED {name}: {error}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
