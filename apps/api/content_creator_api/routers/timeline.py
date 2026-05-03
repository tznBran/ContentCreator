"""Timeline read/write + export endpoints.

The frontend treats the timeline as a single list of items. PUT replaces
the whole list atomically (preserving ``id`` where supplied so cross-edits
keep the same row). POST /exports kicks off the ffmpeg render via RQ.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, col, select

from content_creator_api.config import get_settings
from content_creator_api.db import get_session
from content_creator_api.models import (
    ExportJob,
    ExportStatus,
    Project,
    TimelineItem,
)
from content_creator_api.schemas import (
    ExportCreate,
    ExportRead,
    TimelineItemRead,
    TimelinePut,
)
from content_creator_api.services.queue import get_queue
from content_creator_api.tasks.render import render_export_job

router = APIRouter(tags=["timeline"])


def _now() -> datetime:
    return datetime.now(UTC)


def _list_items(session: Session, project_id: UUID) -> list[TimelineItem]:
    rows = session.exec(
        select(TimelineItem)
        .where(TimelineItem.project_id == project_id)
        .order_by(col(TimelineItem.order_index).asc())
    ).all()
    return list(rows)


@router.get(
    "/projects/{project_id}/timeline", response_model=list[TimelineItemRead]
)
def get_timeline(
    project_id: UUID, session: Session = Depends(get_session)
) -> list[TimelineItem]:
    if session.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")
    return _list_items(session, project_id)


@router.put(
    "/projects/{project_id}/timeline", response_model=list[TimelineItemRead]
)
def put_timeline(
    project_id: UUID,
    payload: TimelinePut,
    session: Session = Depends(get_session),
) -> list[TimelineItem]:
    if session.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")

    existing = {item.id: item for item in _list_items(session, project_id)}
    seen_ids: set[UUID] = set()

    for index, write in enumerate(payload.items):
        if write.id is not None and write.id in existing:
            row = existing[write.id]
            row.order_index = index
            row.item_type = write.item_type
            row.clip_id = write.clip_id
            row.source_start_ms = write.source_start_ms
            row.duration_ms = write.duration_ms
            row.transition_in = write.transition_in
            row.transition_out = write.transition_out
            row.text_overlay = write.text_overlay
            row.audio_storage_key = write.audio_storage_key
            row.volume = write.volume
            row.updated_at = _now()
            seen_ids.add(row.id)
            session.add(row)
        else:
            row = TimelineItem(
                project_id=project_id,
                order_index=index,
                item_type=write.item_type,
                clip_id=write.clip_id,
                source_start_ms=write.source_start_ms,
                duration_ms=write.duration_ms,
                transition_in=write.transition_in,
                transition_out=write.transition_out,
                text_overlay=write.text_overlay,
                audio_storage_key=write.audio_storage_key,
                volume=write.volume,
            )
            session.add(row)

    # Delete removed rows.
    for old_id, old in existing.items():
        if old_id not in seen_ids and not any(
            w.id == old_id for w in payload.items
        ):
            session.delete(old)

    session.commit()
    return _list_items(session, project_id)


@router.post(
    "/projects/{project_id}/exports",
    response_model=ExportRead,
    status_code=status.HTTP_201_CREATED,
)
def create_export(
    project_id: UUID,
    payload: ExportCreate,
    session: Session = Depends(get_session),
) -> ExportJob:
    if session.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")
    if not _list_items(session, project_id):
        raise HTTPException(status_code=400, detail="timeline is empty")

    job = ExportJob(
        project_id=project_id,
        width=payload.width,
        height=payload.height,
        fps=payload.fps,
        status=ExportStatus.PENDING,
    )
    session.add(job)
    session.commit()
    session.refresh(job)

    if get_settings().enqueue_jobs:
        get_queue().enqueue(
            render_export_job,
            str(job.id),
            job_timeout=3600,
            result_ttl=3600,
        )

    return job


@router.get(
    "/projects/{project_id}/exports", response_model=list[ExportRead]
)
def list_exports(
    project_id: UUID, session: Session = Depends(get_session)
) -> list[ExportJob]:
    if session.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")
    rows = session.exec(
        select(ExportJob)
        .where(ExportJob.project_id == project_id)
        .order_by(col(ExportJob.created_at).desc())
    ).all()
    return list(rows)


@router.get("/exports/{export_id}", response_model=ExportRead)
def get_export(
    export_id: UUID, session: Session = Depends(get_session)
) -> ExportJob:
    job = session.get(ExportJob, export_id)
    if job is None:
        raise HTTPException(status_code=404, detail="export not found")
    return job
