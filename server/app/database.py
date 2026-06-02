import os
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlmodel import SQLModel, create_engine, Session

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./telex.db")
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})


def create_db():
    SQLModel.metadata.create_all(engine)
    _migrate()
    _cleanup_old_failures()


def _migrate():
    """Idempotent column additions for schema upgrades."""
    stmts = [
        "ALTER TABLE client ADD COLUMN device_password_hash TEXT",
        "ALTER TABLE client ADD COLUMN send_password_hash TEXT",
        "ALTER TABLE client ADD COLUMN send_locked INTEGER DEFAULT 0",
        "ALTER TABLE client ADD COLUMN send_locked_at TEXT",
    ]
    with engine.connect() as conn:
        for stmt in stmts:
            try:
                conn.execute(text(stmt))
                conn.commit()
            except Exception:
                pass  # Column already exists


def _cleanup_old_failures():
    """Delete failed attempts older than 7 days to keep the DB lean."""
    cutoff = datetime.utcnow() - timedelta(days=7)
    with engine.connect() as conn:
        conn.execute(
            text("DELETE FROM failedattempt WHERE attempted_at < :cutoff"),
            {"cutoff": cutoff.isoformat()},
        )
        conn.commit()


def get_session():
    with Session(engine) as session:
        yield session
