#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "[check] Python virtualenv is missing: ${PYTHON_BIN}" >&2
  echo "[check] Create it with: python3.12 -m venv .venv && ./.venv/bin/pip install -r requirements_agent.txt" >&2
  exit 1
fi

if [[ "${1:-}" == "--all" ]]; then
  shift
  exec "${PYTHON_BIN}" -m pytest -q "$@"
fi

if [[ "$#" -eq 0 ]]; then
  exec "${PYTHON_BIN}" -m pytest -q -m "not integration"
fi

exec "${PYTHON_BIN}" -m pytest -q "$@"
