#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 || ! -f "$1" ]]; then
  echo "Usage: $0 <postgres-custom-format.dump>" >&2
  exit 2
fi

dump="$1"
echo "WARNING: this replaces the current PostgreSQL application data."
read -r -p "Type RESTORE to continue: " confirmation
[[ "$confirmation" == "RESTORE" ]]

docker compose exec -T database sh -c \
  'pg_restore --clean --if-exists --no-owner --no-acl -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < "$dump"

echo "PostgreSQL restore completed. Verify docker compose ps and /health/ready before resuming workers."
