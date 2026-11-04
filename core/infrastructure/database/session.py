"""
Database engine and session management.
Supports SQLite (for local embedded development) and PostgreSQL (for commercial deployment).
"""

import os
from contextlib import contextmanager
from typing import Any, Dict, Generator, Optional

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from core.infrastructure.database.models import Base


class DatabaseEngine:
    """Manages SQLAlchemy engine and session factories."""

    def __init__(self, database_url: Optional[str] = None) -> None:
        if not database_url:
            env_url = os.environ.get("DATABASE_URL")
            if env_url:
                database_url = env_url
            else:
                db_dir = os.path.join(os.getcwd(), "data")
                os.makedirs(db_dir, exist_ok=True)
                database_url = f"sqlite:///{os.path.join(db_dir, 'folioshield.db')}"

        self.database_url = database_url

        engine_kwargs: Dict[str, Any] = {}
        if database_url.startswith("sqlite"):
            engine_kwargs["connect_args"] = {"check_same_thread": False}
        else:
            engine_kwargs["pool_size"] = int(os.environ.get("DB_POOL_SIZE", "10"))
            engine_kwargs["max_overflow"] = int(os.environ.get("DB_MAX_OVERFLOW", "20"))
            engine_kwargs["pool_pre_ping"] = True

        self.engine: Engine = create_engine(self.database_url, **engine_kwargs)
        self.session_factory = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=self.engine,
        )

    def create_all(self) -> None:
        """Creates all tables defined in models."""
        Base.metadata.create_all(bind=self.engine)

    def drop_all(self) -> None:
        """Drops all tables."""
        Base.metadata.drop_all(bind=self.engine)

    def session(self) -> Session:
        """Returns a new SQLAlchemy Session."""
        return self.session_factory()

    def close(self) -> None:
        """Disposes the engine connection pool."""
        self.engine.dispose()


_DEFAULT_DB_ENGINE: Optional[DatabaseEngine] = None


def get_default_engine() -> DatabaseEngine:
    global _DEFAULT_DB_ENGINE
    if _DEFAULT_DB_ENGINE is None:
        _DEFAULT_DB_ENGINE = DatabaseEngine()
    return _DEFAULT_DB_ENGINE


@contextmanager
def get_db_session(engine: Optional[DatabaseEngine] = None) -> Generator[Session, None, None]:
    """Context manager for scoped database sessions."""
    eng = engine or get_default_engine()
    session = eng.session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
