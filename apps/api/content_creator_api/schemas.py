"""Request/response schemas. Decoupled from ORM models so we can evolve them independently."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from content_creator_api.models import (
    ClipStatus,
    ExportStatus,
    GenerationJobStatus,
    NarrationStatus,
    ProjectStatus,
    TimelineItemType,
    VoiceStatus,
)


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


# --- Phase 2: Storyboard / Shots / Timeline / Exports -----------------


class StoryboardCreate(BaseModel):
    """Ask the LLM to break a project's prompt into N ordered shots."""

    prompt: str | None = Field(
        default=None,
        description="If omitted, the project's prompt is used.",
        max_length=4000,
    )
    n_shots: int = Field(default=5, ge=1, le=20)
    total_duration_seconds: int = Field(default=30, ge=5, le=180)
    aspect_ratio: str = Field(default="9:16", max_length=16)


class ShotCreate(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)
    duration_seconds: int = Field(default=5, ge=1, le=30)
    aspect_ratio: str = Field(default="9:16", max_length=16)
    notes: str | None = Field(default=None, max_length=2000)
    order_index: int | None = Field(default=None, ge=0)


class ShotUpdate(BaseModel):
    prompt: str | None = Field(default=None, max_length=4000)
    duration_seconds: int | None = Field(default=None, ge=1, le=30)
    aspect_ratio: str | None = Field(default=None, max_length=16)
    notes: str | None = Field(default=None, max_length=2000)
    order_index: int | None = Field(default=None, ge=0)
    selected_clip_id: UUID | None = None


class ShotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    order_index: int
    prompt: str
    duration_seconds: int
    aspect_ratio: str
    notes: str | None
    generation_job_id: UUID | None
    selected_clip_id: UUID | None
    created_at: datetime
    updated_at: datetime


class TimelineItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    order_index: int
    item_type: TimelineItemType
    clip_id: UUID | None
    source_start_ms: int
    duration_ms: int
    transition_in: str | None
    transition_out: str | None
    text_overlay: str | None
    audio_storage_key: str | None
    volume: float
    created_at: datetime
    updated_at: datetime


class TimelineItemWrite(BaseModel):
    """Used in PUT /timeline. ``id`` is preserved if present, else new row."""

    id: UUID | None = None
    item_type: TimelineItemType = TimelineItemType.CLIP
    clip_id: UUID | None = None
    source_start_ms: int = Field(default=0, ge=0)
    duration_ms: int = Field(default=5000, ge=100)
    transition_in: str | None = Field(default=None, max_length=64)
    transition_out: str | None = Field(default=None, max_length=64)
    text_overlay: str | None = Field(default=None, max_length=500)
    audio_storage_key: str | None = Field(default=None, max_length=512)
    volume: float = Field(default=1.0, ge=0.0, le=2.0)


class TimelinePut(BaseModel):
    items: list[TimelineItemWrite] = Field(default_factory=list)


class ExportCreate(BaseModel):
    width: int = Field(default=1080, ge=64, le=3840)
    height: int = Field(default=1920, ge=64, le=3840)
    fps: int = Field(default=30, ge=1, le=120)


class ExportRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    status: ExportStatus
    width: int
    height: int
    fps: int
    storage_key: str | None
    public_url: str | None
    duration_ms: int | None
    error: str | None
    created_at: datetime
    updated_at: datetime


# --- Phase 3: Voices / Narrations / Captions --------------------------


class VoiceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    reference_text: str | None = Field(default=None, max_length=2000)


class VoiceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    provider: str
    sample_storage_key: str | None
    sample_public_url: str | None
    provider_voice_id: str | None
    reference_text: str | None
    status: VoiceStatus
    error: str | None
    created_at: datetime
    updated_at: datetime


class NarrationCreate(BaseModel):
    voice_id: UUID
    script: str = Field(min_length=1, max_length=20000)


class CaptionSegmentRead(BaseModel):
    start_ms: int
    end_ms: int
    text: str


class NarrationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    voice_id: UUID | None
    script: str
    status: NarrationStatus
    storage_key: str | None
    public_url: str | None
    duration_ms: int | None
    captions_json: str | None
    error: str | None
    created_at: datetime
    updated_at: datetime
