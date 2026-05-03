"""RQ task that renders a project's timeline into a single mp4 file."""

from __future__ import annotations

import logging
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy.orm import Session as ORMSession
from sqlmodel import Session, col, select

from content_creator_api.config import get_settings
from content_creator_api.db import engine
from content_creator_api.models import (
    Clip,
    ExportJob,
    ExportStatus,
    TimelineItem,
    TimelineItemType,
)
from content_creator_api.services import storage
from content_creator_api.services.render import (
    RenderClip,
    RenderError,
    RenderSpec,
    render_timeline,
)

log = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


def _save(session: ORMSession, obj: ExportJob) -> None:
    obj.updated_at = _now()
    session.add(obj)
    session.commit()
    session.refresh(obj)


def _load_render_clips(session: Session, project_id: UUID) -> list[RenderClip]:
    items = session.exec(
        select(TimelineItem)
        .where(TimelineItem.project_id == project_id)
        .where(TimelineItem.item_type == TimelineItemType.CLIP)
        .order_by(col(TimelineItem.order_index).asc())
    ).all()
    if not items:
        raise RenderError("project has no timeline items")
    out: list[RenderClip] = []
    for item in items:
        if item.clip_id is None:
            continue
        clip = session.get(Clip, item.clip_id)
        if clip is None or not clip.public_url:
            raise RenderError(f"timeline references clip {item.clip_id} with no url")
        out.append(
            RenderClip(
                source_url=clip.public_url,
                source_start_ms=item.source_start_ms,
                duration_ms=item.duration_ms,
            )
        )
    if not out:
        raise RenderError("no playable clips on the timeline")
    return out


def render_export_job(export_id: str) -> None:
    """Synchronous RQ entrypoint."""
    job_id = UUID(export_id)
    settings = get_settings()
    work_dir = Path(tempfile.mkdtemp(prefix=f"export-{job_id}-"))
    try:
        with Session(engine) as session:
            export = session.get(ExportJob, job_id)
            if export is None:
                log.warning("export.missing %s", job_id)
                return

            try:
                export.status = ExportStatus.RENDERING
                _save(session, export)

                clips = _load_render_clips(session, export.project_id)
                spec = RenderSpec(
                    width=export.width,
                    height=export.height,
                    fps=export.fps,
                )
                output = render_timeline(clips, spec=spec, work_dir=work_dir)

                export.status = ExportStatus.UPLOADING
                _save(session, export)

                key = f"exports/{export.project_id}/{export.id}.mp4"
                with output.open("rb") as fh:
                    body = fh.read()
                if settings.s3_endpoint_url:
                    storage.put_bytes(key, body, content_type="video/mp4")
                else:
                    log.info("export.dryrun key=%s bytes=%d", key, len(body))

                export.storage_key = key
                export.public_url = storage.public_url(key)
                export.duration_ms = sum(c.duration_ms for c in clips)
                export.status = ExportStatus.SUCCEEDED
                _save(session, export)
            except Exception as exc:
                log.exception("export.failed %s", job_id)
                export.status = ExportStatus.FAILED
                export.error = str(exc)[:2000]
                _save(session, export)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
