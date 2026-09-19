FROM python:3.13-slim

WORKDIR /app
RUN useradd -m -u 1000 validator
COPY --chown=validator:validator runner.py ./runner.py
RUN mkdir -p /var/lib/python-validator/inbox /var/lib/python-validator/outbox \
    && chown -R validator:validator /var/lib/python-validator
USER validator
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHON_VALIDATOR_DIR=/var/lib/python-validator
CMD ["python", "runner.py"]
