#!/usr/bin/env bash
# Passive OWASP ZAP scan of the API's OpenAPI definition (no active attacks, safe for dev data).
# Start the API first, for example:
#   cd backend && uv run uvicorn app.main:create_app --factory --port 8765
# Usage: scripts/security/zap_api_scan.sh [port] [report-dir]
set -euo pipefail
PORT="${1:-8765}"
OUT="${2:-$(pwd)/zap-report}"
mkdir -p "$OUT"
MSYS_NO_PATHCONV=1 docker run --rm -v "$OUT:/zap/wrk:rw" ghcr.io/zaproxy/zaproxy:stable \
  zap-api-scan.py -t "http://host.docker.internal:${PORT}/openapi.json" -f openapi -S \
  -J zap.json -r zap.html -I
# A FAIL-NEW count above zero means a medium or high finding. Warnings are reviewed by hand.
