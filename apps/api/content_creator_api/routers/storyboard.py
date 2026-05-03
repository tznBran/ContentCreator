"""Storyboard expansion: prompt -> N ordered Shot rows.

Calls the OpenRouter chat endpoint synchronously inside the request
handler. This is intentionally fast (no media), so it lives on the API
process rather than the worker queue.
"""

from __future__ import annotations

import asyncio
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
    Shot,
)
from content_creator_api.schemas import (
    GenerationDetail,
    ShotCreate,
    ShotRead,
    ShotUpdate,
    StoryboardCreate,
)
from content_creator_api.services.openrouter import OpenRouterClient
from content_creator_api.services.queue import get_queue
from content_creator_api.services.storyboard import generate_storyboard
from content_creator_api.tasks.generation import generate_and_score_clip

router = APIRouter(tags=["storyboard"])


def _now() -> datetime:
    return datetime.now(UTC)


def _list_shots(session: Session, project_id: UUID) -> list[Shot]:
    rows = session.exec(
        select(Shot)
        .where(Shot.project_id == project_id)
        .order_by(col(Shot.order_index).asc())
    ).all()
    return list(rows)


@router.get("/projects/{project_id}/shots", response_model=list[ShotRead])
def list_shots(
    project_id: UUID, session: Session = Depends(get_session)
) -> list[Shot]:
    if session.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")
    return _list_shots(session, project_id)


@router.post(
    "/projects/{project_id}/shots",
    response_model=ShotRead,
    status_code=status.HTTP_201_CREATED,
)
def create_shot(
    project_id: UUID,
    payload: ShotCreate,
    session: Session = Depends(get_session),
) -> Shot:
    if session.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")
    existing = _list_shots(session, project_id)
    order_index = (
        payload.order_index if payload.order_index is not None else len(existing)
    )
    shot = Shot(
        project_id=project_id,
        prompt=payload.prompt,
        duration_seconds=payload.duration_seconds,
        aspect_ratio=payload.aspect_ratio,
        notes=payload.notes,
        order_index=order_index,
    )
    session.add(shot)
    session.commit()
    session.refresh(shot)
    return shot


@router.patch("/shots/{shot_id}", response_model=ShotRead)
def update_shot(
    shot_id: UUID,
    payload: ShotUpdate,
    session: Session = Depends(get_session),
) -> Shot:
    shot = session.get(Shot, shot_id)
    if shot is None:
        raise HTTPException(status_code=404, detail="shot not found")
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(shot, key, value)
    shot.updated_at = _now()
    session.add(shot)
    session.commit()
    session.refresh(shot)
    return shot


@router.delete("/shots/{shot_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_shot(shot_id: UUID, session: Session = Depends(get_session)) -> None:
    shot = session.get(Shot, shot_id)
    if shot is None:
        raise HTTPException(status_code=404, detail="shot not found")
    session.delete(shot)
    session.commit()


@router.post(
    "/shots/{shot_id}/generations",
    response_model=GenerationDetail,
    status_code=status.HTTP_201_CREATED,
)
def generate_shot_clips(
    shot_id: UUID,
    n_variants: int = 3,
    session: Session = Depends(get_session),
) -> GenerationDetail:
    """Spawn N Seedance variants for this shot's prompt.

    Reuses the same Phase 1 generation pipeline. The created GenerationJob
    is recorded on ``shot.generation_job_id``; the auto-picked
    ``best_clip_id`` later fills in ``shot.selected_clip_id`` (the frontend
    can also override the pick).
    """
    shot = session.get(Shot, shot_id)
    if shot is None:
        raise HTTPException(status_code=404, detail="shot not found")
    if not 1 <= n_variants <= 8:
        raise HTTPException(status_code=400, detail="n_variants must be 1..8")

    settings = get_settings()
    job = GenerationJob(
        project_id=shot.project_id,
        prompt=shot.prompt,
        n_variants=n_variants,
        aspect_ratio=shot.aspect_ratio,
        duration_seconds=shot.duration_seconds,
        model=settings.openrouter_video_model,
        status=GenerationJobStatus.RUNNING,
    )
    session.add(job)
    session.commit()
    session.refresh(job)

    clips: list[Clip] = []
    for i in range(n_variants):
        clip = Clip(
            project_id=shot.project_id,
            generation_job_id=job.id,
            variant_index=i,
            prompt=shot.prompt,
            status=ClipStatus.PENDING,
        )
        session.add(clip)
        clips.append(clip)
    session.commit()
    for clip in clips:
        session.refresh(clip)

    shot.generation_job_id = job.id
    shot.updated_at = _now()
    session.add(shot)
    session.commit()

    if settings.enqueue_jobs:
        queue = get_queue()
        for clip in clips:
            queue.enqueue(
                generate_and_score_clip,
                str(clip.id),
                job_timeout=1800,
                result_ttl=3600,
            )

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
        clips=[],
    )


@router.post(
    "/projects/{project_id}/storyboard",
    response_model=list[ShotRead],
    status_code=status.HTTP_201_CREATED,
)
def create_storyboard(
    project_id: UUID,
    payload: StoryboardCreate,
    session: Session = Depends(get_session),
) -> list[Shot]:
    """Replace any existing shots with an LLM-generated shot list."""
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")

    settings = get_settings()
    if not settings.openrouter_api_key:
        raise HTTPException(
            status_code=503,
            detail="storyboard requires OPENROUTER_API_KEY",
        )

    prompt = payload.prompt or project.prompt
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt required")

    client = OpenRouterClient(
        api_key=settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
    )
    try:
        shots_data = asyncio.run(
            generate_storyboard(
                client,
                model=settings.openrouter_llm_model,
                prompt=prompt,
                n_shots=payload.n_shots,
                total_duration_seconds=payload.total_duration_seconds,
            )
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"llm error: {exc}") from exc

    if not shots_data:
        raise HTTPException(status_code=502, detail="llm returned no shots")

    # Wipe existing shots so the result is deterministic.
    existing = _list_shots(session, project_id)
    for old in existing:
        session.delete(old)
    session.commit()

    out: list[Shot] = []
    for index, shot_data in enumerate(shots_data):
        shot = Shot(
            project_id=project_id,
            prompt=shot_data.prompt,
            duration_seconds=shot_data.duration_seconds,
            aspect_ratio=payload.aspect_ratio,
            notes=shot_data.notes,
            order_index=index,
        )
        session.add(shot)
        out.append(shot)
    session.commit()
    for shot in out:
        session.refresh(shot)
    return out
