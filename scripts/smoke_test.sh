#!/usr/bin/env bash
set -euo pipefail

base_url="$${BACKEND_URL:-http://127.0.0.1:8000}"
curl --fail --silent --show-error "$base_url/health/live" >/dev/null
curl --fail --silent --show-error "$base_url/health/ready" >/dev/null

echo "Backend liveness and PostgreSQL readiness checks passed."
echo "For a full release gate, exercise profile generation, Telegram approval, publication, and restart recovery in an isolated Compose stack."
