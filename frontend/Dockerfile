# Build stage
FROM python:3.13-slim as builder

WORKDIR /build

COPY src/requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt


# Runtime stage
FROM python:3.13-slim

WORKDIR /app

# Create non-root user for security
RUN useradd -m -u 1000 appuser

# Copy only runtime dependencies from builder
COPY --from=builder --chown=appuser:appuser /root/.local /home/appuser/.local

# Copy application code
COPY --chown=appuser:appuser src/ ./src/

# Set PATH and Python environment variables
ENV PATH=/home/appuser/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Expose HTTPS port
EXPOSE 443

# Create certs directory with proper permissions
RUN mkdir -p /certs && chown appuser:appuser /certs

# Switch to non-root user
USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:443')" || exit 1

# Run migrations and start server
CMD sh -c "python src/manage.py migrate && \
           python src/manage.py shell < /dev/stdin <<EOF && \
from django.contrib.auth import get_user_model
User = get_user_model()
if not User.objects.filter(username='admin').exists():
    User.objects.create_superuser('admin', 'admin@myproject.com', 'admin')
EOF
           if [ ! -f /certs/localhost.crt ] || [ ! -f /certs/localhost.key ]; then \
               openssl req -x509 -newkey rsa:2048 -sha256 -days 3650 -nodes \
               -keyout /certs/localhost.key -out /certs/localhost.crt \
               -subj '/CN=localhost' >/dev/null 2>&1; \
           fi && \
           python src/manage.py runserver_plus --cert-file /certs/localhost.crt --key-file /certs/localhost.key 0.0.0.0:443"
