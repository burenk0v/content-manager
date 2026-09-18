#!/bin/bash
set -e

python src/manage.py migrate

if [ -n "${ADMIN_USERNAME:-}" ] && [ -n "${ADMIN_PASSWORD:-}" ] && [ -n "${ADMIN_EMAIL:-}" ]; then
python src/manage.py shell <<EOF
import os
from django.contrib.auth import get_user_model
User = get_user_model()
username = os.environ["ADMIN_USERNAME"]
password = os.environ["ADMIN_PASSWORD"]
email = os.environ["ADMIN_EMAIL"]
user, created = User.objects.get_or_create(username=username, defaults={"email": email, "is_staff": True, "is_superuser": True})
if created:
    user.set_password(password)
    user.save()
elif not user.is_superuser:
    user.is_staff = True
    user.is_superuser = True
    user.set_password(password)
    user.save()
EOF
fi

mkdir -p /certs
if [ ! -f /certs/localhost.crt ] || [ ! -f /certs/localhost.key ]; then
    openssl req -x509 -newkey rsa:2048 -sha256 -days 3650 -nodes         -keyout /certs/localhost.key -out /certs/localhost.crt         -subj '/CN=localhost' >/dev/null 2>&1
fi

exec uvicorn mysite.asgi:application --app-dir src --host 0.0.0.0 --port 8443     --ssl-keyfile /certs/localhost.key --ssl-certfile /certs/localhost.crt
