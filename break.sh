#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

restore_targets() {
  cp "${ROOT_DIR}/nginx/nginx.conf.base" "${ROOT_DIR}/nginx/nginx.conf"
  cp "${ROOT_DIR}/app/requirements.txt.base" "${ROOT_DIR}/app/requirements.txt"
  cp "${ROOT_DIR}/app/app.env.base" "${ROOT_DIR}/app/app.env"
}

apply_a() {
  echo "[break] pattern A: rewrite nginx upstream port to an incorrect value"
  perl -0pi -e 's/app:8000/app:8001/' "${ROOT_DIR}/nginx/nginx.conf"
  docker compose restart nginx
}

apply_b() {
  echo "[break] pattern B: remove uvicorn from requirements and recreate app"
  grep -v '^uvicorn\[standard\]==' "${ROOT_DIR}/app/requirements.txt.base" > "${ROOT_DIR}/app/requirements.txt"
  docker compose up -d --force-recreate app
}

apply_c() {
  echo "[break] pattern C: change the app-side DB password env var and recreate app"
  perl -0pi -e 's/^DB_PASSWORD=.*/DB_PASSWORD=wrongpassword/' "${ROOT_DIR}/app/app.env"
  docker compose up -d --force-recreate app
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
    random)
      case $((RANDOM % 3)) in
        0) echo "A" ;;
        1) echo "B" ;;
        2) echo "C" ;;
      esac
      ;;
    *)
      echo "usage: ./break.sh [a|b|c|random]" >&2
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
  esac

  echo "[break] injected failure pattern ${pattern}"
}

main "${1:-random}"
