"""Shared helpers for dataset scripts: paths, checksums, resumable download, manifest."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
DATASET = ROOT / "dataset"
RAW = DATASET / "raw"
PROCESSED = DATASET / "processed"
DEMO = DATASET / "demo"
MANIFEST = RAW / "manifest.json"


def sha256_file(path: Path, block: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(block):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest() -> dict[str, dict]:
    if MANIFEST.exists():
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    return {}


def record_download(name: str, url: str, path: Path, license_name: str) -> dict:
    """Record file, URL, license, download date and checksum in raw/manifest.json."""
    entry = {
        "file": str(path.relative_to(ROOT)).replace("\\", "/"),
        "url": url,
        "license": license_name,
        "downloaded": datetime.now(UTC).date().isoformat(),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }
    manifest = load_manifest()
    manifest[name] = entry
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return entry


def download_resumable(url: str, dest: Path, timeout: float = 60.0) -> Path:
    """Stream url to dest, resuming a partial `.part` file with an HTTP Range request."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        return dest
    part = dest.with_suffix(dest.suffix + ".part")
    start = part.stat().st_size if part.exists() else 0
    headers = {"Range": f"bytes={start}-"} if start else {}
    with httpx.stream(
        "GET", url, headers=headers, timeout=timeout, follow_redirects=True
    ) as response:
        if response.status_code == 416:  # already fully downloaded
            part.replace(dest)
            return dest
        response.raise_for_status()
        mode = "ab" if start and response.status_code == 206 else "wb"
        with part.open(mode) as handle:
            for chunk in response.iter_bytes(1 << 20):
                handle.write(chunk)
    part.replace(dest)
    return dest
