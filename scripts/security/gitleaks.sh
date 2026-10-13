#!/usr/bin/env bash
# Secrets scan of the working tree. Config and allowlist: .gitleaks.toml
set -euo pipefail
cd "$(dirname "$0")/../.."
MSYS_NO_PATHCONV=1 docker run --rm -v "$PWD:/repo" zricethezav/gitleaks:latest \
  dir /repo --config /repo/.gitleaks.toml --no-banner -v
