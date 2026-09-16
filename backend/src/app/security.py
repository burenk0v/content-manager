import hmac
import os

from fastapi import Header, HTTPException, status


def require_service_token(x_service_token: str | None = Header(None)) -> None:
    expected = os.environ.get("SERVICE_ACCOUNT_TOKEN")
    if not expected or not x_service_token or not hmac.compare_digest(x_service_token, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid service token",
        )
