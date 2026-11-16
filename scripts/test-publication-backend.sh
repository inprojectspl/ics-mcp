#!/usr/bin/env bash
# Explicit contract smoke against an existing ICS checkout; never a deployed API.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
backend_root="${1:?Usage: bash scripts/test-publication-backend.sh /path/to/ics}"
test_file="${2:-$root/tests/publication_backend_smoke.py}"
test -x "$backend_root/backend/.venv/bin/python"
pg_id=""
redis_id=""
cleanup() {
  if [ -n "$redis_id" ]; then docker rm -fv "$redis_id" >/dev/null || true; fi
  if [ -n "$pg_id" ]; then docker rm -fv "$pg_id" >/dev/null || true; fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
pg_id="$(docker run -d -p 127.0.0.1::5432 -e POSTGRES_USER=ics -e POSTGRES_PASSWORD=ics -e POSTGRES_DB=ics postgres:18.3-alpine)"
redis_id="$(docker run -d -p 127.0.0.1::6379 redis:7-alpine)"
pg_binding="$(docker port "$pg_id" 5432/tcp)"
redis_binding="$(docker port "$redis_id" 6379/tcp)"
ready=false
for ((attempt = 0; attempt < 30; attempt++)); do
  if docker exec "$pg_id" pg_isready -U ics >/dev/null 2>&1 && docker exec "$redis_id" redis-cli ping >/dev/null 2>&1; then
    ready=true
    break
  fi
  sleep 1
done
if [ "$ready" != true ]; then echo "Isolated services did not become ready" >&2; exit 1; fi
export ICS_TEST_BACKEND_ROOT="$backend_root"
export ICS_TEST_DATABASE_URL="postgresql+asyncpg://ics:ics@127.0.0.1:${pg_binding##*:}/ics"
export ICS_TEST_REDIS_URL="redis://127.0.0.1:${redis_binding##*:}/0"
git -C "$backend_root" rev-parse HEAD
bash "$root/scripts/test.sh" "$test_file" -q
