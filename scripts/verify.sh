#!/usr/bin/env bash
# Canonical local verification. CI runs exactly this.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== ruff check";        uv run ruff check .
echo "== ruff format";       uv run ruff format --check .
echo "== pytest";            uv run pytest -q
echo "== uv audit";          uv audit
echo "== all gates passed"
