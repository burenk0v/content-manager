import os
from datetime import datetime, date, timedelta, time
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field, validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.app.db import get_db
from src.app.models import AssistantMessageTemplate, PublicationSchedule, Prompt, Topic, PostDraft

router = APIRouter()

VALID_SCHEDULE_TYPES = {"interval", "daily"}
VALID_LANGUAGES = {"ru", "en", "es"}
VALID_DRAFT_STATUSES = {"pending", "rejected", "published"}


def _check_service_token(x_service_token: Optional[str] = Header(None)):
    expected = os.environ.get("SERVICE_ACCOUNT_TOKEN")
    if not expected:
        return True
    return x_service_token == expected


class TopicCreate(BaseModel):
    name: str = Field(..., min_length=1)
    language: str = Field(..., min_length=2)

    @validator("language")
    def validate_language(cls, value):
        language = value.strip().lower()
        if language not in VALID_LANGUAGES:
            raise ValueError("language must be one of ru, en, es")
        return language


class TopicOut(TopicCreate):
    id: int
    created_at: datetime

    class Config:
        orm_mode = True


class PromptCreate(BaseModel):
    name: str = Field(..., min_length=1)
    language: str = Field(..., min_length=2)
    text: str = Field(..., min_length=1)

    @validator("language")
    def validate_language(cls, value):
        language = value.strip().lower()
        if language not in VALID_LANGUAGES:
            raise ValueError("language must be one of ru, en, es")
        return language


class PromptOut(PromptCreate):
    id: int
    created_at: datetime

    class Config:
        orm_mode = True


class AssistantMessageTemplateCreate(BaseModel):
    name: str = Field(..., min_length=1)
    language: str = Field(..., min_length=2)
    text: str = Field(..., min_length=1)

    @validator("language")
    def validate_language(cls, value):
        language = value.strip().lower()
        if language not in VALID_LANGUAGES:
            raise ValueError("language must be one of ru, en, es")
        return language


class AssistantMessageTemplateOut(AssistantMessageTemplateCreate):
    id: int
    created_at: datetime

    class Config:
        orm_mode = True


class ScheduleBase(BaseModel):
    name: str = Field(..., min_length=1)
    chat_id: str = Field(..., min_length=1)
    chat_name: Optional[str] = None
    language: str = Field(..., min_length=2)
    assistant_message: Optional[str] = None
    prompt_id: Optional[int] = None
    assistant_template_id: Optional[int] = None
    schedule_type: str
    schedule_value: str
    is_active: bool = True

    @validator("language")
    def validate_language(cls, value):
        language = value.strip().lower()
        if language not in VALID_LANGUAGES:
            raise ValueError("language must be one of ru, en, es")
        return language

    @validator("schedule_type")
    def validate_schedule_type(cls, value):
        value = value.strip().lower()
        if value not in VALID_SCHEDULE_TYPES:
            raise ValueError("schedule_type must be 'interval' or 'daily'")
        return value

    @validator("prompt_id")
    def validate_prompt_id(cls, value):
        if value is None:
            return value
        if value <= 0:
            raise ValueError("prompt_id must be a positive integer")
        return value

    @validator("assistant_template_id")
    def validate_assistant_template_id(cls, value):
        if value is None:
            return value
        if value <= 0:
            raise ValueError("assistant_template_id must be a positive integer")
        return value

    @validator("schedule_value")
    def validate_schedule_value(cls, value, values):
        schedule_type = values.get("schedule_type")
        if not schedule_type:
            return value
        target = value.strip()
        if schedule_type == "interval":
            if not target.isdigit() or int(target) <= 0:
                raise ValueError("schedule_value for interval must be a positive integer")
        elif schedule_type == "daily":
            try:
                datetime.strptime(target, "%H:%M").time()
            except ValueError:
                raise ValueError("schedule_value for daily must be in HH:MM format")
        return target


class ScheduleCreate(ScheduleBase):
    pass


class ScheduleUpdate(BaseModel):
    name: Optional[str] = None
    chat_id: Optional[str] = None
    chat_name: Optional[str] = None
    language: Optional[str] = None
    assistant_message: Optional[str] = None
    prompt_id: Optional[int] = None
    assistant_template_id: Optional[int] = None
    schedule_type: Optional[str] = None
    schedule_value: Optional[str] = None
    is_active: Optional[bool] = None
    last_run: Optional[datetime] = None

    @validator("language")
    def validate_language(cls, value):
        if value is None:
            return value
        language = value.strip().lower()
        if language not in VALID_LANGUAGES:
            raise ValueError("language must be one of ru, en, es")
        return language

    @validator("schedule_type")
    def validate_schedule_type(cls, value):
        if value is None:
            return value
        value = value.strip().lower()
        if value not in VALID_SCHEDULE_TYPES:
            raise ValueError("schedule_type must be 'interval' or 'daily'")
        return value

    @validator("prompt_id")
    def validate_prompt_id(cls, value):
        if value is None:
            return value
        if value <= 0:
            raise ValueError("prompt_id must be a positive integer")
        return value

    @validator("assistant_template_id")
    def validate_assistant_template_id(cls, value):
        if value is None:
            return value
        if value <= 0:
            raise ValueError("assistant_template_id must be a positive integer")
        return value

    @validator("schedule_value")
    def validate_schedule_value(cls, value):
        if value is None:
            return value
        target = value.strip()
        if ":" in target:
            try:
                datetime.strptime(target, "%H:%M").time()
            except ValueError:
                raise ValueError("schedule_value for daily must be in HH:MM format")
        elif not target.isdigit() or int(target) <= 0:
            raise ValueError("schedule_value for interval must be a positive integer")
        return target


class ScheduleOut(ScheduleBase):
    id: int
    last_run: Optional[datetime]
    created_at: datetime
    next_run: Optional[datetime] = None
    prompt_name: Optional[str] = None
    prompt_text: Optional[str] = None
    assistant_template_name: Optional[str] = None
    assistant_template_text: Optional[str] = None

    class Config:
        orm_mode = True


class DraftBase(BaseModel):
    schedule_id: int
    topic_id: Optional[int] = None
    topic_name: str
    language: str
    generated_text: str
    status: str = Field("pending")

    @validator("status")
    def validate_status(cls, value):
        if value not in VALID_DRAFT_STATUSES:
            raise ValueError(f"status must be one of {VALID_DRAFT_STATUSES}")
        return value


class DraftCreate(DraftBase):
    pass


class DraftUpdate(BaseModel):
    status: Optional[str] = None
    generated_text: Optional[str] = None
    topic_id: Optional[int] = None

    @validator("status")
    def validate_status(cls, value):
        if value is None:
            return value
        if value not in VALID_DRAFT_STATUSES:
            raise ValueError(f"status must be one of {VALID_DRAFT_STATUSES}")
        return value


class DraftOut(DraftBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True


def compute_next_run(schedule: PublicationSchedule) -> Optional[datetime]:
    now = datetime.utcnow()
    if schedule.schedule_type == "interval":
        try:
            interval = int(schedule.schedule_value)
        except ValueError:
            return None
        if schedule.last_run is None:
            return now
        return schedule.last_run + timedelta(minutes=interval)

    if schedule.schedule_type == "daily":
        try:
            run_time = datetime.strptime(schedule.schedule_value, "%H:%M").time()
        except ValueError:
            return None
        today = now.date()
        scheduled = datetime.combine(today, run_time)
        if schedule.last_run is None or schedule.last_run.date() < today:
            if scheduled <= now:
                return datetime.combine(today + timedelta(days=1), run_time)
            return scheduled
        return datetime.combine(today + timedelta(days=1), run_time)

    return None


def is_schedule_due(schedule: PublicationSchedule) -> bool:
    if not schedule.is_active:
        return False
    now = datetime.utcnow()
    if schedule.schedule_type == "interval":
        if schedule.last_run is None:
            return True
        try:
            interval = int(schedule.schedule_value)
        except ValueError:
            return False
        return now >= schedule.last_run + timedelta(minutes=interval)

    if schedule.schedule_type == "daily":
        try:
            run_time = datetime.strptime(schedule.schedule_value, "%H:%M").time()
        except ValueError:
            return False
        today = date.today()
        scheduled = datetime.combine(today, run_time)
        if now < scheduled:
            return False
        return schedule.last_run is None or schedule.last_run.date() < today

    return False


def schedule_out(schedule: PublicationSchedule) -> ScheduleOut:
    return ScheduleOut(
        id=schedule.id,
        name=schedule.name,
        chat_id=schedule.chat_id,
        chat_name=schedule.chat_name,
        language=schedule.language,
        assistant_message=schedule.assistant_message,
        prompt_id=schedule.prompt_id,
        assistant_template_id=schedule.assistant_template_id,
        schedule_type=schedule.schedule_type,
        schedule_value=schedule.schedule_value,
        is_active=schedule.is_active,
        last_run=schedule.last_run,
        created_at=schedule.created_at,
        next_run=compute_next_run(schedule),
        prompt_name=schedule.prompt.name if schedule.prompt else None,
        prompt_text=schedule.prompt.text if schedule.prompt else None,
        assistant_template_name=schedule.assistant_template.name if schedule.assistant_template else None,
        assistant_template_text=schedule.assistant_template.text if schedule.assistant_template else None,
    )


@router.get("/topics", response_model=List[TopicOut])
def get_topics(
    x_service_token: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    if not _check_service_token(x_service_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid service token")
    topics = db.query(Topic).order_by(Topic.created_at.desc()).all()
    return topics


@router.get("/prompts", response_model=List[PromptOut])
def get_prompts(
    x_service_token: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    if not _check_service_token(x_service_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid service token")
    prompts = db.query(Prompt).order_by(Prompt.created_at.desc()).all()
    return prompts


@router.get("/assistant-messages", response_model=List[AssistantMessageTemplateOut])
def get_assistant_messages(
    x_service_token: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    if not _check_service_token(x_service_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid service token")
    assistant_messages = db.query(AssistantMessageTemplate).order_by(AssistantMessageTemplate.created_at.desc()).all()
    return assistant_messages


@router.post("/prompts", response_model=PromptOut, status_code=status.HTTP_201_CREATED)
def create_prompt(
    payload: PromptCreate,
    x_service_token: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    if not _check_service_token(x_service_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid service token")
    prompt = Prompt(name=payload.name.strip(), language=payload.language.strip(), text=payload.text)
    db.add(prompt)
    try:
        db.commit()
        db.refresh(prompt)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Prompt already exists")
    return prompt


@router.post("/assistant-messages", response_model=AssistantMessageTemplateOut, status_code=status.HTTP_201_CREATED)
def create_assistant_message(
    payload: AssistantMessageTemplateCreate,
    x_service_token: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    if not _check_service_token(x_service_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid service token")
    assistant_message = AssistantMessageTemplate(
        name=payload.name.strip(),
        language=payload.language.strip(),
        text=payload.text,
    )
    db.add(assistant_message)
    try:
        db.commit()
        db.refresh(assistant_message)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Assistant message already exists")
    return assistant_message


@router.delete("/prompts/{prompt_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_prompt(
    prompt_id: int,
    x_service_token: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    if not _check_service_token(x_service_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid service token")
    prompt = db.query(Prompt).filter(Prompt.id == prompt_id).first()
    if not prompt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prompt not found")
    in_use = db.query(PublicationSchedule).filter(PublicationSchedule.prompt_id == prompt_id).first()
    if in_use:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Prompt is used by existing schedules")
    db.delete(prompt)
    db.commit()


@router.delete("/assistant-messages/{assistant_message_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_assistant_message(
    assistant_message_id: int,
    x_service_token: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    if not _check_service_token(x_service_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid service token")
    assistant_message = db.query(AssistantMessageTemplate).filter(AssistantMessageTemplate.id == assistant_message_id).first()
    if not assistant_message:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assistant message not found")
    in_use = db.query(PublicationSchedule).filter(PublicationSchedule.assistant_template_id == assistant_message_id).first()
    if in_use:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Assistant message is used by existing schedules")
    db.delete(assistant_message)
    db.commit()


@router.post("/topics", response_model=TopicOut, status_code=status.HTTP_201_CREATED)
def create_topic(
    payload: TopicCreate,
    x_service_token: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    if not _check_service_token(x_service_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid service token")
    topic = Topic(name=payload.name.strip(), language=payload.language.strip())
    db.add(topic)
    try:
        db.commit()
        db.refresh(topic)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Topic already exists")
    return topic


@router.delete("/topics/{topic_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_topic(
    topic_id: int,
    x_service_token: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    if not _check_service_token(x_service_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid service token")
    topic = db.query(Topic).filter(Topic.id == topic_id).first()
    if not topic:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Topic not found")
    db.delete(topic)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Topic cannot be deleted because it is referenced by existing drafts. Delete related drafts first."
        )


@router.get("/schedules", response_model=List[ScheduleOut])
def get_schedules(
    x_service_token: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    if not _check_service_token(x_service_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid service token")
    schedules = db.query(PublicationSchedule).order_by(PublicationSchedule.created_at.desc()).all()
    return [schedule_out(schedule) for schedule in schedules]


@router.get("/schedules/ready", response_model=List[ScheduleOut])
def get_ready_schedules(
    x_service_token: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    if not _check_service_token(x_service_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid service token")
    schedules = db.query(PublicationSchedule).filter(PublicationSchedule.is_active == True).all()
    due = [schedule_out(schedule) for schedule in schedules if is_schedule_due(schedule)]
    return due


@router.get("/schedules/{schedule_id}", response_model=ScheduleOut)
def get_schedule(
    schedule_id: int,
    x_service_token: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    if not _check_service_token(x_service_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid service token")
    schedule = db.query(PublicationSchedule).filter(PublicationSchedule.id == schedule_id).first()
    if not schedule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")
    return schedule_out(schedule)


@router.post("/schedules", response_model=ScheduleOut, status_code=status.HTTP_201_CREATED)
def create_schedule(
    payload: ScheduleCreate,
    x_service_token: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    if not _check_service_token(x_service_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid service token")
    if payload.prompt_id is not None:
        prompt = db.query(Prompt).filter(Prompt.id == payload.prompt_id).first()
        if not prompt:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prompt not found")
    if payload.assistant_template_id is not None:
        assistant_template = db.query(AssistantMessageTemplate).filter(AssistantMessageTemplate.id == payload.assistant_template_id).first()
        if not assistant_template:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assistant message not found")
    if not (payload.assistant_message or payload.assistant_template_id is not None):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="assistant_message or assistant_template_id is required")
    schedule = PublicationSchedule(
        name=payload.name.strip(),
        chat_id=payload.chat_id.strip(),
        chat_name=payload.chat_name.strip() if payload.chat_name else None,
        language=payload.language.strip(),
        assistant_message=payload.assistant_message or "",
        prompt_id=payload.prompt_id,
        assistant_template_id=payload.assistant_template_id,
        schedule_type=payload.schedule_type,
        schedule_value=payload.schedule_value,
        is_active=payload.is_active,
    )
    db.add(schedule)
    db.commit()
    db.refresh(schedule)
    return schedule_out(schedule)


@router.put("/schedules/{schedule_id}", response_model=ScheduleOut)
def update_schedule(
    schedule_id: int,
    payload: ScheduleUpdate,
    x_service_token: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    if not _check_service_token(x_service_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid service token")
    schedule = db.query(PublicationSchedule).filter(PublicationSchedule.id == schedule_id).first()
    if not schedule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")
    update_data = payload.dict(exclude_unset=True)
    if "prompt_id" in update_data and update_data["prompt_id"] is not None:
        prompt = db.query(Prompt).filter(Prompt.id == update_data["prompt_id"]).first()
        if not prompt:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prompt not found")
    if "assistant_template_id" in update_data and update_data["assistant_template_id"] is not None:
        assistant_template = db.query(AssistantMessageTemplate).filter(AssistantMessageTemplate.id == update_data["assistant_template_id"]).first()
        if not assistant_template:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assistant message not found")
    effective_assistant_message = update_data.get("assistant_message", schedule.assistant_message)
    effective_assistant_template_id = update_data.get("assistant_template_id", schedule.assistant_template_id)
    if not (effective_assistant_message or effective_assistant_template_id is not None):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="assistant_message or assistant_template_id is required")
    if "assistant_message" in update_data and update_data["assistant_message"] is None:
        update_data["assistant_message"] = ""
    schedule_definition_changed = any(
        update_data.get(field) != getattr(schedule, field)
        for field in ("schedule_type", "schedule_value")
        if field in update_data
    )
    if schedule_definition_changed and "last_run" not in update_data:
        update_data["last_run"] = None
    for key, value in update_data.items():
        setattr(schedule, key, value)
    db.commit()
    db.refresh(schedule)
    return schedule_out(schedule)


@router.delete("/schedules/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_schedule(
    schedule_id: int,
    x_service_token: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    if not _check_service_token(x_service_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid service token")
    schedule = db.query(PublicationSchedule).filter(PublicationSchedule.id == schedule_id).first()
    if not schedule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")
    db.delete(schedule)
    db.commit()


@router.post("/drafts", response_model=DraftOut, status_code=status.HTTP_201_CREATED)
def create_draft(
    payload: DraftCreate,
    x_service_token: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    if not _check_service_token(x_service_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid service token")
    schedule = db.query(PublicationSchedule).filter(PublicationSchedule.id == payload.schedule_id).first()
    if not schedule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")
    if payload.topic_id is not None:
        topic = db.query(Topic).filter(Topic.id == payload.topic_id).first()
        if not topic:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Topic not found")
    draft = PostDraft(
        schedule_id=payload.schedule_id,
        topic_id=payload.topic_id,
        topic_name=payload.topic_name.strip(),
        language=payload.language.strip(),
        generated_text=payload.generated_text.strip(),
        status=payload.status,
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


@router.get("/drafts", response_model=List[DraftOut])
def list_drafts(
    status: Optional[str] = None,
    x_service_token: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    if not _check_service_token(x_service_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid service token")
    query = db.query(PostDraft)
    if status:
        if status not in VALID_DRAFT_STATUSES:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid draft status")
        query = query.filter(PostDraft.status == status)
    drafts = query.order_by(PostDraft.created_at.desc()).all()
    return drafts


@router.get("/drafts/{draft_id}", response_model=DraftOut)
def get_draft(
    draft_id: int,
    x_service_token: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    if not _check_service_token(x_service_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid service token")
    draft = db.query(PostDraft).filter(PostDraft.id == draft_id).first()
    if not draft:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found")
    return draft


@router.patch("/drafts/{draft_id}", response_model=DraftOut)
def update_draft(
    draft_id: int,
    payload: DraftUpdate,
    x_service_token: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    if not _check_service_token(x_service_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid service token")
    draft = db.query(PostDraft).filter(PostDraft.id == draft_id).first()
    if not draft:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found")
    update_data = payload.dict(exclude_unset=True)
    if update_data.get("status") == "published" and draft.topic_id is None:
        topic = db.query(Topic).filter(Topic.name == draft.topic_name.strip()).first()
        if not topic:
            topic = Topic(name=draft.topic_name.strip(), language=draft.language.strip())
            db.add(topic)
            db.flush()
        update_data["topic_id"] = topic.id
    for key, value in update_data.items():
        setattr(draft, key, value)
    db.commit()
    db.refresh(draft)
    return draft


@router.delete("/drafts/{draft_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_draft(
    draft_id: int,
    x_service_token: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    if not _check_service_token(x_service_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid service token")
    draft = db.query(PostDraft).filter(PostDraft.id == draft_id).first()
    if not draft:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found")
    db.delete(draft)
    db.commit()
