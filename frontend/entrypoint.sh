#!/bin/bash
set -e

# Run migrations
python src/manage.py migrate

# Create admin user if it doesn't exist
python src/manage.py shell <<EOF
from django.contrib.auth import get_user_model
User = get_user_model()
if not User.objects.filter(username='admin').exists():
    User.objects.create_superuser('admin', 'admin@myproject.com', 'admin')
EOF

# Generate self-signed certificate if needed
mkdir -p /certs
if [ ! -f /certs/localhost.crt ] || [ ! -f /certs/localhost.key ]; then
    openssl req -x509 -newkey rsa:2048 -sha256 -days 3650 -nodes \
        -keyout /certs/localhost.key -out /certs/localhost.crt \
        -subj '/CN=localhost' >/dev/null 2>&1
fi

# Start Django development server with HTTPS on non-privileged port
python src/manage.py runserver_plus --cert-file /certs/localhost.crt --key-file /certs/localhost.key 0.0.0.0:8443
