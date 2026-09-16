from __future__ import annotations

from sqlalchemy.orm import Session

from src.app.audit import audit
from src.app.content_transformation import TransformationRequest, get_content_transformer
from src.app.models import Channel, Content, ContentVariant, ContentVersion


class VariantNotFound(Exception):
    pass


class VariantConflict(Exception):
    pass


class VariantProviderFailure(Exception):
    pass


def transform_content(
    db: Session,
    content_id: int,
    channel_id: int,
    *,
    content_version_id: int | None = None,
    instructions: str | None = None,
    model: str | None = None,
) -> ContentVariant:
    content = db.query(Content).filter(Content.id == content_id).first()
    if not content:
        raise VariantNotFound("Content not found")
    channel = db.query(Channel).filter(Channel.id == channel_id).first()
    if not channel:
        raise VariantNotFound("Channel not found")
    if channel.workspace_id != content.workspace_id:
        raise VariantConflict("Channel belongs to another workspace")
    if not channel.is_active:
        raise VariantConflict("Channel is inactive")

    if content_version_id is None:
        source_version = content.current_version
    else:
        source_version = (
            db.query(ContentVersion)
            .filter(ContentVersion.id == content_version_id, ContentVersion.content_id == content.id)
            .first()
        )
        if not source_version:
            raise VariantNotFound("Content version not found")

    latest = (
        db.query(ContentVariant)
        .filter(
            ContentVariant.content_version_id == source_version.id,
            ContentVariant.channel_id == channel.id,
        )
        .order_by(ContentVariant.version.desc(), ContentVariant.id.desc())
        .first()
    )
    variant_number = latest.version + 1 if latest else 1

    try:
        transformer = get_content_transformer()
        body = transformer.transform(
            TransformationRequest(
                body=source_version.body,
                platform=channel.platform,
                language=content.language,
                instructions=instructions,
                model=model,
            )
        )
    except Exception as exc:
        raise VariantProviderFailure(str(exc)) from exc

    variant = ContentVariant(
        content_id=content.id,
        content_version_id=source_version.id,
        channel_id=channel.id,
        version=variant_number,
        body=body,
        provider=transformer.name,
        model=model,
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
    return variant


def list_variants(
    db: Session,
    content_id: int,
    *,
    channel_id: int | None = None,
    content_version_id: int | None = None,
) -> list[ContentVariant]:
    if not db.query(Content).filter(Content.id == content_id).first():
        raise VariantNotFound("Content not found")
    query = db.query(ContentVariant).filter(ContentVariant.content_id == content_id)
    if channel_id is not None:
        query = query.filter(ContentVariant.channel_id == channel_id)
    if content_version_id is not None:
        query = query.filter(ContentVariant.content_version_id == content_version_id)
    return query.order_by(ContentVariant.created_at.desc(), ContentVariant.id.desc()).limit(200).all()
