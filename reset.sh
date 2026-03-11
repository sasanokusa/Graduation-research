#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cp "${ROOT_DIR}/nginx/nginx.conf.base" "${ROOT_DIR}/nginx/nginx.conf"
cp "${ROOT_DIR}/app/main.py.base" "${ROOT_DIR}/app/main.py"
cp "${ROOT_DIR}/app/requirements.txt.base" "${ROOT_DIR}/app/requirements.txt"
cp "${ROOT_DIR}/app/app.env.base" "${ROOT_DIR}/app/app.env"

docker compose down -v
docker compose up -d

echo "[reset] restored baseline files for scenarios A-O and recreated the stack"
