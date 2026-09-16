from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from src.app.audit import audit
from src.app.content_transformation import TransformationRequest, get_content_transformer
from src.app.db import get_db
from src.app.models import Channel, Content, ContentVariant, ContentVersion
from src.app.routers.foundation import require_service_token

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
    content = db.query(Content).filter(Content.id == content_id).first()
    if not content:
        raise HTTPException(404, "Content not found")
    channel = db.query(Channel).filter(Channel.id == channel_id).first()
    if not channel:
        raise HTTPException(404, "Channel not found")
    if channel.workspace_id != content.workspace_id:
        raise HTTPException(409, "Channel belongs to another workspace")
    if not channel.is_active:
        raise HTTPException(409, "Channel is inactive")

    if payload.content_version_id is None:
        source_version = content.current_version
    else:
        source_version = (
            db.query(ContentVersion)
            .filter(ContentVersion.id == payload.content_version_id, ContentVersion.content_id == content.id)
            .first()
        )
        if not source_version:
            raise HTTPException(404, "Content version not found")

    latest = (
        db.query(ContentVariant)
        .filter(
            ContentVariant.content_version_id == source_version.id,
            ContentVariant.channel_id == channel.id,
        )
        .order_by(ContentVariant.version.desc(), ContentVariant.id.desc())
        .first()
    )
    variant_number = (latest.version + 1) if latest else 1

    try:
        transformer = get_content_transformer()
        body = transformer.transform(
            TransformationRequest(
                body=source_version.body,
                platform=channel.platform,
                language=content.language,
                instructions=payload.instructions,
                model=payload.model,
            )
        )
    except Exception as exc:
        db.rollback()
        raise HTTPException(502, str(exc)) from exc

    variant = ContentVariant(
        content_id=content.id,
        content_version_id=source_version.id,
        channel_id=channel.id,
        version=variant_number,
        body=body,
        provider=transformer.name,
        model=payload.model,
        status="draft",
    )
    db.add(variant)
    db.flush()
    audit(
        db,
        content.workspace_id,
        "content_variant",
        variant.id,
        "created",
        event_type="content_variant.created",
        metadata={
            "content_id": content.id,
            "content_version_id": source_version.id,
            "channel_id": channel.id,
            "platform": channel.platform,
            "version": variant.version,
            "provider": transformer.name,
        },
    )
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
    if not db.query(Content).filter(Content.id == content_id).first():
        raise HTTPException(404, "Content not found")
    query = db.query(ContentVariant).filter(ContentVariant.content_id == content_id)
    if channel_id is not None:
        query = query.filter(ContentVariant.channel_id == channel_id)
    if content_version_id is not None:
        query = query.filter(ContentVariant.content_version_id == content_version_id)
    return query.order_by(ContentVariant.created_at.desc(), ContentVariant.id.desc()).limit(200).all()
