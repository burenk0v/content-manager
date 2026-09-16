import os
import tempfile
import uuid

os.environ["SERVICE_ACCOUNT_TOKEN"] = "test-token"

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from src.app.db import Base, get_db
from src.app.main import app

_fd, _db_path = tempfile.mkstemp(prefix="content_manager_security_test_", suffix=".sqlite3")
os.close(_fd)
engine = create_engine(
    f"sqlite:///{_db_path}",
    connect_args={"check_same_thread": False, "timeout": 30},
    poolclass=NullPool,
)
TestingSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base.metadata.create_all(bind=engine)


def override_db():
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_db
client = TestClient(app)


def test_content_api_rejects_missing_service_token():
    response = client.get("/content/workspaces")
    assert response.status_code == 401


def test_content_api_rejects_invalid_service_token():
    response = client.get("/content/workspaces", headers={"X-Service-Token": "wrong"})
    assert response.status_code == 401


def test_content_api_accepts_configured_service_token():
    suffix = uuid.uuid4().hex[:8]
    response = client.post(
        "/content/workspaces",
        json={"name": f"Secure {suffix}", "slug": f"secure-{suffix}"},
        headers={"X-Service-Token": "test-token"},
    )
    assert response.status_code == 201
