#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RESET_HEALTHCHECK_ATTEMPTS="${RESET_HEALTHCHECK_ATTEMPTS:-90}"
RESET_HEALTHCHECK_INTERVAL_SECONDS="${RESET_HEALTHCHECK_INTERVAL_SECONDS:-2}"
COMPOSE_WAIT_TIMEOUT_SECONDS="${COMPOSE_WAIT_TIMEOUT_SECONDS:-300}"
LEGACY_CONTAINER_NAMES=(target-nginx target-app target-db)

wait_for_stack_ready() {
  local url="http://localhost:8080/healthz"
  local attempt

  for attempt in $(seq 1 "${RESET_HEALTHCHECK_ATTEMPTS}"); do
    if curl -fsS --max-time 3 "${url}" >/dev/null 2>&1; then
      echo "[reset] confirmed healthy stack at ${url} on attempt ${attempt}/${RESET_HEALTHCHECK_ATTEMPTS}"
      return 0
    fi
    sleep "${RESET_HEALTHCHECK_INTERVAL_SECONDS}"
  done

  echo "[reset] ${url} did not become healthy after ${RESET_HEALTHCHECK_ATTEMPTS} attempts" >&2
  docker compose ps || true
  return 1
}

cleanup_legacy_named_containers() {
  local legacy_name

  for legacy_name in "${LEGACY_CONTAINER_NAMES[@]}"; do
    if docker container inspect "${legacy_name}" >/dev/null 2>&1; then
      echo "[reset] removing legacy container ${legacy_name}"
      docker rm -f "${legacy_name}" >/dev/null
    fi
  done
}

compose_up() {
  if docker compose up --help 2>/dev/null | grep -q -- "--wait"; then
    docker compose up -d --wait --wait-timeout "${COMPOSE_WAIT_TIMEOUT_SECONDS}"
  else
    docker compose up -d
  fi
}

cp "${ROOT_DIR}/nginx/nginx.conf.base" "${ROOT_DIR}/nginx/nginx.conf"
cp "${ROOT_DIR}/app/main.py.base" "${ROOT_DIR}/app/main.py"
cp "${ROOT_DIR}/app/requirements.txt.base" "${ROOT_DIR}/app/requirements.txt"
cp "${ROOT_DIR}/app/app.env.base" "${ROOT_DIR}/app/app.env"

docker compose down --remove-orphans -v || true
cleanup_legacy_named_containers
compose_up
wait_for_stack_ready

echo "[reset] restored baseline files for scenarios A-X and recreated the stack"
