"""Database engine and session factory."""

from __future__ import annotations

from collections.abc import Generator

from sqlmodel import Session, SQLModel, create_engine

from content_creator_api.config import get_settings

_settings = get_settings()

engine = create_engine(
    _settings.database_url,
    echo=False,
    pool_pre_ping=True,
)


def init_db() -> None:
    """Create tables from SQLModel metadata.

    For migrations use Alembic; this helper is only used in tests and for the
    very first bootstrap.
    """
    SQLModel.metadata.create_all(engine)


def get_session() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a SQLModel session."""
    with Session(engine) as session:
        yield session
