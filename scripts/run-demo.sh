#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PROJECT_DIR}/.venv/bin/python"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "Ambiente virtual ausente. Execute ./scripts/bootstrap.sh primeiro." >&2
  exit 1
fi

exec "${PYTHON_BIN}" -m rf_sense serve --simulate

