"""Endpoints for generation jobs and clips.

Endpoints:

* ``POST /projects/{project_id}/generations`` — kick off N variant generation.
  Creates a GenerationJob + N pending Clips and enqueues an RQ task per clip.
* ``GET /projects/{project_id}/generations`` — list jobs for a project.
* ``GET /generations/{job_id}`` — fetch a single job with its clips (poll this).
* ``POST /generations/{job_id}/winner`` — explicitly mark a clip as the winner.
* ``GET /clips/{clip_id}`` — fetch a single clip.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, col, select

from content_creator_api.config import get_settings
from content_creator_api.db import get_session
from content_creator_api.models import (
    Clip,
    ClipStatus,
    GenerationJob,
    GenerationJobStatus,
    Project,
)
from content_creator_api.schemas import (
    ClipRead,
    GenerationCreate,
    GenerationDetail,
    GenerationRead,
    WinnerSelect,
)
from content_creator_api.services.queue import get_queue
from content_creator_api.tasks.generation import generate_and_score_clip

router = APIRouter(tags=["generations"])


def _now() -> datetime:
    return datetime.now(UTC)


def _to_detail(session: Session, job: GenerationJob) -> GenerationDetail:
    rows = session.exec(
        select(Clip).where(Clip.generation_job_id == job.id).order_by(
            col(Clip.variant_index).asc()
        )
    ).all()
    return GenerationDetail(
        id=job.id,
        project_id=job.project_id,
        prompt=job.prompt,
        n_variants=job.n_variants,
        aspect_ratio=job.aspect_ratio,
        duration_seconds=job.duration_seconds,
        model=job.model,
        status=job.status,
        best_clip_id=job.best_clip_id,
        error=job.error,
        created_at=job.created_at,
        updated_at=job.updated_at,
        clips=[ClipRead.model_validate(c) for c in rows],
    )


@router.post(
    "/projects/{project_id}/generations",
    response_model=GenerationDetail,
    status_code=status.HTTP_201_CREATED,
)
def create_generation(
    project_id: UUID,
    payload: GenerationCreate,
    session: Session = Depends(get_session),
) -> GenerationDetail:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")

    settings = get_settings()
    job = GenerationJob(
        project_id=project_id,
        prompt=payload.prompt,
        n_variants=payload.n_variants,
        aspect_ratio=payload.aspect_ratio,
        duration_seconds=payload.duration_seconds,
        model=payload.model or settings.openrouter_video_model,
        status=GenerationJobStatus.RUNNING,
    )
    session.add(job)
    session.commit()
    session.refresh(job)

    clips: list[Clip] = []
    for i in range(payload.n_variants):
        clip = Clip(
            project_id=project_id,
            generation_job_id=job.id,
            variant_index=i,
            prompt=payload.prompt,
            status=ClipStatus.PENDING,
        )
        session.add(clip)
        clips.append(clip)
    session.commit()
    for clip in clips:
        session.refresh(clip)

    if settings.enqueue_jobs:
        queue = get_queue()
        for clip in clips:
            queue.enqueue(
                generate_and_score_clip,
                str(clip.id),
                job_timeout=1800,
                result_ttl=3600,
            )

    return _to_detail(session, job)


@router.get(
    "/projects/{project_id}/generations",
    response_model=list[GenerationRead],
)
def list_generations(
    project_id: UUID,
    session: Session = Depends(get_session),
) -> list[GenerationJob]:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    rows = session.exec(
        select(GenerationJob)
        .where(GenerationJob.project_id == project_id)
        .order_by(col(GenerationJob.created_at).desc())
    ).all()
    return list(rows)


@router.get("/generations/{job_id}", response_model=GenerationDetail)
def get_generation(
    job_id: UUID,
    session: Session = Depends(get_session),
) -> GenerationDetail:
    job = session.get(GenerationJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="generation not found")
    return _to_detail(session, job)


@router.post("/generations/{job_id}/winner", response_model=GenerationDetail)
def set_winner(
    job_id: UUID,
    payload: WinnerSelect,
    session: Session = Depends(get_session),
) -> GenerationDetail:
    job = session.get(GenerationJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="generation not found")
    clip = session.get(Clip, payload.clip_id)
    if clip is None or clip.generation_job_id != job.id:
        raise HTTPException(status_code=404, detail="clip not in this generation")
    job.best_clip_id = clip.id
    job.updated_at = _now()
    session.add(job)
    session.commit()
    session.refresh(job)
    return _to_detail(session, job)


@router.get("/clips/{clip_id}", response_model=ClipRead)
def get_clip(clip_id: UUID, session: Session = Depends(get_session)) -> Clip:
    clip = session.get(Clip, clip_id)
    if clip is None:
        raise HTTPException(status_code=404, detail="clip not found")
    return clip
