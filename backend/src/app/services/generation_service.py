from __future__

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
from src.app.services.python_quality import format_quality_failure, validate_post
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
MAX_TOPIC_SELECTION_ATTEMPTS = 5


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
    candidates = (
        db.query(GenerationRun)
        .filter(
            GenerationRun.status == "running",
            (
                (GenerationRun.lease_heartbeat_at.is_not(None) & (GenerationRun.lease_heartbeat_at < cutoff))
                | (GenerationRun.lease_heartbeat_at.is_(None) & (GenerationRun.created_at < cutoff))
            ),
        )
        .order_by(GenerationRun.id.asc())
        .all()
    )
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
        audit(
            db,
            run.content.workspace_id,
            "generation_run",
            run.id,
            "recovered",
            event_type="content.generation_recovered",
            metadata={"error_message": run.error_message},
        )
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


def _parse_topic_output(text: str) -> str:
    import re

    value = (text or "").strip()
    match = re.search(r"^TOPIC:\s*(.+?)\s*$", value, re.I | re.M)
    if not match:
        raise GenerationProviderFailure("AI provider returned an invalid topic format")
    topic = match.group(1).strip().strip('"').strip("'")
    if not topic:
        raise GenerationProviderFailure("AI provider returned an empty topic")
    return topic[:200]


def build_profile_generation_prompt(profile: ContentProfile) -> str:
    return (
        "You are an autonomous content editor. Choose exactly one topic for a publication. "
        "Do not write the publication yet. Never ask the operator for a topic. Return exactly:\n"
        "TOPIC: <short topic name>\n\n"
        f"Channel: {profile.channel.name or profile.channel.external_id}\n"
        f"Language: {profile.language}\n"
        f"Topic/niche: {profile.topic_niche or 'Choose a useful, timely topic in the channel niche'}\n"
        f"Tone: {profile.tone or 'Clear, useful, and natural'}\n"
        f"Content format: {profile.content_format or 'Publication-ready post'}\n"
        f"Editorial rules: {profile.rules or 'No clickbait; no placeholders; provide useful substance'}"
    )


def build_profile_post_prompt(profile: ContentProfile, topic: str) -> str:
    return (
        "You are an autonomous content editor. Create one complete publication-ready post "
        "for the configured profile using exactly the selected topic below. "
        "Do not change the topic and do not ask the operator for another topic. "
        "Never output scripts, styles, placeholders, or an outline. "
        "Any Python code fence must be syntactically valid. Return exactly:\n"
        "POST: <ready-to-publish message>\n\n"
        f"Selected topic: {topic}\n"
        f"Channel: {profile.channel.name or profile.channel.external_id}\n"
        f"Language: {profile.language}\n"
        f"Topic/niche: {profile.topic_niche or 'Use the selected topic within the channel niche'}\n"
        f"Tone: {profile.tone or 'Clear, useful, and natural'}\n"
        f"Content format: {profile.content_format or 'Publication-ready post'}\n"
        f"Editorial rules: {profile.rules or 'No clickbait; no placeholders; provide useful substance'}"
    )


def _select_unique_topic(
    profile: ContentProfile,
    topic_memory: list[tuple[str, str]],
    *,
    model: str | None = None,
) -> str:
    provider = get_generation_provider()
    prompt = build_profile_generation_prompt(profile)
    duplicate_topic: str | None = None

    for _attempt in range(MAX_TOPIC_SELECTION_ATTEMPTS):
        if duplicate_topic is not None:
            prompt = (
                build_profile_generation_prompt(profile)
                + "\n\n"
                f'The topic "{duplicate_topic}" was already used. '
                "Choose a genuinely different topic. Do not repeat or closely rephrase it. "
                "Return only the new TOPIC line."
            )
        try:
            generated_topic = provider.generate(
                prompt=prompt,
                system_message="You select unique publication topics. Return only the requested topic line.",
                model=model,
            )
        except GenerationError as exc:
            raise GenerationProviderFailure(str(exc)) from exc
        except Exception as exc:
            raise GenerationProviderFailure("Generation failed unexpectedly") from exc

        topic = _parse_topic_output(generated_topic)
        duplicate = find_duplicate_topic(topic, topic_memory)
        if duplicate is None:
            return topic
        duplicate_topic = duplicate[0]

    raise GenerationProviderFailure(
        f"Unable to select a unique topic after {MAX_TOPIC_SELECTION_ATTEMPTS} attempts"
    )


def _parse_post_output(text: str) -> str:
    import re

    value = (text or "").strip()
    match = re.search(r"^POST:\s*(.+)", value, re.I | re.S)
    if match:
        value = match.group(1).strip()
    if not value:
        raise GenerationProviderFailure("AI provider returned an empty post")
    return value


def generate_profile_content(
    db: Session,
    profile_id: int,
    *,
    model: str | None = None,
    scheduler_lease_token: str | None = None,
) -> GenerationRun:
    profile = (
        db.query(ContentProfile)
        .filter(ContentProfile.id == profile_id, ContentProfile.is_active.is_(True))
        .first()
    )
    if not profile:
        raise GenerationNotFound
    if profile.scheduler_lease_token and profile.scheduler_lease_token != scheduler_lease_token:
        raise GenerationConflict("Profile is owned by the autonomous scheduler")

    recover_stale_generations(db)
    topic_memory = load_topic_memory(db, profile.id)
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

    try:
        topic = _select_unique_topic(profile, topic_memory, model=model)
    except GenerationProviderFailure as exc:
        profile.regeneration_requested = True
        failed_run = GenerationRun(
            content_id=content.id,
            provider="configured",
            model=model,
            status="failed",
            prompt=build_profile_generation_prompt(profile),
            error_message=str(exc)[:4000],
            completed_at=datetime.utcnow(),
            lease_heartbeat_at=None,
        )
        db.add(failed_run)
        db.flush()
        audit(
            db,
            content.workspace_id,
            "generation_run",
            failed_run.id,
            "failed",
            event_type="content.generation_failed",
            metadata={"provider": failed_run.provider, "model": failed_run.model, "phase": "topic_selection"},
        )
        db.commit()
        raise

    def transform_generated(generated: str) -> str:
        value = _parse_post_output(generated)
        quality = validate_post(value)
        if not quality.valid:
            raise GenerationProviderFailure(f"python_quality: {format_quality_failure(quality)}")
        return value

    try:
        run = generate_content(
            db,
            content.id,
            prompt=build_profile_post_prompt(profile, topic),
            system_message="You are an autonomous content editor. Produce complete publication-ready content.",
            model=model,
            transform_generated=transform_generated,
        )
    except GenerationProviderFailure:
        profile.regeneration_requested = True
        db.flush()
        raise

    content.title = topic
    previous_status = content.status
    transition(previous_status, "review")
    content.status = "review"
    content.updated_at = datetime.utcnow()
    audit(
        db,
        content.workspace_id,
        "content",
        content.id,
        "status_changed",
        event_type="content.ready_for_approval",
        metadata={"from": previous_status, "to": "review", "generation_run_id": run.id},
    )
    db.flush()
    return run
