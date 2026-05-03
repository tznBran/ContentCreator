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


class TimelineItemType(StrEnum):
    """Discriminator for items on the project timeline.

    Phase 2 only emits ``CLIP``; Phase 3 will add ``AUDIO`` (narration / BGM)
    and ``TEXT`` (caption overlays).
    """

    CLIP = "clip"
    AUDIO = "audio"
    TEXT = "text"


class ExportStatus(StrEnum):
    PENDING = "pending"
    RENDERING = "rendering"
    UPLOADING = "uploading"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class VoiceStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"


class NarrationStatus(StrEnum):
    PENDING = "pending"
    SYNTHESIZING = "synthesizing"
    UPLOADING = "uploading"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class SocialPlatform(StrEnum):
    YOUTUBE = "youtube"
    TIKTOK = "tiktok"
    INSTAGRAM = "instagram"


class PublishVisibility(StrEnum):
    PRIVATE = "private"
    UNLISTED = "unlisted"
    PUBLIC = "public"


class PublishStatus(StrEnum):
    PENDING = "pending"
    UPLOADING = "uploading"
    PROCESSING = "processing"
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


class Shot(SQLModel, table=True):
    """One ordered shot in a project's storyboard.

    Each shot is its own prompt + duration + (eventually) a chosen winning
    clip from a Phase 1 GenerationJob. Shots are ordered by ``order_index``.
    """

    __tablename__ = "shots"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    project_id: UUID = Field(foreign_key="projects.id", index=True, nullable=False)
    order_index: int = Field(default=0, ge=0, index=True)
    prompt: str = Field(max_length=4000)
    duration_seconds: int = Field(default=5, ge=1, le=30)
    aspect_ratio: str = Field(default="9:16", max_length=16)
    notes: str | None = Field(default=None, max_length=2000)
    generation_job_id: UUID | None = Field(
        default=None, foreign_key="generation_jobs.id"
    )
    selected_clip_id: UUID | None = Field(default=None, foreign_key="clips.id")
    created_at: datetime = Field(default_factory=_utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=_utcnow, nullable=False)


class TimelineItem(SQLModel, table=True):
    """A single item on the project timeline.

    For now (Phase 2), only ``item_type=CLIP`` is rendered. The fields are
    sized so that Phase 3 (audio overlays, captions) and Phase 4 don't
    require schema changes.
    """

    __tablename__ = "timeline_items"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    project_id: UUID = Field(foreign_key="projects.id", index=True, nullable=False)
    order_index: int = Field(default=0, ge=0, index=True)
    item_type: TimelineItemType = Field(default=TimelineItemType.CLIP)
    clip_id: UUID | None = Field(default=None, foreign_key="clips.id")
    # Trim within the source clip (in milliseconds).
    source_start_ms: int = Field(default=0, ge=0)
    duration_ms: int = Field(default=5000, ge=100)
    # Reserved fields for transitions / overlays.
    transition_in: str | None = Field(default=None, max_length=64)
    transition_out: str | None = Field(default=None, max_length=64)
    text_overlay: str | None = Field(default=None, max_length=500)
    # Generic key for future audio overlays (Phase 3).
    audio_storage_key: str | None = Field(default=None, max_length=512)
    volume: float = Field(default=1.0, ge=0.0, le=2.0)
    created_at: datetime = Field(default_factory=_utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=_utcnow, nullable=False)


class ExportJob(SQLModel, table=True):
    """A render of the project timeline to a single mp4 file."""

    __tablename__ = "export_jobs"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    project_id: UUID = Field(foreign_key="projects.id", index=True, nullable=False)
    status: ExportStatus = Field(default=ExportStatus.PENDING, index=True)
    width: int = Field(default=1080, ge=64)
    height: int = Field(default=1920, ge=64)
    fps: int = Field(default=30, ge=1, le=120)
    storage_key: str | None = Field(default=None, max_length=512)
    public_url: str | None = Field(default=None, max_length=2000)
    duration_ms: int | None = Field(default=None)
    error: str | None = Field(default=None, max_length=2000)
    created_at: datetime = Field(default_factory=_utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=_utcnow, nullable=False)


class VoiceProfile(SQLModel, table=True):
    """A user's cloned voice (via F5-TTS / ElevenLabs / Replicate)."""

    __tablename__ = "voice_profiles"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str = Field(max_length=200)
    provider: str = Field(default="f5tts", max_length=64)
    # Where the user's recorded sample lives (in our bucket).
    sample_storage_key: str | None = Field(default=None, max_length=512)
    sample_public_url: str | None = Field(default=None, max_length=2000)
    # ID returned by the upstream provider once the voice is registered.
    provider_voice_id: str | None = Field(default=None, max_length=200)
    # Optional reference transcript of the sample (improves clone quality
    # for F5-TTS).
    reference_text: str | None = Field(default=None, max_length=2000)
    status: VoiceStatus = Field(default=VoiceStatus.PENDING, index=True)
    error: str | None = Field(default=None, max_length=2000)
    created_at: datetime = Field(default_factory=_utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=_utcnow, nullable=False)


class NarrationJob(SQLModel, table=True):
    """A request to synthesize a script with a given voice."""

    __tablename__ = "narration_jobs"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    project_id: UUID = Field(foreign_key="projects.id", index=True, nullable=False)
    voice_id: UUID | None = Field(
        default=None, foreign_key="voice_profiles.id", index=True
    )
    script: str = Field(max_length=20000)
    status: NarrationStatus = Field(default=NarrationStatus.PENDING, index=True)
    storage_key: str | None = Field(default=None, max_length=512)
    public_url: str | None = Field(default=None, max_length=2000)
    duration_ms: int | None = Field(default=None)
    # JSON-encoded list of {"start_ms": int, "end_ms": int, "text": str}.
    # Stored as a string so this works on both Postgres and SQLite without
    # requiring sqlmodel JSON support.
    captions_json: str | None = Field(default=None, max_length=200000)
    error: str | None = Field(default=None, max_length=2000)
    created_at: datetime = Field(default_factory=_utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=_utcnow, nullable=False)


class SocialAccount(SQLModel, table=True):
    """A connected social media account (YouTube/TikTok/Instagram).

    Tokens are stored verbatim in this single-user prototype. When we
    move to multi-user we'll encrypt at-rest with a per-user data key.
    """

    __tablename__ = "social_accounts"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    platform: SocialPlatform = Field(index=True)
    # Display info from the provider (e.g. channel title, IG handle).
    account_name: str = Field(max_length=200)
    external_id: str = Field(max_length=200, index=True)
    access_token: str = Field(max_length=4000)
    refresh_token: str | None = Field(default=None, max_length=4000)
    expires_at: datetime | None = Field(default=None)
    scope: str | None = Field(default=None, max_length=2000)
    # JSON blob of any extra provider-specific identifiers we need
    # later (e.g. IG ``ig_user_id``, FB page ID, YouTube channel ID).
    extra_json: str | None = Field(default=None, max_length=4000)
    created_at: datetime = Field(default_factory=_utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=_utcnow, nullable=False)


class PublishJob(SQLModel, table=True):
    """One platform upload of a final exported mp4."""

    __tablename__ = "publish_jobs"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    project_id: UUID = Field(foreign_key="projects.id", index=True, nullable=False)
    export_id: UUID = Field(foreign_key="export_jobs.id", index=True, nullable=False)
    account_id: UUID = Field(
        foreign_key="social_accounts.id", index=True, nullable=False
    )
    platform: SocialPlatform = Field(index=True)
    title: str = Field(max_length=200)
    description: str = Field(default="", max_length=5000)
    visibility: PublishVisibility = Field(default=PublishVisibility.PRIVATE)
    status: PublishStatus = Field(default=PublishStatus.PENDING, index=True)
    platform_media_id: str | None = Field(default=None, max_length=200)
    platform_url: str | None = Field(default=None, max_length=2000)
    error: str | None = Field(default=None, max_length=2000)
    created_at: datetime = Field(default_factory=_utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=_utcnow, nullable=False)
