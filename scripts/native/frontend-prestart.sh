#!/usr/bin/env bash
set -Eeuo pipefail
cd /opt/content-manager/frontend
/opt/content-manager-venvs/frontend/bin//opt/content-manager-venvs/frontend/bin/python src/manage.py migrate --noinput
/opt/content-manager-venvs/frontend/bin/python src/manage.py shell <<'PY'
import os
from django.contrib.auth import get_user_model
User = get_user_model()
username = os.environ["ADMIN_USERNAME"]
password = os.environ["ADMIN_PASSWORD"]
email = os.environ["ADMIN_EMAIL"]
user, created = User.objects.get_or_create(
    username=username,
    defaults={"email": email, "is_staff": True, "is_superuser": True},
)
if created:
    user.set_password(password)
    user.save()
elif not user.is_superuser:
    user.is_staff = True
    user.is_superuser = True
    user.set_password(password)
    user.save()
PY
