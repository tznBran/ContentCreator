"""Voice cloning + narration synthesis endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from sqlmodel import Session, col, select

from content_creator_api.config import get_settings
from content_creator_api.db import get_session
from content_creator_api.models import (
    NarrationJob,
    NarrationStatus,
    Project,
    VoiceProfile,
    VoiceStatus,
)
from content_creator_api.schemas import (
    NarrationCreate,
    NarrationRead,
    VoiceRead,
)
from content_creator_api.services import storage
from content_creator_api.services.queue import get_queue
from content_creator_api.tasks.narration import (
    register_voice_profile,
    synthesize_narration_job,
)

router = APIRouter(tags=["voices"])


def _now() -> datetime:
    return datetime.now(UTC)


@router.get("/voices", response_model=list[VoiceRead])
def list_voices(session: Session = Depends(get_session)) -> list[VoiceProfile]:
    rows = session.exec(
        select(VoiceProfile).order_by(col(VoiceProfile.created_at).desc())
    ).all()
    return list(rows)


@router.post(
    "/voices",
    response_model=VoiceRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_voice(
    name: str = Form(...),
    reference_text: str | None = Form(default=None),
    audio: UploadFile = File(...),
    session: Session = Depends(get_session),
) -> VoiceProfile:
    """Upload a voice sample and kick off provider registration."""
    settings = get_settings()
    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="empty audio upload")

    voice = VoiceProfile(
        name=name.strip() or "Voice",
        provider=settings.tts_provider,
        reference_text=reference_text,
        status=VoiceStatus.PENDING,
    )
    voice.id = voice.id or uuid4()  # ensure id exists for storage key

    key = f"voices/{voice.id}/sample.wav"
    if settings.s3_endpoint_url:
        storage.put_bytes(
            key,
            audio_bytes,
            content_type=audio.content_type or "audio/wav",
        )
    voice.sample_storage_key = key
    voice.sample_public_url = storage.public_url(key)

    session.add(voice)
    session.commit()
    session.refresh(voice)

    if settings.enqueue_jobs:
        get_queue().enqueue(
            register_voice_profile,
            str(voice.id),
            job_timeout=600,
            result_ttl=3600,
        )

    return voice


@router.get("/voices/{voice_id}", response_model=VoiceRead)
def get_voice(
    voice_id: UUID, session: Session = Depends(get_session)
) -> VoiceProfile:
    voice = session.get(VoiceProfile, voice_id)
    if voice is None:
        raise HTTPException(status_code=404, detail="voice not found")
    return voice


@router.delete("/voices/{voice_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_voice(voice_id: UUID, session: Session = Depends(get_session)) -> None:
    voice = session.get(VoiceProfile, voice_id)
    if voice is None:
        raise HTTPException(status_code=404, detail="voice not found")
    session.delete(voice)
    session.commit()


# --- Narrations -------------------------------------------------------


@router.post(
    "/projects/{project_id}/narrations",
    response_model=NarrationRead,
    status_code=status.HTTP_201_CREATED,
)
def create_narration(
    project_id: UUID,
    payload: NarrationCreate,
    session: Session = Depends(get_session),
) -> NarrationJob:
    if session.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")
    voice = session.get(VoiceProfile, payload.voice_id)
    if voice is None:
        raise HTTPException(status_code=404, detail="voice not found")
    if voice.status != VoiceStatus.READY:
        raise HTTPException(
            status_code=409,
            detail=f"voice not ready (status={voice.status})",
        )

    narration = NarrationJob(
        project_id=project_id,
        voice_id=voice.id,
        script=payload.script,
        status=NarrationStatus.PENDING,
    )
    session.add(narration)
    session.commit()
    session.refresh(narration)

    if get_settings().enqueue_jobs:
        get_queue().enqueue(
            synthesize_narration_job,
            str(narration.id),
            job_timeout=1800,
            result_ttl=3600,
        )

    return narration


@router.get(
    "/projects/{project_id}/narrations", response_model=list[NarrationRead]
)
def list_narrations(
    project_id: UUID, session: Session = Depends(get_session)
) -> list[NarrationJob]:
    if session.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")
    rows = session.exec(
        select(NarrationJob)
        .where(NarrationJob.project_id == project_id)
        .order_by(col(NarrationJob.created_at).desc())
    ).all()
    return list(rows)


@router.get("/narrations/{narration_id}", response_model=NarrationRead)
def get_narration(
    narration_id: UUID, session: Session = Depends(get_session)
) -> NarrationJob:
    narration = session.get(NarrationJob, narration_id)
    if narration is None:
        raise HTTPException(status_code=404, detail="narration not found")
    return narration
