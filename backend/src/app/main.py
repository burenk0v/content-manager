from fastapi import FastAPI

from src.app.routers import auth
from src.app.routers import content
from src.app import db, models


app = FastAPI()


@app.on_event("startup")
def on_startup():
    # Create DB tables if they don't exist
    db.Base.metadata.create_all(bind=db.engine)
    db.ensure_schema()


app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(content.router, prefix="/content", tags=["content"])


@app.get("/")
def root():
    return {"status": "Backend running"}


@app.get("/health/db")
def health_db():
    if db.check_db_connection():
        return {"status": "ok"}
    return {"status": "failed"}
