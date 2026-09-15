from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from .db import Base


CONTENT_STATUSES = (
    "draft",
    "review",
    "approved",
    "scheduled",
    "publishing",
    "published",
    "failed",
    "archived",
)


class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False)


class Workspace(Base):
    __tablename__ = 'workspaces'
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    slug = Column(String, unique=True, index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    channels = relationship('Channel', back_populates='workspace', cascade='all, delete-orphan')
    contents = relationship('Content', back_populates='workspace', cascade='all, delete-orphan')


class Channel(Base):
    __tablename__ = 'channels'
    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey('workspaces.id', ondelete='CASCADE'), nullable=False, index=True)
    platform = Column(String, nullable=False)
    external_id = Column(String, nullable=False)
    name = Column(String, nullable=True)
    timezone = Column(String, nullable=False, default='UTC')
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    __table_args__ = (UniqueConstraint('platform', 'external_id', name='uq_channels_platform_external_id'),)
    workspace = relationship('Workspace', back_populates='channels')
    publications = relationship('Publication', back_populates='channel')


class Topic(Base):
    __tablename__ = 'topics'
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)
    language = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Prompt(Base):
    __tablename__ = 'prompts'
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)
    language = Column(String, nullable=False)
    text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class AssistantMessageTemplate(Base):
    __tablename__ = 'assistant_message_templates'
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)
    language = Column(String, nullable=False)
    text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class PublicationSchedule(Base):
    __tablename__ = 'publication_schedules'
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    chat_id = Column(String, nullable=False)
    chat_name = Column(String, nullable=True)
    language = Column(String, nullable=False)
    assistant_message = Column(Text, nullable=False)
    prompt_id = Column(Integer, ForeignKey('prompts.id'), nullable=True)
    assistant_template_id = Column(Integer, ForeignKey('assistant_message_templates.id'), nullable=True)
    timezone = Column(String, nullable=False, default='UTC')
    schedule_type = Column(String, nullable=False)
    schedule_value = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    last_run = Column(DateTime, nullable=True)
    force_run_requested_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    prompt = relationship('Prompt', foreign_keys=[prompt_id])
    assistant_template = relationship('AssistantMessageTemplate', foreign_keys=[assistant_template_id])


class Content(Base):
    __tablename__ = 'contents'
    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey('workspaces.id', ondelete='CASCADE'), nullable=False, index=True)
    title = Column(String, nullable=True)
    body = Column(Text, nullable=False)
    language = Column(String, nullable=False)
    status = Column(String, nullable=False, default='draft', index=True)
    created_by = Column(Integer, ForeignKey('users.id'), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    workspace = relationship('Workspace', back_populates='contents')
    author = relationship('User')
    versions = relationship('ContentVersion', back_populates='content', cascade='all, delete-orphan', order_by='ContentVersion.version')
    publications = relationship('Publication', back_populates='content', cascade='all, delete-orphan')


class ContentVersion(Base):
    __tablename__ = 'content_versions'
    id = Column(Integer, primary_key=True, index=True)
    content_id = Column(Integer, ForeignKey('contents.id', ondelete='CASCADE'), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    body = Column(Text, nullable=False)
    source = Column(String, nullable=False, default='human')
    created_by = Column(Integer, ForeignKey('users.id'), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    __table_args__ = (UniqueConstraint('content_id', 'version', name='uq_content_versions_content_version'),)
    content = relationship('Content', back_populates='versions')
    author = relationship('User')


class Publication(Base):
    __tablename__ = 'publications'
    id = Column(Integer, primary_key=True, index=True)
    content_id = Column(Integer, ForeignKey('contents.id', ondelete='CASCADE'), nullable=False, index=True)
    channel_id = Column(Integer, ForeignKey('channels.id', ondelete='CASCADE'), nullable=False, index=True)
    source_draft_id = Column(Integer, ForeignKey('post_drafts.id', ondelete='SET NULL'), nullable=True, index=True)
    status = Column(String, nullable=False, default='scheduled', index=True)
    scheduled_at = Column(DateTime, nullable=True, index=True)
    published_at = Column(DateTime, nullable=True)
    processing_started_at = Column(DateTime, nullable=True)
    next_attempt_at = Column(DateTime, nullable=True, index=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    worker_id = Column(String, nullable=True)
    external_id = Column(String, nullable=True)
    idempotency_key = Column(String, unique=True, nullable=False)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    content = relationship('Content', back_populates='publications')
    channel = relationship('Channel', back_populates='publications')
    source_draft = relationship('PostDraft')


class AuditLog(Base):
    __tablename__ = 'audit_logs'
    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey('workspaces.id', ondelete='SET NULL'), nullable=True, index=True)
    actor_user_id = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    entity_type = Column(String, nullable=False)
    entity_id = Column(Integer, nullable=True)
    action = Column(String, nullable=False)
    metadata_json = Column('metadata', JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


class PostDraft(Base):
    __tablename__ = 'post_drafts'
    id = Column(Integer, primary_key=True, index=True)
    schedule_id = Column(Integer, ForeignKey('publication_schedules.id'), nullable=False)
    topic_id = Column(Integer, ForeignKey('topics.id'), nullable=True)
    topic_name = Column(String, nullable=False)
    language = Column(String, nullable=False)
    generated_text = Column(Text, nullable=False)
    status = Column(String, nullable=False, default='pending', index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    topic = relationship('Topic')
    schedule = relationship('PublicationSchedule')
