#!/usr/bin/env bash
set -euo pipefail

mkdir -p backups
timestamp="$(date -u +%Y%m%d-%H%M%S)"
output="backups/content-manager-${timestamp}.dump"

docker compose exec -T database sh -c \
  'pg_dump --format=custom --no-owner --no-acl -U "$POSTGRES_USER" "$POSTGRES_DB"' > "$output"

test -s "$output"
echo "PostgreSQL backup written to $output"
