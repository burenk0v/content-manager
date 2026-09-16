from fastapi import FastAPI

from src.app import db
from src.app.observability import request_observability
from src.app.routers import ai
from src.app.routers import audit
from src.app.routers import auth
from src.app.routers import foundation
from src.app.routers import lifecycle
from src.app.routers import planning


app = FastAPI(title="Content Manager API", version="0.1.0")
app.middleware("http")(request_observability)

app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(foundation.router, prefix="/content", tags=["content-lifecycle"])
app.include_router(lifecycle.router, prefix="/content", tags=["content-state"])
app.include_router(planning.router, prefix="/content", tags=["content-planning"])
app.include_router(ai.router, prefix="/content", tags=["content-generation"])
app.include_router(audit.router, prefix="/audit", tags=["audit"])


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
