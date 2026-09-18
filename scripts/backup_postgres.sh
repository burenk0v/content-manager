#!/usr/bin/env bash
set -euo pipefail

mkdir -p backups
timestamp="$(date -u +%Y%m%d-%H%M%S)"
output="backups/content-manager-${timestamp}.dump"

docker compose exec -T database pg_dump \
  --format=custom \
  --no-owner \
  --no-acl \
  --username="${DB_USER:-content_manager}" \
  "${DB_NAME:-content_manager}" > "$output"

test -s "$output"
echo "PostgreSQL backup written to $output"
