from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from src.app.ai_generation import GenerationError, GenerationRequest, get_generation_provider
from src.app.audit import audit
from src.app.db import get_db
from src.app.domain.content_state_machine import transition
from src.app.models import Content, ContentVersion, GenerationRun

from src.app.routers.foundation import require_service_token

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
    content = db.query(Content).filter(Content.id == content_id).first()
    if not content:
        raise HTTPException(404, "Content not found")
    if content.status in {"published", "archived"}:
        raise HTTPException(409, "Content cannot be regenerated in its current state")

    provider_name = "openai"
    run = GenerationRun(
        content_id=content.id,
        provider=provider_name,
        model=payload.model,
        status="running",
        prompt=payload.prompt,
    )
    db.add(run)
    db.flush()

    try:
        provider = get_generation_provider()
        provider_name = provider.name
        run.provider = provider_name
        generated = provider.generate(
            prompt=payload.prompt,
            system_message=payload.system_message,
            model=payload.model,
        )
    except GenerationError as exc:
        run.status = "failed"
        run.error_message = str(exc)
        run.completed_at = datetime.utcnow()
        audit(
            db,
            content.workspace_id,
            "generation_run",
            run.id,
            "failed",
            event_type="content.generation_failed",
            metadata={"provider": run.provider, "model": run.model},
        )
        db.commit()
        raise HTTPException(502, str(exc)) from exc

    version_number = content.current_version.version + 1
    version = ContentVersion(
        content_id=content.id,
        version=version_number,
        body=generated,
        source=f"ai:{provider_name}",
        created_by=None,
    )
    db.add(version)
    db.flush()

    previous_status = content.status
    if previous_status != "draft":
        try:
            transition(previous_status, "draft")
        except ValueError as exc:
            db.rollback()
            raise HTTPException(409, "Content cannot be regenerated from its current state") from exc
        content.status = "draft"
    content.updated_at = datetime.utcnow()

    run.content_version_id = version.id
    run.status = "succeeded"
    run.completed_at = datetime.utcnow()
    audit(
        db,
        content.workspace_id,
        "generation_run",
        run.id,
        "completed",
        event_type="content.generation_completed",
        metadata={"provider": provider_name, "model": payload.model, "content_version_id": version.id},
    )
    audit(
        db,
        content.workspace_id,
        "content_version",
        version.id,
        "created",
        event_type="content_version.created",
        metadata={"source": version.source, "generation_run_id": run.id},
    )
    if previous_status != "draft":
        audit(
            db,
            content.workspace_id,
            "content",
            content.id,
            "status_changed",
            event_type="content.approval_invalidated",
            metadata={"from": previous_status, "to": "draft", "generation_run_id": run.id},
        )

    db.commit()
    db.refresh(run)
    return run


@router.get(
    "/contents/{content_id}/generations",
    response_model=list[GenerationRunOut],
    dependencies=[Depends(require_service_token)],
)
def list_generations(content_id: int, db: Session = Depends(get_db)):
    if not db.query(Content).filter(Content.id == content_id).first():
        raise HTTPException(404, "Content not found")
    return (
        db.query(GenerationRun)
        .filter(GenerationRun.content_id == content_id)
        .order_by(GenerationRun.created_at.desc(), GenerationRun.id.desc())
        .limit(100)
        .all()
    )
