import os
from datetime import datetime, date, timedelta, time
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field, validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.app.db import get_db
from src.app.models import PublicationSchedule, Topic, PostDraft

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


class ScheduleBase(BaseModel):
    name: str = Field(..., min_length=1)
    chat_id: str = Field(..., min_length=1)
    chat_name: Optional[str] = None
    language: str = Field(..., min_length=2)
    assistant_message: str = Field(..., min_length=1)
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
    name: Optional[str]
    chat_id: Optional[str]
    chat_name: Optional[str]
    language: Optional[str]
    assistant_message: Optional[str]
    schedule_type: Optional[str]
    schedule_value: Optional[str]
    is_active: Optional[bool]
    last_run: Optional[datetime]

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

    class Config:
        orm_mode = True


class DraftBase(BaseModel):
    schedule_id: int
    topic_id: int
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
    status: Optional[str]
    generated_text: Optional[str]

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
        today = date.today()
        scheduled = datetime.combine(today, run_time)
        if schedule.last_run is None or schedule.last_run.date() < today:
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
        schedule_type=schedule.schedule_type,
        schedule_value=schedule.schedule_value,
        is_active=schedule.is_active,
        last_run=schedule.last_run,
        created_at=schedule.created_at,
        next_run=compute_next_run(schedule),
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
    db.commit()


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
    schedule = PublicationSchedule(
        name=payload.name.strip(),
        chat_id=payload.chat_id.strip(),
        chat_name=payload.chat_name.strip() if payload.chat_name else None,
        language=payload.language.strip(),
        assistant_message=payload.assistant_message.strip(),
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
    for key, value in update_data.items():
        setattr(draft, key, value)
    db.commit()
    db.refresh(draft)
    return draft
