#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "[check] Python virtualenv is missing: ${PYTHON_BIN}" >&2
  echo "[check] Create it with: python3.12 -m venv .venv && ./.venv/bin/pip install -r requirements_agent.txt" >&2
  exit 1
fi

exec "${PYTHON_BIN}" -m pytest -q "$@"
