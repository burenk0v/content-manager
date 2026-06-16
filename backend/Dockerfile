FROM python:3.11-slim
WORKDIR /src/app
COPY requirements.txt .
RUN pip install --no-cache-dir -r src/requirements.txt
COPY . .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
