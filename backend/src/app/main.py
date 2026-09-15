from fastapi import FastAPI

from src.app.routers import auth
from src.app.routers import content
from src.app import db


app = FastAPI(title="Content Manager API", version="0.1.0")


app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(content.router, prefix="/content", tags=["content"])


@app.get("/")
def root():
    return {"status": "Backend running"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/health/db")
def health_db():
    if db.check_db_connection():
        return {"status": "ok"}
    return {"status": "failed"}
