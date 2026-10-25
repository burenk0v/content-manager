# Native installation on Raspberry Pi OS

Experimental native deployment for Raspberry Pi 3B+ without Docker. Use 64-bit Raspberry Pi OS Lite (aarch64 / arm64). 32-bit OS images are rejected.

## What it installs

- PostgreSQL from OS packages.
- Backend, frontend, and Telegram worker in separate Python virtual environments.
- The autonomous scheduler as a separate service.
- Four systemd services: backend, scheduler, frontend, and Telegram.
- Configuration in /etc/content-manager/, app state in /var/lib/content-manager/, and pre-update database dumps in /var/backups/content-manager/.

The backend API listens on 127.0.0.1:8000. The Web UI listens on 0.0.0.0:3000 for LAN access. Do not port-forward these ports from the Internet. Put a TLS reverse proxy in front of the Web UI for public access; Telegram WebApps require HTTPS.

## First installation

Run on the Raspberry Pi. The repository checkout must be at /opt/content-manager.

~~~bash
sudo apt-get update
sudo apt-get install -y git
sudo git clone https://github.com/burenk0v/content-manager.git /opt/content-manager
sudo chown -R "$USER":"$USER" /opt/content-manager
cd /opt/content-manager
sudo bash scripts/install_native.sh
~~~

The installer asks for an OpenAI-compatible API key, Telegram bot token, administrator Telegram ID(s), initial Web UI administrator credentials, and the hostname/IP used to access the UI. Secrets are generated automatically and stored in /etc/content-manager/content-manager.env with mode 0600. Public registration remains disabled.

Leave the public HTTPS URL prompts empty if HTTPS is not configured yet. The Web UI can still be reached on the LAN, but the Telegram /web command will not open a WebApp until WEBAPP_URL is set to a valid public HTTPS URL. FRONTEND_PUBLIC_URL should normally be the same public HTTPS origin.

## Verify

~~~bash
systemctl --no-pager --full status content-manager-backend content-manager-scheduler content-manager-frontend content-manager-telegram
curl http://127.0.0.1:8000/health/ready
curl -I http://127.0.0.1:3000/
~~~

From another device on the LAN, open http://<raspberry-pi-ip>:3000/. If Django rejects the host, update FRONTEND_HOST in /etc/content-manager/content-manager.env and rerun the installer to regenerate service configuration.

## Logs and controls

~~~bash
journalctl -u content-manager-backend -f
journalctl -u content-manager-scheduler -f
journalctl -u content-manager-frontend -f
journalctl -u content-manager-telegram -f

sudo systemctl restart content-manager-backend
sudo systemctl restart content-manager-scheduler
sudo systemctl restart content-manager-frontend
sudo systemctl restart content-manager-telegram
~~~

## Update

~~~bash
cd /opt/content-manager
sudo git pull --ff-only
sudo bash scripts/install_native.sh --update
~~~

Update mode creates a PostgreSQL custom-format dump in /var/backups/content-manager/ before applying migrations, updates Python dependencies, and restarts services. It does not replace the main configuration file or reset an existing superuser password. Copy backups to another machine or NAS for disaster recovery.

## Restore a database backup

This replaces the current database contents. Verify the selected file before running the commands.

~~~bash
sudo systemctl stop content-manager-telegram content-manager-scheduler content-manager-frontend content-manager-backend
sudo -u postgres dropdb content_manager
sudo -u postgres createdb --owner=content_manager content_manager
sudo -u postgres pg_restore --dbname=content_manager /var/backups/content-manager/<backup-file>.dump
sudo systemctl start content-manager-backend content-manager-scheduler content-manager-frontend content-manager-telegram
~~~

If DB_NAME or DB_USER were changed, substitute the configured values.

## Raspberry Pi 3B+ notes

- MAX_CONCURRENT_GENERATIONS is set to 1 to reduce memory pressure.
- Package installation can take a while. Use a stable power supply and reliable storage; a USB SSD is preferable to a low-end SD card.
- AI generation uses the configured remote OpenAI-compatible API; the Pi does not run a local language model.
- The Web UI is exposed to the LAN on port 3000. Keep it on a trusted network until HTTPS and suitable network controls are configured.
- Validate this installer on the exact Raspberry Pi OS release and connected integrations before treating it as production-ready.
