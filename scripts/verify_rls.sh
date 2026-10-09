#!/usr/bin/env bash
# Verify migrations apply and RLS enforces tenant isolation against a plain
# Postgres (no Docker/Supabase stack needed). Uses a local shim to emulate the
# Supabase auth schema/roles. Intended for CI (postgres service) and local dev.
#
# Env: standard libpq vars (PGHOST, PGPORT, PGUSER, PGPASSWORD). Defaults target
# a local cluster as the postgres superuser.
set -euo pipefail

export PGHOST="${PGHOST:-127.0.0.1}"
export PGPORT="${PGPORT:-5432}"
export PGUSER="${PGUSER:-postgres}"
export PGDATABASE="${PGDATABASE:-postgres}"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DB="hm_rls_verify_$$"

echo "Creating test database $DB ..."
psql -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS $DB;" >/dev/null
psql -v ON_ERROR_STOP=1 -c "CREATE DATABASE $DB;" >/dev/null

run() { psql -v ON_ERROR_STOP=1 -d "$DB" -f "$1" >/dev/null; }

echo "Applying Supabase shim ..."
run "$ROOT/supabase/tests/_local_shim.sql"

echo "Applying migrations (excluding storage, which needs the Supabase storage schema) ..."
for f in "$ROOT"/supabase/migrations/*.sql; do
  case "$f" in
    *storage_reports.sql) echo "  skip $(basename "$f")"; continue ;;
  esac
  echo "  apply $(basename "$f")"
  run "$f"
done

echo "Running RLS assertions ..."
psql -v ON_ERROR_STOP=1 -d "$DB" -f "$ROOT/supabase/tests/rls_assertions.sql"

echo "Dropping test database ..."
psql -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS $DB;" >/dev/null

echo "RLS verification succeeded."
