#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${PROJECT_DIR}/.venv"

if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  echo "Python não encontrado. Instale Python 3.11+ e tente novamente." >&2
  exit 1
fi

"${PYTHON_BIN}" -c 'import sys; raise SystemExit(sys.version_info < (3, 11))' || {
  echo "É necessário Python 3.11 ou mais recente." >&2
  exit 1
}

if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
  "${PYTHON_BIN}" -m venv "${VENV_DIR}"
fi

"${VENV_DIR}/bin/python" -m pip install --upgrade pip setuptools wheel
"${VENV_DIR}/bin/python" -m pip install --editable "${PROJECT_DIR}[dev]"

echo
echo "Ambiente pronto."
echo "Execute: ${PROJECT_DIR}/scripts/run-demo.sh"

