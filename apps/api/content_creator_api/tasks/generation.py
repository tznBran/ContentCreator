"""RQ tasks that drive Seedance 2.0 generation + scoring.

The job lifecycle for one clip:

    PENDING
      -> GENERATING       submit to OpenRouter, store provider_job_id
      -> DOWNLOADING      poll until completed, stream the result into S3
      -> SCORING          ask the vision LLM for a 0-100 score
      -> SUCCEEDED        we have storage_key, score, score_explanation

A separate finalize task runs after all clips terminate and picks a winner.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID

import structlog
from sqlmodel import Session, select

from content_creator_api.config import get_settings
from content_creator_api.db import engine
from content_creator_api.models import (
    Clip,
    ClipStatus,
    GenerationJob,
    GenerationJobStatus,
)
from content_creator_api.services import storage
from content_creator_api.services.openrouter import (
    OpenRouterClient,
    OpenRouterError,
)
from content_creator_api.services.scoring import score_clip

log = structlog.get_logger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


def _refresh_clip(session: Session, clip_id: UUID) -> Clip:
    clip = session.get(Clip, clip_id)
    if clip is None:
        raise ValueError(f"clip {clip_id} not found")
    return clip


def _save(session: Session, *objs: Clip | GenerationJob) -> None:
    for obj in objs:
        obj.updated_at = _now()
        session.add(obj)
    session.commit()
    for obj in objs:
        session.refresh(obj)


def generate_and_score_clip(clip_id: str) -> None:
    """Synchronous RQ entrypoint. Runs the full lifecycle for one clip."""
    asyncio.run(_run_clip(UUID(clip_id)))


async def _run_clip(clip_id: UUID) -> None:
    settings = get_settings()
    client = OpenRouterClient(
        api_key=settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
    )

    with Session(engine) as session:
        clip = _refresh_clip(session, clip_id)
        job = session.get(GenerationJob, clip.generation_job_id) if clip.generation_job_id else None
        try:
            clip.status = ClipStatus.GENERATING
            _save(session, clip)
            submission = await client.submit_video(
                model=job.model if job else settings.openrouter_video_model,
                prompt=clip.prompt,
                aspect_ratio=job.aspect_ratio if job else "9:16",
                duration_seconds=job.duration_seconds if job else 5,
            )
            clip.provider_job_id = submission.id
            clip.polling_url = submission.polling_url
            _save(session, clip)

            result = await client.wait_for_video(
                submission.polling_url,
                interval_seconds=5.0,
                timeout_seconds=900.0,
            )
            if not result.succeeded:
                raise OpenRouterError(
                    result.error or f"video job ended in status {result.status}"
                )

            source_url = result.unsigned_urls[0]
            clip.source_url = source_url
            clip.cost_usd = result.cost_usd
            clip.status = ClipStatus.DOWNLOADING
            _save(session, clip)

            key = f"clips/{clip.project_id}/{clip.id}.mp4"
            storage.upload_from_url(source_url, key, content_type="video/mp4")
            clip.storage_key = key
            clip.public_url = storage.public_url(key)
            clip.status = ClipStatus.SCORING
            _save(session, clip)

            scoring_url = storage.presigned_get_url(key)
            score = await score_clip(
                client,
                model=settings.openrouter_vision_model,
                prompt=clip.prompt,
                clip_url=scoring_url,
            )
            clip.score = score.score
            clip.score_explanation = score.explanation
            clip.status = ClipStatus.SUCCEEDED
            _save(session, clip)
            log.info(
                "clip.succeeded",
                clip_id=str(clip.id),
                score=score.score,
            )
        except Exception as exc:
            log.exception("clip.failed", clip_id=str(clip.id))
            clip.status = ClipStatus.FAILED
            clip.error = str(exc)[:2000]
            _save(session, clip)
        finally:
            if job is not None:
                _maybe_finalize_job(session, job.id)


def _maybe_finalize_job(session: Session, job_id: UUID) -> None:
    """If all clips are terminal, mark the job done and pick the winner."""
    job = session.get(GenerationJob, job_id)
    if job is None:
        return
    clips = list(session.exec(select(Clip).where(Clip.generation_job_id == job_id)))
    if not clips:
        return
    pending = [
        c
        for c in clips
        if c.status
        not in (ClipStatus.SUCCEEDED, ClipStatus.FAILED)
    ]
    if pending:
        return
    succeeded = [c for c in clips if c.status == ClipStatus.SUCCEEDED]
    if succeeded:
        succeeded.sort(key=lambda c: (c.score is None, -(c.score or 0.0)))
        job.best_clip_id = succeeded[0].id
        job.status = GenerationJobStatus.SUCCEEDED
    else:
        job.status = GenerationJobStatus.FAILED
        job.error = "all variants failed"
    job.updated_at = _now()
    session.add(job)
    session.commit()


def finalize_generation_job(job_id: str) -> None:
    """Idempotent finalizer (in case nothing else triggered it)."""
    with Session(engine) as session:
        _maybe_finalize_job(session, UUID(job_id))
