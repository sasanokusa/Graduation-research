#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

wait_for_http_failure() {
  local path="$1"
  local attempts="${2:-10}"
  local sleep_seconds="${3:-2}"
  local url="http://localhost:8080${path}"
  local attempt

  for attempt in $(seq 1 "${attempts}"); do
    if ! curl -fsS --max-time 3 "${url}" >/dev/null 2>&1; then
      echo "[break] confirmed failure at ${path} on attempt ${attempt}/${attempts}"
      return 0
    fi
    sleep "${sleep_seconds}"
  done

  echo "[break] warning: ${path} still responded successfully after ${attempts} attempts" >&2
  return 1
}

wait_for_http_success() {
  local path="$1"
  local attempts="${2:-10}"
  local sleep_seconds="${3:-2}"
  local url="http://localhost:8080${path}"
  local attempt

  for attempt in $(seq 1 "${attempts}"); do
    if curl -fsS --max-time 3 "${url}" >/dev/null 2>&1; then
      echo "[break] confirmed success at ${path} on attempt ${attempt}/${attempts}"
      return 0
    fi
    sleep "${sleep_seconds}"
  done

  echo "[break] warning: ${path} did not respond successfully after ${attempts} attempts" >&2
  return 1
}

wait_for_split_state() {
  local success_path="$1"
  local failure_path="$2"
  local attempts="${3:-10}"
  local sleep_seconds="${4:-2}"
  local attempt

  for attempt in $(seq 1 "${attempts}"); do
    if curl -fsS --max-time 3 "http://localhost:8080${success_path}" >/dev/null 2>&1 \
      && ! curl -fsS --max-time 3 "http://localhost:8080${failure_path}" >/dev/null 2>&1; then
      echo "[break] confirmed split state: ${success_path} success and ${failure_path} failure on attempt ${attempt}/${attempts}"
      return 0
    fi
    sleep "${sleep_seconds}"
  done

  echo "[break] warning: split state (${success_path} success, ${failure_path} failure) was not confirmed" >&2
  return 1
}

restore_targets() {
  cp "${ROOT_DIR}/nginx/nginx.conf.base" "${ROOT_DIR}/nginx/nginx.conf"
  cp "${ROOT_DIR}/app/main.py.base" "${ROOT_DIR}/app/main.py"
  cp "${ROOT_DIR}/app/requirements.txt.base" "${ROOT_DIR}/app/requirements.txt"
  cp "${ROOT_DIR}/app/app.env.base" "${ROOT_DIR}/app/app.env"
}

apply_a() {
  echo "[break] pattern A: rewrite nginx upstream port to an incorrect value"
  perl -0pi -e 's/server app:8000 resolve;/server app:8001 resolve;/' "${ROOT_DIR}/nginx/nginx.conf"
  docker compose restart nginx
  wait_for_http_failure "/healthz"
}

apply_b() {
  echo "[break] pattern B: remove uvicorn from requirements and recreate app"
  grep -v '^uvicorn\[standard\]==' "${ROOT_DIR}/app/requirements.txt.base" > "${ROOT_DIR}/app/requirements.txt"
  docker compose up -d --force-recreate app
}

apply_c() {
  echo "[break] pattern C: change the app-side DB password env var and recreate app"
  perl -0pi -e 's/^DB_PASSWORD=.*/DB_PASSWORD=wrongpassword/m' "${ROOT_DIR}/app/app.env"
  docker compose up -d --force-recreate app
  echo "[break] waiting for app-side env change to surface via /api/items"
  wait_for_http_failure "/api/items"
}

apply_d() {
  echo "[break] pattern D: change the API query to a non-existent table name"
  perl -0pi -e 's/FROM items ORDER BY id/FROM itemz ORDER BY id/' "${ROOT_DIR}/app/main.py"
  docker compose up -d --force-recreate app
  wait_for_http_failure "/api/items"
}

apply_e() {
  echo "[break] pattern E: drift the app listen port away from nginx upstream expectations"
  perl -0pi -e 's/^APP_PORT=.*/APP_PORT=9000/m' "${ROOT_DIR}/app/app.env"
  docker compose up -d --force-recreate app
  wait_for_http_failure "/healthz"
}

apply_f() {
  echo "[break] pattern F: change the API query to a non-existent column name"
  perl -0pi -e 's/name, description FROM items/name, details FROM items/' "${ROOT_DIR}/app/main.py"
  docker compose up -d --force-recreate app
  wait_for_http_failure "/api/items"
}

apply_g() {
  echo "[break] pattern G: break the /healthz query while leaving the main API path intact"
  perl -0pi -e 's/SELECT 1 AS ok/SELECT missing FROM health_checks/' "${ROOT_DIR}/app/main.py"
  docker compose up -d --force-recreate app
  wait_for_http_failure "/healthz"
}

apply_h() {
  echo "[break] pattern H: change the nginx upstream host name to an invalid service name"
  perl -0pi -e 's/server app:8000 resolve;/server backend:8000 resolve;/' "${ROOT_DIR}/nginx/nginx.conf"
  docker compose restart nginx
  wait_for_http_failure "/healthz"
}

apply_i() {
  echo "[break] pattern I: inject a masked two-stage env failure (port drift + DB password drift)"
  perl -0pi -e 's/^APP_PORT=.*/APP_PORT=9000/m; s/^DB_PASSWORD=.*/DB_PASSWORD=wrongpassword/m' "${ROOT_DIR}/app/app.env"
  docker compose up -d --force-recreate app
  echo "[break] waiting for the first-stage upstream failure to surface"
  wait_for_http_failure "/healthz"
}

apply_k() {
  echo "[break] pattern K: inject an opaque API 500 that requires extra observation"
  cp "${ROOT_DIR}/scenarios/fixtures/app_main_k.py" "${ROOT_DIR}/app/main.py"
  docker compose up -d --force-recreate app
  wait_for_split_state "/healthz" "/api/items"
}

seed_stale_upstream_failure_logs() {
  local attempt
  for attempt in $(seq 1 4); do
    curl -fsS --max-time 3 "http://localhost:8080/healthz" >/dev/null 2>&1 || true
    curl -fsS --max-time 3 "http://localhost:8080/api/items" >/dev/null 2>&1 || true
    sleep 1
  done
}

apply_l() {
  echo "[break] pattern L: seed stale nginx upstream failures, then leave an app/query bug as the current fault"
  perl -0pi -e 's/server app:8000 resolve;/server app:8001 resolve;/' "${ROOT_DIR}/nginx/nginx.conf"
  docker compose restart nginx
  seed_stale_upstream_failure_logs
  cp "${ROOT_DIR}/nginx/nginx.conf.base" "${ROOT_DIR}/nginx/nginx.conf"
  docker compose restart nginx
  perl -0pi -e 's/FROM items ORDER BY id/FROM itemz ORDER BY id/' "${ROOT_DIR}/app/main.py"
  docker compose up -d --force-recreate app
  wait_for_split_state "/healthz" "/api/items"
}

pick_pattern() {
  case "${1:-random}" in
    a|A|pattern-a)
      echo "A"
      ;;
    b|B|pattern-b)
      echo "B"
      ;;
    c|C|pattern-c)
      echo "C"
      ;;
    d|D|pattern-d)
      echo "D"
      ;;
    e|E|pattern-e)
      echo "E"
      ;;
    f|F|pattern-f)
      echo "F"
      ;;
    g|G|pattern-g)
      echo "G"
      ;;
    h|H|pattern-h)
      echo "H"
      ;;
    i|I|pattern-i)
      echo "I"
      ;;
    k|K|pattern-k)
      echo "K"
      ;;
    l|L|pattern-l)
      echo "L"
      ;;
    random)
      case $((RANDOM % 11)) in
        0) echo "A" ;;
        1) echo "B" ;;
        2) echo "C" ;;
        3) echo "D" ;;
        4) echo "E" ;;
        5) echo "F" ;;
        6) echo "G" ;;
        7) echo "H" ;;
        8) echo "I" ;;
        9) echo "K" ;;
        10) echo "L" ;;
      esac
      ;;
    *)
      echo "usage: ./break.sh [a|b|c|d|e|f|g|h|i|k|l|random]" >&2
      exit 1
      ;;
  esac
}

main() {
  local pattern
  pattern="$(pick_pattern "${1:-random}")"

  restore_targets

  case "${pattern}" in
    A) apply_a ;;
    B) apply_b ;;
    C) apply_c ;;
    D) apply_d ;;
    E) apply_e ;;
    F) apply_f ;;
    G) apply_g ;;
    H) apply_h ;;
    I) apply_i ;;
    K) apply_k ;;
    L) apply_l ;;
  esac

  echo "[break] injected failure pattern ${pattern}"
}

main "${1:-random}"
