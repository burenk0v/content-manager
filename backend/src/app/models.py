from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from .db import Base


CONTENT_STATUSES = (
    "draft", "review", "approved", "scheduled", "publishing", "published", "failed", "archived",
)


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    is_admin = Column(Boolean, default=False, nullable=False)


class Workspace(Base):
    __tablename__ = "workspaces"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    slug = Column(String, unique=True, index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    channels = relationship("Channel", back_populates="workspace", cascade="all, delete-orphan")
    contents = relationship("Content", back_populates="workspace", cascade="all, delete-orphan")


class Channel(Base):
    __tablename__ = "channels"
    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    platform = Column(String, nullable=False)
    external_id = Column(String, nullable=False)
    name = Column(String, nullable=True)
    timezone = Column(String, nullable=False, default="UTC")
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    __table_args__ = (UniqueConstraint("platform", "external_id", name="uq_channels_platform_external_id"),)
    workspace = relationship("Workspace", back_populates="channels")
    publications = relationship("Publication", back_populates="channel")


class Content(Base):
    __tablename__ = "contents"
    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String, nullable=True)
    language = Column(String, nullable=False)
    status = Column(String, nullable=False, default="draft", index=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    workspace = relationship("Workspace", back_populates="contents")
    author = relationship("User")
    versions = relationship("ContentVersion", back_populates="content", cascade="all, delete-orphan", order_by="ContentVersion.version")
    publications = relationship("Publication", back_populates="content", cascade="all, delete-orphan")

    @property
    def body(self) -> str:
        if not self.versions:
            raise ValueError(f"Content {self.id} has no versions")
        return self.versions[-1].body


class ContentVersion(Base):
    __tablename__ = "content_versions"
    id = Column(Integer, primary_key=True, index=True)
    content_id = Column(Integer, ForeignKey("contents.id", ondelete="CASCADE"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    body = Column(Text, nullable=False)
    source = Column(String, nullable=False, default="human")
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    __table_args__ = (UniqueConstraint("content_id", "version", name="uq_content_versions_content_version"),)
    content = relationship("Content", back_populates="versions")
    author = relationship("User")


class Publication(Base):
    __tablename__ = "publications"
    id = Column(Integer, primary_key=True, index=True)
    content_id = Column(Integer, ForeignKey("contents.id", ondelete="CASCADE"), nullable=False, index=True)
    channel_id = Column(Integer, ForeignKey("channels.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String, nullable=False, default="scheduled", index=True)
    scheduled_at = Column(DateTime, nullable=True, index=True)
    published_at = Column(DateTime, nullable=True)
    processing_started_at = Column(DateTime, nullable=True)
    processing_token = Column(String, nullable=True, index=True)
    lease_heartbeat_at = Column(DateTime, nullable=True, index=True)
    next_attempt_at = Column(DateTime, nullable=True, index=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    worker_id = Column(String, nullable=True)
    external_id = Column(String, nullable=True)
    idempotency_key = Column(String, unique=True, nullable=False)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    __table_args__ = (Index("uq_publications_content_channel", "content_id", "channel_id", unique=True),)
    content = relationship("Content", back_populates="publications")
    channel = relationship("Channel", back_populates="publications")
    provider_operation = relationship("PublicationOperation", back_populates="publication", uselist=False, cascade="all, delete-orphan")


class PublicationOperation(Base):
    __tablename__ = "publication_operations"
    id = Column(Integer, primary_key=True, index=True)
    publication_id = Column(Integer, ForeignKey("publications.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    provider = Column(String, nullable=False)
    operation_key = Column(String, nullable=False, unique=True, index=True)
    status = Column(String, nullable=False, default="pending", index=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    external_id = Column(String, nullable=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    publication = relationship("Publication", back_populates="provider_operation")


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True)
    actor_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    entity_type = Column(String, nullable=False)
    entity_id = Column(Integer, nullable=True)
    action = Column(String, nullable=False)
    metadata_json = Column("metadata", JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
