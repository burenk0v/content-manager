FROM python:3.13-slim as builder
WORKDIR /build
COPY src/requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

FROM python:3.13-slim
WORKDIR /app
RUN useradd -m -u 1000 appuser
COPY --from=builder --chown=appuser:appuser /root/.local /home/appuser/.local
COPY --chown=appuser:appuser src/ ./src/
COPY --chown=appuser:appuser entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh && mkdir -p /certs && chown appuser:appuser /certs
ENV PATH=/home/appuser/.local/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
EXPOSE 8443
USER appuser
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3     CMD python -c "import socket; socket.create_connection(('localhost', 8443), 5)" || exit 1
ENTRYPOINT ["/app/entrypoint.sh"]
