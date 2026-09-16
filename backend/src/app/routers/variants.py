from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from src.app.db import get_db
from src.app.routers.foundation import require_service_token
from src.app.services.variant_service import (
    VariantConflict,
    VariantNotFound,
    VariantProviderFailure,
    list_variants as list_variants_service,
    transform_content as transform_content_service,
)

router = APIRouter()


class TransformContent(BaseModel):
    content_version_id: int | None = None
    instructions: str | None = Field(None, min_length=1, max_length=12000)
    model: str | None = Field(None, min_length=1, max_length=100)


class ContentVariantOut(BaseModel):
    id: int
    content_id: int
    content_version_id: int
    channel_id: int
    version: int
    body: str
    provider: str
    model: str | None
    status: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


@router.post(
    "/contents/{content_id}/variants/{channel_id}/transform",
    response_model=ContentVariantOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_service_token)],
)
def transform_content(
    content_id: int,
    channel_id: int,
    payload: TransformContent,
    db: Session = Depends(get_db),
):
    try:
        variant = transform_content_service(
            db,
            content_id,
            channel_id,
            content_version_id=payload.content_version_id,
            instructions=payload.instructions,
            model=payload.model,
        )
    except VariantNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    except VariantConflict as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from exc
    except VariantProviderFailure as exc:
        db.rollback()
        raise HTTPException(502, str(exc)) from exc

    db.commit()
    db.refresh(variant)
    return variant


@router.get(
    "/contents/{content_id}/variants",
    response_model=list[ContentVariantOut],
    dependencies=[Depends(require_service_token)],
)
def list_variants(
    content_id: int,
    channel_id: int | None = None,
    content_version_id: int | None = None,
    db: Session = Depends(get_db),
):
    try:
        return list_variants_service(
            db,
            content_id,
            channel_id=channel_id,
            content_version_id=content_version_id,
        )
    except VariantNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
