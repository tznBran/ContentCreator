"""Database models.

Projects own GenerationJobs, which own Clips. Later phases add Shot,
Voice, SocialAccount, etc.
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


class GenerationJobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ClipStatus(StrEnum):
    PENDING = "pending"
    GENERATING = "generating"
    DOWNLOADING = "downloading"
    SCORING = "scoring"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class Project(SQLModel, table=True):
    """A user-facing video project."""

    __tablename__ = "projects"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    title: str = Field(index=True, max_length=200)
    prompt: str = Field(default="", max_length=4000)
    status: ProjectStatus = Field(default=ProjectStatus.DRAFT, index=True)
    created_at: datetime = Field(default_factory=_utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=_utcnow, nullable=False)


class GenerationJob(SQLModel, table=True):
    """A request to generate N clip variants for a project."""

    __tablename__ = "generation_jobs"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    project_id: UUID = Field(foreign_key="projects.id", index=True, nullable=False)
    prompt: str = Field(max_length=4000)
    n_variants: int = Field(default=3, ge=1, le=8)
    aspect_ratio: str = Field(default="9:16", max_length=16)
    duration_seconds: int = Field(default=5, ge=1, le=30)
    model: str = Field(default="bytedance/seedance-2.0", max_length=200)
    status: GenerationJobStatus = Field(default=GenerationJobStatus.PENDING, index=True)
    best_clip_id: UUID | None = Field(default=None, foreign_key="clips.id")
    error: str | None = Field(default=None, max_length=2000)
    created_at: datetime = Field(default_factory=_utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=_utcnow, nullable=False)


class Clip(SQLModel, table=True):
    """One generated video clip variant."""

    __tablename__ = "clips"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    project_id: UUID = Field(foreign_key="projects.id", index=True, nullable=False)
    generation_job_id: UUID | None = Field(
        default=None, foreign_key="generation_jobs.id", index=True
    )
    variant_index: int = Field(default=0, ge=0, le=63)
    prompt: str = Field(max_length=4000)
    status: ClipStatus = Field(default=ClipStatus.PENDING, index=True)
    provider_job_id: str | None = Field(default=None, max_length=200)
    polling_url: str | None = Field(default=None, max_length=2000)
    source_url: str | None = Field(default=None, max_length=2000)
    storage_key: str | None = Field(default=None, max_length=512)
    public_url: str | None = Field(default=None, max_length=2000)
    duration_seconds: float | None = Field(default=None)
    score: float | None = Field(default=None)
    score_explanation: str | None = Field(default=None, max_length=2000)
    cost_usd: float | None = Field(default=None)
    error: str | None = Field(default=None, max_length=2000)
    created_at: datetime = Field(default_factory=_utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=_utcnow, nullable=False)
