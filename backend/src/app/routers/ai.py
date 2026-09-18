from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from src.app.db import get_db
from src.app.routers.foundation import require_service_token
from src.app.services.generation_service import (
    GenerationConflict,
    GenerationNotFound,
    GenerationProviderFailure,
    generate_content as generate_content_service,
    generate_profile_content as generate_profile_content_service,
    list_generations as list_generations_service,
    recover_stale_generations as recover_stale_generations_service,
)

router = APIRouter()


class GenerateContent(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=12000)
    system_message: Optional[str] = Field(None, min_length=1, max_length=12000)
    model: Optional[str] = Field(None, min_length=1, max_length=100)


class GenerationRunOut(BaseModel):
    id: int
    content_id: int
    content_version_id: Optional[int]
    provider: str
    model: Optional[str]
    status: str
    prompt: str
    error_message: Optional[str]
    created_at: datetime
    completed_at: Optional[datetime]
    model_config = ConfigDict(from_attributes=True)


@router.post(
    "/contents/{content_id}/generate",
    response_model=GenerationRunOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_service_token)],
)
def generate_content(content_id: int, payload: GenerateContent, db: Session = Depends(get_db)):
    try:
        run = generate_content_service(
            db,
            content_id,
            prompt=payload.prompt,
            system_message=payload.system_message,
            model=payload.model,
        )
    except GenerationNotFound as exc:
        raise HTTPException(404, "Content not found") from exc
    except GenerationConflict as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from exc
    except GenerationProviderFailure as exc:
        db.commit()
        raise HTTPException(502, str(exc)) from exc

    db.commit()
    db.refresh(run)
    return run


@router.get(
    "/contents/{content_id}/generations",
    response_model=list[GenerationRunOut],
    dependencies=[Depends(require_service_token)],
)
def list_generations(content_id: int, db: Session = Depends(get_db)):
    try:
        return list_generations_service(db, content_id)
    except GenerationNotFound as exc:
        raise HTTPException(404, "Content not found") from exc


@router.post(
    "/profiles/{profile_id}/generate",
    response_model=GenerationRunOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_service_token)],
)
def generate_profile(profile_id: int, payload: GenerateContent | None = None, db: Session = Depends(get_db)):
    try:
        run = generate_profile_content_service(
            db,
            profile_id,
            model=payload.model if payload else None,
        )
    except GenerationNotFound as exc:
        db.rollback()
        raise HTTPException(404, "Content profile not found") from exc
    except GenerationProviderFailure as exc:
        db.commit()
        raise HTTPException(502, str(exc)) from exc
    except GenerationConflict as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from exc

    db.commit()
    db.refresh(run)
    return run


@router.post(
    "/generations/recover-stale",
    response_model=list[GenerationRunOut],
    dependencies=[Depends(require_service_token)],
)
def recover_stale_generations(db: Session = Depends(get_db)):
    return recover_stale_generations_service(db)
