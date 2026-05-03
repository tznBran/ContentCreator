"""RQ task: upload an exported mp4 to a connected social account."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlmodel import Session

from content_creator_api.db import engine
from content_creator_api.models import (
    ExportJob,
    ExportStatus,
    PublishJob,
    PublishStatus,
    SocialAccount,
)
from content_creator_api.services import storage
from content_creator_api.services.publishers import (
    PublisherError,
    PublishMetadata,
    get_publisher,
)

log = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


def publish_video(publish_id: str) -> None:
    """Upload the export referenced by ``publish_id`` to the platform."""
    job_uuid = UUID(publish_id)
    with Session(engine) as session:
        job = session.get(PublishJob, job_uuid)
        if job is None:
            log.warning("publish.missing %s", publish_id)
            return
        try:
            export = session.get(ExportJob, job.export_id)
            account = session.get(SocialAccount, job.account_id)
            if export is None or export.status != ExportStatus.SUCCEEDED:
                raise PublisherError("export not ready")
            if account is None:
                raise PublisherError("social account not connected")
            if export.storage_key is None:
                raise PublisherError("export has no storage key")

            job.status = PublishStatus.UPLOADING
            job.updated_at = _now()
            session.add(job)
            session.commit()

            video_bytes = storage.get_bytes(export.storage_key)
            public_url = export.public_url

            publisher = get_publisher(job.platform)
            metadata = PublishMetadata(
                title=job.title,
                description=job.description,
                visibility=job.visibility,
            )

            job.status = PublishStatus.PROCESSING
            job.updated_at = _now()
            session.add(job)
            session.commit()

            result = asyncio.run(
                publisher.publish(
                    account=account,
                    video_bytes=video_bytes,
                    public_video_url=public_url,
                    metadata=metadata,
                )
            )

            job.platform_media_id = result.platform_media_id
            job.platform_url = result.platform_url
            job.status = PublishStatus.SUCCEEDED
            job.updated_at = _now()
            session.add(job)
            session.commit()
        except Exception as exc:
            log.exception("publish.failed %s", publish_id)
            job.status = PublishStatus.FAILED
            job.error = str(exc)[:2000]
            job.updated_at = _now()
            session.add(job)
            session.commit()
