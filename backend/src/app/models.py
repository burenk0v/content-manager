from datetime import datetime

from sqlalchemy import Column, Integer, String, Boolean, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship

from .db import Base


class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False)


class Topic(Base):
    __tablename__ = 'topics'
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)
    language = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class PublicationSchedule(Base):
    __tablename__ = 'publication_schedules'
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    chat_id = Column(String, nullable=False)
    chat_name = Column(String, nullable=True)
    language = Column(String, nullable=False)
    assistant_message = Column(Text, nullable=False)
    schedule_type = Column(String, nullable=False)
    schedule_value = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    last_run = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class PostDraft(Base):
    __tablename__ = 'post_drafts'
    id = Column(Integer, primary_key=True, index=True)
    schedule_id = Column(Integer, ForeignKey('publication_schedules.id'), nullable=False)
    topic_id = Column(Integer, ForeignKey('topics.id'), nullable=False)
    topic_name = Column(String, nullable=False)
    language = Column(String, nullable=False)
    generated_text = Column(Text, nullable=False)
    status = Column(String, nullable=False, default='pending', index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    topic = relationship('Topic')
    schedule = relationship('PublicationSchedule')
