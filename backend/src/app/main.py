from fastapi import FastAPI
from fastapi.responses import Response

from src.app import db
from src.app.metrics import metrics_response
from src.app.observability import request_observability
from src.app.routers import ai
from src.app.routers import audit
from src.app.routers import auth
from src.app.routers import foundation
from src.app.routers import lifecycle
from src.app.routers import planning
from src.app.routers import variants


app = FastAPI(title="Content Manager API", version="0.1.0")
app.middleware("http")(request_observability)

app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(foundation.router, prefix="/content", tags=["content-lifecycle"])
app.include_router(lifecycle.router, prefix="/content", tags=["content-state"])
app.include_router(planning.router, prefix="/content", tags=["content-planning"])
app.include_router(ai.router, prefix="/content", tags=["content-generation"])
app.include_router(variants.router, prefix="/content", tags=["content-variants"])
app.include_router(audit.router, prefix="/audit", tags=["audit"])


@app.get("/")
def root():
    return {"status": "Backend running"}


@app.get("/health/live")
def health_live():
    return {"status": "ok"}


@app.get("/health/ready")
def health_ready():
    if db.check_db_connection():
        return {"status": "ok"}
    return Response(
        content='{"detail":"Database unavailable"}',
        media_type="application/json",
        status_code=503,
    )


@app.get("/health")
def health():
    return health_live()


@app.get("/health/db")
def health_db():
    if db.check_db_connection():
        return {"status": "ok"}
    return {"status": "failed"}


@app.get("/metrics")
def metrics() -> Response:
    payload, content_type = metrics_response()
    return Response(content=payload, media_type=content_type.split(";", 1)[0])
