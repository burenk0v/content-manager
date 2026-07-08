import os
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./backend_db.sqlite3")

connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def ensure_schema():
    inspector = inspect(engine)

    if "prompts" not in inspector.get_table_names() or "assistant_message_templates" not in inspector.get_table_names():
        Base.metadata.create_all(bind=engine)
        inspector = inspect(engine)

    if "publication_schedules" in inspector.get_table_names():
        column_names = {column["name"] for column in inspector.get_columns("publication_schedules")}
        if "prompt_id" not in column_names:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE publication_schedules ADD COLUMN prompt_id INTEGER"))
        if "assistant_template_id" not in column_names:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE publication_schedules ADD COLUMN assistant_template_id INTEGER"))
        if "timezone" not in column_names:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE publication_schedules ADD COLUMN timezone VARCHAR NOT NULL DEFAULT 'UTC'"))

    if engine.dialect.name == "postgresql" and "post_drafts" in inspector.get_table_names():
        draft_columns = {column["name"]: column for column in inspector.get_columns("post_drafts")}
        topic_id_column = draft_columns.get("topic_id")
        if topic_id_column and topic_id_column.get("nullable") is False:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE post_drafts ALTER COLUMN topic_id DROP NOT NULL"))

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_db_connection():
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
    finally:
        db.close()
