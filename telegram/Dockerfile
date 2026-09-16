# Build stage
FROM python:3.13-slim as builder

WORKDIR /build

COPY src/requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

FROM python:3.13-slim

WORKDIR /app
RUN useradd -m -u 1000 appuser
COPY --from=builder --chown=appuser:appuser /root/.local /home/appuser/.local
COPY --chown=appuser:appuser src/ ./src/

ENV PATH=/home/appuser/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER appuser

CMD ["python", "src/app.py"]
