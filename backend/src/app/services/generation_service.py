from __future__ import annotations

from datetime import datetime, timedelta
import os
import threading

from sqlalchemy import and_, or_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.app.db import SessionLocal

from src.app.ai_generation import GenerationError, get_generation_provider
from src.app.audit import audit
from src.app.domain.content_state_machine import InvalidContentTransition, transition
from src.app.models import Content, ContentProfile, ContentVersion, GenerationRun
from src.app.services.python_quality import extract_python_blocks, format_quality_failure, validate_post
from src.app.services.python_sandbox import PythonSandboxError, execute_python_blocks
from src.app.services.topic_memory import find_duplicate_topic, load_topic_memory


class GenerationNotFound(Exception):
    pass


class GenerationConflict(Exception):
    pass


class GenerationProviderFailure(Exception):
    pass


DEFAULT_GENERATION_LEASE_TIMEOUT_SECONDS = 900
MIN_GENERATION_LEASE_TIMEOUT_SECONDS = 60
MAX_GENERATION_LEASE_TIMEOUT_SECONDS = 86400


def generation_lease_timeout_seconds() -> int:
    raw = os.environ.get("GENERATION_LEASE_TIMEOUT_SECONDS", str(DEFAULT_GENERATION_LEASE_TIMEOUT_SECONDS))
    try:
        value = int(raw)
    except ValueError:
        value = DEFAULT_GENERATION_LEASE_TIMEOUT_SECONDS
    return max(MIN_GENERATION_LEASE_TIMEOUT_SECONDS, min(value, MAX_GENERATION_LEASE_TIMEOUT_SECONDS))


def _generation_heartbeat_interval_seconds() -> float:
    return max(5.0, min(generation_lease_timeout_seconds() / 3.0, 60.0))


def _heartbeat_generation(run_id: int, stop_event: threading.Event) -> None:
    interval = _generation_heartbeat_interval_seconds()
    while not stop_event.wait(interval):
        heartbeat_db = SessionLocal()
        try:
            run = heartbeat_db.query(GenerationRun).filter(
                GenerationRun.id == run_id,
                GenerationRun.status == "running",
            ).first()
            if run is None:
                return
            run.lease_heartbeat_at = datetime.utcnow()
            heartbeat_db.commit()
        except Exception:
            heartbeat_db.rollback()
        finally:
            heartbeat_db.close()

def recover_stale_generations(db: Session) -> list[GenerationRun]:
    now = datetime.utcnow()
    cutoff = now - timedelta(seconds=generation_lease_timeout_seconds())
    candidates = (db.query(GenerationRun)
        .filter(
            GenerationRun.status == "running",
            ((GenerationRun.lease_heartbeat_at.is_not(None) & (GenerationRun.lease_heartbeat_at < cutoff)) |
             (GenerationRun.lease_heartbeat_at.is_(None) & (GenerationRun.created_at < cutoff))),
        )
        .order_by(GenerationRun.id.asc()).all())
    recovered = []
    for candidate in candidates:
        result = db.execute(
            update(GenerationRun)
            .where(
                GenerationRun.id == candidate.id,
                GenerationRun.status == "running",
                or_(
                    and_(GenerationRun.lease_heartbeat_at.is_not(None), GenerationRun.lease_heartbeat_at < cutoff),
                    and_(GenerationRun.lease_heartbeat_at.is_(None), GenerationRun.created_at < cutoff),
                ),
            )
            .values(
                status="failed",
                error_message="Recovered stale generation run after worker restart or timeout",
                completed_at=now,
                lease_heartbeat_at=None,
            )
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            continue
        run = db.query(GenerationRun).populate_existing().filter(GenerationRun.id == candidate.id).first()
        profile = run.content.profile
        if profile is not None:
            profile.regeneration_requested = True
            profile.updated_at = now
        audit(db, run.content.workspace_id, "generation_run", run.id, "recovered",
              event_type="content.generation_recovered", metadata={"error_message": run.error_message})
        recovered.append(run)
    if recovered:
        db.commit()
    return recovered


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

    now = datetime.utcnow()
    active = (
        db.query(GenerationRun)
        .filter(GenerationRun.content_id == content.id, GenerationRun.status == "running")
        .order_by(GenerationRun.id.desc())
        .first()
    )
    if active is not None:
        cutoff = now - timedelta(seconds=generation_lease_timeout_seconds())
        last_activity = active.lease_heartbeat_at or active.created_at
        if last_activity >= cutoff:
            raise GenerationConflict("Content already has a generation run in progress")
        result = db.execute(
            update(GenerationRun)
            .where(
                GenerationRun.id == active.id,
                GenerationRun.status == "running",
                or_(
                    and_(GenerationRun.lease_heartbeat_at.is_not(None), GenerationRun.lease_heartbeat_at < cutoff),
                    and_(GenerationRun.lease_heartbeat_at.is_(None), GenerationRun.created_at < cutoff),
                ),
            )
            .values(
                status="failed",
                error_message="Recovered stale generation run before starting a new run",
                completed_at=now,
                lease_heartbeat_at=None,
            )
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            raise GenerationConflict("Content already has a generation run in progress")
        audit(
            db,
            content.workspace_id,
            "generation_run",
            active.id,
            "recovered",
            event_type="content.generation_recovered",
            metadata={"error_message": "Recovered stale generation run before starting a new run"},
        )
        db.flush()

    run = GenerationRun(
        content_id=content.id,
        provider="configured",
        model=model,
        status="running",
        prompt=prompt,
        lease_heartbeat_at=now,
    )
    db.add(run)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise GenerationConflict("Content already has a generation run in progress") from exc

    heartbeat_stop = threading.Event()
    heartbeat_thread: threading.Thread | None = None

    def fail_run(message: str, *, unexpected: bool = False) -> None:
        db.rollback()
        failed_run = db.query(GenerationRun).filter(GenerationRun.id == run.id).first() or run
        failed_run.status = "failed"
        failed_run.error_message = message[:4000]
        failed_run.completed_at = datetime.utcnow()
        failed_run.lease_heartbeat_at = None
        audit(
            db,
            content.workspace_id,
            "generation_run",
            failed_run.id,
            "failed",
            event_type="content.generation_failed",
            metadata={"provider": failed_run.provider, "model": failed_run.model, "unexpected": unexpected},
        )
        db.commit()

    try:
        provider = get_generation_provider()
        provider_name = provider.name
        run.provider = provider_name
        run.lease_heartbeat_at = datetime.utcnow()
        db.commit()

        heartbeat_thread = threading.Thread(
            target=_heartbeat_generation,
            args=(run.id, heartbeat_stop),
            name=f"generation-heartbeat-{run.id}",
            daemon=True,
        )
        heartbeat_thread.start()

        generated = provider.generate(prompt=prompt, system_message=system_message, model=model)
        if transform_generated is not None:
            generated = transform_generated(generated)
    except (GenerationError, GenerationProviderFailure) as exc:
        fail_run(str(exc))
        raise GenerationProviderFailure(str(exc)) from exc
    except Exception as exc:
        fail_run(str(exc), unexpected=True)
        raise GenerationProviderFailure("Generation failed unexpectedly") from exc
    finally:
        heartbeat_stop.set()
        if heartbeat_thread is not None:
            heartbeat_thread.join(timeout=2.0)

    try:
        version = ContentVersion(
            content_id=content.id,
            version=(content.versions[-1].version + 1) if content.versions else 1,
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
        run.lease_heartbeat_at = None
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
    except GenerationProviderFailure:
        raise
    except Exception as exc:
        fail_run(str(exc), unexpected=True)
        raise GenerationProviderFailure("Generation failed while persisting its result") from exc

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


def _parse_autonomous_output(text: str) -> tuple[str, str]:
    import re
    value = (text or "").strip()
    match = re.search(r"TOPIC:\s*(.+?)\s*POST:\s*(.+)", value, re.S | re.I)
    if not match:
        match = re.search(r"TOPIC:\s*(.+?)\s*MESSAGE:\s*(.+)", value, re.S | re.I)
    if match:
        topic, body = match.group(1).strip().strip('"').strip("'"), match.group(2).strip()
    else:
        lines = value.splitlines()
        if len(lines) >= 2:
            topic, body = lines[0].strip().strip('"').strip("'"), "\n".join(lines[1:]).strip()
        else:
            raise GenerationProviderFailure("AI provider returned an invalid autonomous content format")
    if not topic or not body:
        raise GenerationProviderFailure("AI provider returned empty autonomous content")
    if len(body) < 20 or len(body) > 12000:
        raise GenerationProviderFailure("AI provider returned content outside the supported length")
    if re.search(r"<\/?(?:script|style|iframe)\b", body, re.I):
        raise GenerationProviderFailure("AI provider returned unsafe content")
    if re.search(r"\[(?:insert|add|write|replace)|\{\{.*?\}\}", body, re.I):
        raise GenerationProviderFailure("AI provider returned placeholder content")
    return topic[:200], body


def build_profile_generation_prompt(profile: ContentProfile, used_topics: set[str]) -> str:
    existing = ", ".join(sorted(used_topics)) if used_topics else "none"
    return (
        "You are an autonomous content editor. Choose the topic yourself; never ask the operator for one. "
        "Create one complete publication-ready post for the configured profile. Avoid previously used topics. "
        "Never output scripts, styles, placeholders, or an outline. Any Python code fence must be syntactically valid. Return exactly:\n"
        "TOPIC: <short topic name>\n"
        "POST: <ready-to-publish message>\n\n"
        f"Channel: {profile.channel.name or profile.channel.external_id}\n"
        f"Language: {profile.language}\n"
        f"Topic/niche: {profile.topic_niche or 'Choose a useful, timely topic in the channel niche'}\n"
        f"Tone: {profile.tone or 'Clear, useful, and natural'}\n"
        f"Content format: {profile.content_format or 'Publication-ready post'}\n"
        f"Editorial rules: {profile.rules or 'No clickbait; no placeholders; provide useful substance'}\n"
        f"Topic memory (do not repeat or closely rephrase): {existing}"
    )


def generate_profile_content(db: Session, profile_id: int, *, model: str | None = None) -> GenerationRun:
    profile = (
        db.query(ContentProfile)
        .filter(ContentProfile.id == profile_id, ContentProfile.is_active.is_(True))
        .first()
    )
    if not profile:
        raise GenerationNotFound

    # Recover abandoned work before deciding whether this profile needs a new item.
    # A stale run is converted to a failed run, then the same Content row/prompt
    # is reused below instead of creating a fresh editorial task.
    recover_stale_generations(db)

    topic_memory = load_topic_memory(db, profile.id)
    used_topics = {title.casefold() for title, _status in topic_memory}

    # A failed autonomous generation is recoverable work, not a new content item.
    # Reuse the same Content row and the last persisted prompt so a worker restart
    # does not silently select a different topic and start the editorial cycle over.
    recoverable = (
        db.query(Content)
        .filter(
            Content.profile_id == profile.id,
            Content.title == "AI generation in progress",
            Content.status == "draft",
        )
        .order_by(Content.created_at.asc(), Content.id.asc())
        .all()
    )
    content = None
    recovery_prompt = None
    for candidate in recoverable:
        latest_run = (
            db.query(GenerationRun)
            .filter(GenerationRun.content_id == candidate.id)
            .order_by(GenerationRun.id.desc())
            .first()
        )
        if latest_run is None:
            continue
        if latest_run.status == "running":
            raise GenerationConflict("Profile already has a generation run in progress")
        if latest_run.status == "failed":
            content = candidate
            # A duplicate-topic failure must not replay the same prompt forever.
            # It is safe to reuse prompts for provider/worker failures only.
            if not (latest_run.error_message or "").startswith("duplicate_topic:"):
                recovery_prompt = latest_run.prompt
            break

    if content is None:
        content = Content(
            workspace_id=profile.workspace_id,
            profile_id=profile.id,
            title="AI generation in progress",
            language=profile.language,
            status="draft",
            created_by=None,
        )
        db.add(content)
        db.flush()

    topic_holder: dict[str, str] = {}

    def transform_generated(generated: str) -> str:
        topic, body = _parse_autonomous_output(generated)
        quality = validate_post(body)
        if not quality.valid:
            raise GenerationProviderFailure(
                f"python_quality: {format_quality_failure(quality)}"
            )
        duplicate = find_duplicate_topic(topic, topic_memory)
        if duplicate is not None:
            existing, status, score = duplicate
            raise GenerationProviderFailure(
                f"duplicate_topic: generated topic is too similar to existing topic "
                f"{existing!r} (status={status}, similarity={score:.2f})"
            )
        topic_holder["topic"] = topic
        return body

    try:
        run = generate_content(
            db,
            content.id,
            prompt=recovery_prompt or build_profile_generation_prompt(profile, used_topics),
            system_message="You are an autonomous content editor. Produce complete publication-ready content.",
            model=model,
            transform_generated=transform_generated,
        )
    except GenerationProviderFailure:
        profile.regeneration_requested = True
        db.flush()
        raise

    content.title = topic_holder["topic"]
    db.flush()
    return run
