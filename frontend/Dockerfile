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

# Copy and make entrypoint executable
COPY --chown=appuser:appuser entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Create certs directory with proper permissions
RUN mkdir -p /certs && chown appuser:appuser /certs

# Set PATH and Python environment variables
ENV PATH=/home/appuser/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Expose non-privileged HTTPS port
EXPOSE 8443

# Switch to non-root user
USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('https://localhost:443')" || exit 1

# Run entrypoint script
ENTRYPOINT ["/app/entrypoint.sh"]
