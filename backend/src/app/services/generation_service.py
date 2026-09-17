from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from src.app.ai_generation import GenerationError, get_generation_provider
from src.app.audit import audit
from src.app.domain.content_state_machine import InvalidContentTransition, transition
from src.app.models import Content, ContentVersion, GenerationRun


class GenerationNotFound(Exception):
    pass


class GenerationConflict(Exception):
    pass


class GenerationProviderFailure(Exception):
    pass


def generate_content(
    db: Session,
    content_id: int,
    *,
    prompt: str,
    system_message: str | None = None,
    model: str | None = None,
    transform_generated=None,
) -> GenerationRun:
    content = db.query(Content).filter(Content.id == content_id).first()
    if not content:
        raise GenerationNotFound
    if content.status in {"published", "archived"}:
        raise GenerationConflict("Content cannot be regenerated in its current state")

    provider_name = "openai"
    run = GenerationRun(
        content_id=content.id,
        provider=provider_name,
        model=model,
        status="running",
        prompt=prompt,
    )
    db.add(run)
    db.flush()

    try:
        provider = get_generation_provider()
        provider_name = provider.name
        run.provider = provider_name
        generated = provider.generate(prompt=prompt, system_message=system_message, model=model)
        if transform_generated is not None:
            generated = transform_generated(generated)
    except (GenerationError, GenerationProviderFailure) as exc:
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
        raise GenerationProviderFailure(str(exc)) from exc

    version = ContentVersion(
        content_id=content.id,
        version=content.current_version.version + 1,
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
        except InvalidContentTransition as exc:
            raise GenerationConflict("Content cannot be regenerated from its current state") from exc
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
        metadata={"provider": provider_name, "model": model, "content_version_id": version.id},
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
    return run


def list_generations(db: Session, content_id: int) -> list[GenerationRun]:
    if not db.query(Content).filter(Content.id == content_id).first():
        raise GenerationNotFound
    return (
        db.query(GenerationRun)
        .filter(GenerationRun.content_id == content_id)
        .order_by(GenerationRun.created_at.desc(), GenerationRun.id.desc())
        .limit(100)
        .all()
    )
