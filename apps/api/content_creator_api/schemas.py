"""Request/response schemas. Decoupled from ORM models so we can evolve them independently."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from content_creator_api.models import ClipStatus, GenerationJobStatus, ProjectStatus


class ProjectCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    prompt: str = Field(default="", max_length=4000)


class ProjectUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    prompt: str | None = Field(default=None, max_length=4000)
    status: ProjectStatus | None = None


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    prompt: str
    status: ProjectStatus
    created_at: datetime
    updated_at: datetime


class HealthResponse(BaseModel):
    status: str
    version: str


class GenerationCreate(BaseModel):
    """Request body to spawn N clip variants for a project."""

    prompt: str = Field(min_length=1, max_length=4000)
    n_variants: int = Field(default=3, ge=1, le=8)
    aspect_ratio: str = Field(default="9:16", max_length=16)
    duration_seconds: int = Field(default=5, ge=1, le=30)
    model: str | None = Field(default=None, max_length=200)


class ClipRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    generation_job_id: UUID | None
    variant_index: int
    prompt: str
    status: ClipStatus
    storage_key: str | None
    public_url: str | None
    duration_seconds: float | None
    score: float | None
    score_explanation: str | None
    cost_usd: float | None
    error: str | None
    created_at: datetime
    updated_at: datetime


class GenerationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    prompt: str
    n_variants: int
    aspect_ratio: str
    duration_seconds: int
    model: str
    status: GenerationJobStatus
    best_clip_id: UUID | None
    error: str | None
    created_at: datetime
    updated_at: datetime


class GenerationDetail(GenerationRead):
    clips: list[ClipRead] = Field(default_factory=list)


class WinnerSelect(BaseModel):
    clip_id: UUID
