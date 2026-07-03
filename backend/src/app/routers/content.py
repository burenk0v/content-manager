import os
from fastapi import APIRouter, Header, HTTPException

router = APIRouter()


def _check_service_token(token: str | None):
    expected = os.environ.get("SERVICE_ACCOUNT_TOKEN")
    if not expected:
        # If not configured, allow (useful for local/dev)
        return True
    return token == expected


@router.get("/")
def get_content(x_service_token: str | None = Header(None)):
    if not _check_service_token(x_service_token):
        raise HTTPException(status_code=401, detail="Invalid service token")

    return [
        {"id": 1, "title": "AI Post 1", "body": "Generated content example"},
        {"id": 2, "title": "AI Post 2", "body": "Another content example"}
    ]
