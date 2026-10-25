#!/usr/bin/env bash
set -Eeuo pipefail
SOURCE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
APP_DIR="$(printenv CONTENT_MANAGER_DIR || true)"
VENV_ROOT="$(printenv CONTENT_MANAGER_VENV_DIR || true)"
[[ -n "$APP_DIR" ]] || APP_DIR=/opt/content-manager
[[ -n "$VENV_ROOT" ]] || VENV_ROOT=/opt/content-manager-venvs
CONFIG_DIR=/etc/content-manager
ENV_FILE="$CONFIG_DIR/content-manager.env"
BACKUP_DIR=/var/backups/content-manager
APP_USER=contentmgr
UPDATE_MODE=false

if [[ $# -gt 0 && "$1" == --update ]]; then UPDATE_MODE=true
elif [[ $# -gt 0 ]]; then echo "Usage: sudo bash scripts/install_native.sh [--update]" >&2; exit 2; fi
if [[ $EUID -ne 0 ]]; then exec sudo -E bash "$SOURCE_DIR/scripts/install_native.sh" "$@"; fi
if [[ "$SOURCE_DIR" != "$APP_DIR" ]]; then
  echo "Clone the repository to $APP_DIR, then run the installer from that checkout." >&2
  echo "Current checkout: $SOURCE_DIR" >&2; exit 1
fi
[[ -f "$SOURCE_DIR/backend/src/app/main.py" && -f "$SOURCE_DIR/frontend/src/manage.py" && -f "$SOURCE_DIR/telegram/src/app.py" ]] || { echo "Incomplete repository checkout." >&2; exit 1; }
. /etc/os-release
[[ "$ID" == raspbian || "$ID" == debian ]] || { echo "Use 64-bit Raspberry Pi OS or Debian." >&2; exit 1; }
[[ "$(dpkg --print-architecture)" == arm64 && "$(uname -m)" == aarch64 ]] || { echo "Requires 64-bit ARM OS (arm64/aarch64); 32-bit OS is unsupported." >&2; exit 1; }
python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)' || { echo "Python 3.10+ is required." >&2; exit 1; }
[[ -d "$APP_DIR/.git" ]] || { echo "No Git checkout at $APP_DIR." >&2; exit 1; }

mkdir -p "$CONFIG_DIR" "$BACKUP_DIR" "$VENV_ROOT"
chmod 750 "$CONFIG_DIR"; chmod 700 "$BACKUP_DIR"
prompt() {
  local label="$1" default="" value=""
  if [[ $# -gt 1 ]]; then default="$2"; fi
  if [[ -n "$default" ]]; then read -r -p "$label [$default]: " value; [[ -n "$value" ]] || value="$default"
  else read -r -p "$label: " value; fi
  printf '%s' "$value"
}
secret() { local value=""; read -r -s -p "$1: " value; printf '\n' >&2; printf '%s' "$value"; }
random_secret() { openssl rand -hex 32; }

if [[ ! -f "$ENV_FILE" ]]; then
  [[ -t 0 ]] || { echo "First install needs an interactive terminal to create $ENV_FILE." >&2; exit 1; }
  echo "Initial setup: secrets are saved in $ENV_FILE (permissions 0600)."
  DB_USER=content_manager; DB_NAME=content_manager; DB_PASSWORD="$(random_secret)"
  BACKEND_SECRET_KEY="$(random_secret)"; SERVICE_ACCOUNT_TOKEN="$(random_secret)"
  PUBLICATION_WORKER_TOKEN="$(random_secret)"; FRONTEND_SECRET_KEY="$(random_secret)"
  TELEGRAM_CALLBACK_SECRET="$(random_secret)"
  OPENAI_API_KEY="$(secret 'OpenAI-compatible API key')"
  BOT_TOKEN="$(secret 'Telegram bot token')"
  ADMINS="$(prompt 'Telegram administrator IDs (comma-separated)')"
  ADMIN_USERNAME="$(prompt 'Web UI administrator username' admin)"
  ADMIN_PASSWORD="$(secret 'Web UI administrator password')"
  ADMIN_EMAIL="$(prompt 'Web UI administrator email' admin@localhost)"
  DEFAULT_HOST="$(hostname -I 2>/dev/null | awk '{print $1}')"; [[ -n "$DEFAULT_HOST" ]] || DEFAULT_HOST="$(hostname)"
  FRONTEND_HOST="$(prompt 'Hostname/IP used to open Web UI' "$DEFAULT_HOST")"
  WEBAPP_URL="$(prompt 'Public HTTPS URL for Telegram WebApp (optional)')"
  FRONTEND_PUBLIC_URL="$(prompt 'Public HTTPS origin for Django CSRF (optional)' "$WEBAPP_URL")"
  LINKEDIN_ACCESS_TOKEN="$(secret 'LinkedIn token (optional; press Enter to skip)')"
  [[ -n "$OPENAI_API_KEY" && -n "$BOT_TOKEN" ]] || { echo "OpenAI key and Telegram token are required." >&2; exit 1; }
  [[ "$ADMINS" =~ ^[0-9]+(,[0-9]+)*$ ]] || { echo "ADMINS must be numeric Telegram IDs separated by commas." >&2; exit 1; }
  [[ -n "$ADMIN_USERNAME" && -n "$ADMIN_PASSWORD" && -n "$ADMIN_EMAIL" ]] || { echo "Admin credentials cannot be empty." >&2; exit 1; }
  [[ -z "$WEBAPP_URL" || "$WEBAPP_URL" == https://* ]] || { echo "WEBAPP_URL must use HTTPS or be empty." >&2; exit 1; }
  [[ -z "$FRONTEND_PUBLIC_URL" || "$FRONTEND_PUBLIC_URL" == https://* ]] || { echo "FRONTEND_PUBLIC_URL must use HTTPS or be empty." >&2; exit 1; }

  export CM_DB_USER="$DB_USER" CM_DB_NAME="$DB_NAME" CM_DB_PASSWORD="$DB_PASSWORD"
  export CM_BACKEND_SECRET_KEY="$BACKEND_SECRET_KEY" CM_SERVICE_ACCOUNT_TOKEN="$SERVICE_ACCOUNT_TOKEN"
  export CM_PUBLICATION_WORKER_TOKEN="$PUBLICATION_WORKER_TOKEN" CM_FRONTEND_SECRET_KEY="$FRONTEND_SECRET_KEY"
  export CM_TELEGRAM_CALLBACK_SECRET="$TELEGRAM_CALLBACK_SECRET" CM_OPENAI_API_KEY="$OPENAI_API_KEY"
  export CM_BOT_TOKEN="$BOT_TOKEN" CM_ADMINS="$ADMINS" CM_ADMIN_USERNAME="$ADMIN_USERNAME"
  export CM_ADMIN_PASSWORD="$ADMIN_PASSWORD" CM_ADMIN_EMAIL="$ADMIN_EMAIL"
  export CM_FRONTEND_HOST="$FRONTEND_HOST" CM_WEBAPP_URL="$WEBAPP_URL"
  export CM_FRONTEND_PUBLIC_URL="$FRONTEND_PUBLIC_URL" CM_LINKEDIN_ACCESS_TOKEN="$LINKEDIN_ACCESS_TOKEN"
  python3 - "$SOURCE_DIR/.env.example" "$ENV_FILE" <<'PY'
import os, sys
from pathlib import Path
src, dst = map(Path, sys.argv[1:])
mapping = {"DB_USER":"CM_DB_USER","DB_PASSWORD":"CM_DB_PASSWORD","DB_NAME":"CM_DB_NAME",
"BACKEND_SECRET_KEY":"CM_BACKEND_SECRET_KEY","SERVICE_ACCOUNT_TOKEN":"CM_SERVICE_ACCOUNT_TOKEN",
"PUBLICATION_WORKER_TOKEN":"CM_PUBLICATION_WORKER_TOKEN","OPENAI_API_KEY":"CM_OPENAI_API_KEY",
"BOT_TOKEN":"CM_BOT_TOKEN","ADMINS":"CM_ADMINS","TELEGRAM_CALLBACK_SECRET":"CM_TELEGRAM_CALLBACK_SECRET",
"WEBAPP_URL":"CM_WEBAPP_URL","FRONTEND_PUBLIC_URL":"CM_FRONTEND_PUBLIC_URL","FRONTEND_HOST":"CM_FRONTEND_HOST",
"FRONTEND_SECRET_KEY":"CM_FRONTEND_SECRET_KEY","ADMIN_USERNAME":"CM_ADMIN_USERNAME",
"ADMIN_PASSWORD":"CM_ADMIN_PASSWORD","ADMIN_EMAIL":"CM_ADMIN_EMAIL","LINKEDIN_ACCESS_TOKEN":"CM_LINKEDIN_ACCESS_TOKEN"}
values = {k:os.environ[v] for k,v in mapping.items()}
values.update({"APP_ENV":"production","OPENAI_MODEL":"gpt-4o-mini","AI_GENERATION_PROVIDER":"openai",
"AI_TRANSFORMATION_PROVIDER":"openai","REGISTRATION_ENABLED":"false","LINKEDIN_VERSION":"202609"})
lines=[]; seen=set()
for line in src.read_text().splitlines():
    if not line or line.lstrip().startswith("#") or "=" not in line: lines.append(line); continue
    key=line.split("=",1)[0]
    if key in values: lines.append(key+"="+values[key]); seen.add(key)
    else: lines.append(line)
for key,val in values.items():
    if key not in seen: lines.append(key+"="+val)
lines += ["DB_HOST=127.0.0.1","DB_PORT=5432",
"DATABASE_URL=postgresql://"+values["DB_USER"]+":"+values["DB_PASSWORD"]+"@127.0.0.1:5432/"+values["DB_NAME"],
"BACKEND_API_URL=http://127.0.0.1:8000","MAX_CONCURRENT_GENERATIONS=1"]
dst.write_text("\n".join(lines)+"\n"); dst.chmod(0o600)
PY
  unset CM_DB_USER CM_DB_NAME CM_DB_PASSWORD CM_BACKEND_SECRET_KEY CM_SERVICE_ACCOUNT_TOKEN
  unset CM_PUBLICATION_WORKER_TOKEN CM_FRONTEND_SECRET_KEY CM_TELEGRAM_CALLBACK_SECRET CM_OPENAI_API_KEY
  unset CM_BOT_TOKEN CM_ADMINS CM_ADMIN_USERNAME CM_ADMIN_PASSWORD CM_ADMIN_EMAIL CM_FRONTEND_HOST
  unset CM_WEBAPP_URL CM_FRONTEND_PUBLIC_URL CM_LINKEDIN_ACCESS_TOKEN
fi
chmod 600 "$ENV_FILE"
get_env() { sed -n "s/^$1=//p" "$ENV_FILE" | tail -n 1; }
DB_USER="$(get_env DB_USER)"; DB_NAME="$(get_env DB_NAME)"
DB_PASSWORD="$(get_env DB_PASSWORD)"; DATABASE_URL="$(get_env DATABASE_URL)"
[[ "$DB_USER" =~ ^[a-zA-Z_][a-zA-Z0-9_]*$ && "$DB_NAME" =~ ^[a-zA-Z_][a-zA-Z0-9_]*$ ]] || { echo "Invalid DB_USER/DB_NAME." >&2; exit 1; }
[[ -n "$DB_PASSWORD" && -n "$DATABASE_URL" ]] || { echo "DB_PASSWORD/DATABASE_URL missing." >&2; exit 1; }

echo "Installing OS packages..."
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y build-essential ca-certificates curl git libpq-dev openssl postgresql python3 python3-dev python3-full python3-venv
if ! id "$APP_USER" >/dev/null 2>&1; then useradd --system --home-dir /var/lib/content-manager --create-home --shell /usr/sbin/nologin "$APP_USER"; fi
install -d -o "$APP_USER" -g "$APP_USER" -m 750 /var/lib/content-manager "$VENV_ROOT"
chmod -R a+rX "$APP_DIR"; chown root:root "$APP_DIR"
systemctl enable --now postgresql
for _ in $(seq 1 30); do pg_isready -q && break; sleep 1; done
pg_isready -q || { echo "PostgreSQL did not become ready." >&2; exit 1; }
if runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='$DB_USER'" | grep -q 1; then
  runuser -u postgres -- psql -v ON_ERROR_STOP=1 -c "ALTER ROLE \"$DB_USER\" WITH LOGIN PASSWORD '$DB_PASSWORD'"
else
  runuser -u postgres -- psql -v ON_ERROR_STOP=1 -c "CREATE ROLE \"$DB_USER\" LOGIN PASSWORD '$DB_PASSWORD'"
fi
if ! runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" | grep -q 1; then runuser -u postgres -- createdb --owner="$DB_USER" "$DB_NAME"; fi
if [[ "$UPDATE_MODE" == true ]]; then
  BACKUP_FILE="$BACKUP_DIR/content-manager-$(date +%Y%m%d-%H%M%S).dump"
  echo "Backing up database before update: $BACKUP_FILE"
  runuser -u postgres -- pg_dump -Fc --dbname="$DB_NAME" --file="$BACKUP_FILE"
  chmod 600 "$BACKUP_FILE"
fi

install_venv() {
  local name="$1" requirements="$2" venv="$VENV_ROOT/$1"
  [[ -x "$venv/bin/python" ]] || runuser -u "$APP_USER" -- python3 -m venv "$venv"
  echo "Installing Python dependencies: $name"
  runuser -u "$APP_USER" -- "$venv/bin/python" -m pip install --disable-pip-version-check --no-cache-dir -r "$requirements"
}
install_venv backend "$APP_DIR/backend/src/requirements.txt"
install_venv frontend "$APP_DIR/frontend/src/requirements.txt"
install_venv telegram "$APP_DIR/telegram/src/requirements.txt"

echo "Applying backend database migrations..."
runuser -u "$APP_USER" -- env DATABASE_URL="$DATABASE_URL" "$VENV_ROOT/backend/bin/alembic" -c "$APP_DIR/backend/alembic.ini" upgrade head

cat >/etc/systemd/system/content-manager-backend.service <<EOF
[Unit]
Description=Content Manager API
After=network-online.target postgresql.service
Wants=network-online.target
Requires=postgresql.service
[Service]
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$APP_DIR/backend
EnvironmentFile=$ENV_FILE
Environment=PYTHONUNBUFFERED=1
ExecStart=$VENV_ROOT/backend/bin/uvicorn src.app.main:app --host 127.0.0.1 --port 8000
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
[Install]
WantedBy=multi-user.target
EOF
cat >/etc/systemd/system/content-manager-scheduler.service <<EOF
[Unit]
Description=Content Manager autonomous scheduler
After=content-manager-backend.service
Requires=content-manager-backend.service
[Service]
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$APP_DIR/backend
EnvironmentFile=$ENV_FILE
Environment=PYTHONUNBUFFERED=1
ExecStart=$VENV_ROOT/backend/bin/python -m src.app.services.autonomous_scheduler
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
[Install]
WantedBy=multi-user.target
EOF
cat >/etc/systemd/system/content-manager-frontend.service <<EOF
[Unit]
Description=Content Manager Web UI
After=content-manager-backend.service postgresql.service
Requires=content-manager-backend.service postgresql.service
[Service]
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$APP_DIR/frontend
EnvironmentFile=$ENV_FILE
Environment=PYTHONUNBUFFERED=1
ExecStartPre=/bin/bash $APP_DIR/scripts/native/frontend-prestart.sh
ExecStart=$VENV_ROOT/frontend/bin/uvicorn mysite.asgi:application --app-dir src --host 0.0.0.0 --port 3000
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
[Install]
WantedBy=multi-user.target
EOF
cat >/etc/systemd/system/content-manager-telegram.service <<EOF
[Unit]
Description=Content Manager Telegram worker
After=content-manager-backend.service
Requires=content-manager-backend.service
[Service]
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$APP_DIR/telegram
EnvironmentFile=$ENV_FILE
Environment=PYTHONUNBUFFERED=1
ExecStart=$VENV_ROOT/telegram/bin/python src/app.py
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
[Install]
WantedBy=multi-user.target
EOF
chmod 755 "$SOURCE_DIR/scripts/native/frontend-prestart.sh"
systemctl daemon-reload
systemctl enable content-manager-backend content-manager-scheduler content-manager-frontend content-manager-telegram
systemctl restart content-manager-backend
for _ in $(seq 1 30); do curl -fsS http://127.0.0.1:8000/health/ready >/dev/null && break; sleep 2; done
curl -fsS http://127.0.0.1:8000/health/ready >/dev/null || { echo "Backend readiness check failed; inspect journalctl." >&2; exit 1; }
systemctl restart content-manager-scheduler content-manager-frontend content-manager-telegram
echo
echo "Native installation finished."
echo "Web UI: http://$(get_env FRONTEND_HOST):3000/"
echo "Backend API is local-only at http://127.0.0.1:8000/"
echo "Config: $ENV_FILE"
echo "Logs: journalctl -u content-manager-backend -f"
