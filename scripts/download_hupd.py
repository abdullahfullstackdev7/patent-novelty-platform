"""Download Harvard USPTO Patent Dataset (HUPD) archives for chosen years only.

Usage:
    python scripts/download_hupd.py --sample            # sample-jan-2016 (about 370 MB)
    python scripts/download_hupd.py --years 2013 2014   # full-year archives (multi-GB each)
    python scripts/download_hupd.py --metadata          # hupd_metadata_2022-02-22.feather

HUPD license: Hugging Face metadata says CC BY-SA 4.0, the dataset card text says CC BY 4.0.
The stricter CC BY-SA 4.0 is applied. See dataset/README.md.
"""

from __future__ import annotations

import argparse

from _common import RAW, record_download
from huggingface_hub import hf_hub_download

REPO = "HUPD/hupd"
LICENSE = "CC BY-SA 4.0"
METADATA_FILE = "hupd_metadata_2022-02-22.feather"


def fetch(filename: str) -> None:
    """hf_hub_download resumes interrupted transfers and validates size on completion."""
    local = hf_hub_download(
        repo_id=REPO, repo_type="dataset", filename=filename, local_dir=RAW / "hupd"
    )
    from pathlib import Path

    path = Path(local)
    url = f"https://huggingface.co/datasets/{REPO}/resolve/main/{filename}"
    entry = record_download(f"hupd:{filename}", url, path, LICENSE)
    print(f"{filename}: {entry['bytes']:,} bytes sha256={entry['sha256']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sample", action="store_true", help="sample-jan-2016 archive")
    parser.add_argument("--years", nargs="*", type=int, default=[], help="years 2004 to 2018")
    parser.add_argument("--metadata", action="store_true", help="download the metadata feather")
    args = parser.parse_args()

    files: list[str] = []
    if args.sample:
        files.append("data/sample-jan-2016.tar.gz")
    for year in args.years:
        if not 2004 <= year <= 2018:
            parser.error(f"HUPD covers 2004 to 2018, got {year}")
        files.append(f"data/{year}.tar.gz")
    if args.metadata:
        files.append(METADATA_FILE)
    if not files:
        parser.error("choose at least one of --sample, --years, --metadata")
    for filename in files:
        fetch(filename)


if __name__ == "__main__":
    main()
