"""Database models.

Phase 0 keeps this minimal: a single ``Project`` record represents a video
the user is working on. Later phases will add ``Shot``, ``Clip``,
``RenderJob``, ``Voice``, ``SocialAccount``, etc.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ProjectStatus(StrEnum):
    DRAFT = "draft"
    GENERATING = "generating"
    READY = "ready"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class Project(SQLModel, table=True):
    """A user-facing video project."""

    __tablename__ = "projects"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    title: str = Field(index=True, max_length=200)
    prompt: str = Field(default="", max_length=4000)
    status: ProjectStatus = Field(default=ProjectStatus.DRAFT, index=True)
    created_at: datetime = Field(default_factory=_utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=_utcnow, nullable=False)
