"""Object storage helper (S3 / MinIO).

Wraps boto3 with the small surface we need:

- ``put_bytes`` to upload a file
- ``upload_from_url`` to stream a remote URL straight into the bucket
- ``presigned_get_url`` for short-lived download links
- ``public_url`` for browser-accessible URLs (when the bucket is public)
"""

from __future__ import annotations

from typing import Any

import boto3
import httpx
import structlog
from botocore.client import Config

from content_creator_api.config import get_settings

log = structlog.get_logger(__name__)


class StorageError(RuntimeError):
    pass


def _client() -> Any:
    settings = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url or None,
        region_name=settings.s3_region,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        config=Config(signature_version="s3v4"),
    )


def ensure_bucket() -> None:
    """Create the configured bucket if it doesn't exist."""
    settings = get_settings()
    s3 = _client()
    try:
        s3.head_bucket(Bucket=settings.s3_bucket)
    except Exception:
        s3.create_bucket(Bucket=settings.s3_bucket)
        log.info("storage.bucket_created", bucket=settings.s3_bucket)


def put_bytes(key: str, data: bytes, *, content_type: str = "application/octet-stream") -> str:
    settings = get_settings()
    s3 = _client()
    s3.put_object(
        Bucket=settings.s3_bucket,
        Key=key,
        Body=data,
        ContentType=content_type,
    )
    return key


def get_bytes(key: str) -> bytes:
    """Download an object from the bucket as raw bytes."""
    settings = get_settings()
    s3 = _client()
    response = s3.get_object(Bucket=settings.s3_bucket, Key=key)
    body: bytes = response["Body"].read()
    return body


def upload_from_url(url: str, key: str, *, content_type: str | None = None) -> int:
    """Stream ``url`` into the bucket at ``key``. Returns bytes written."""
    settings = get_settings()
    s3 = _client()
    with httpx.stream("GET", url, follow_redirects=True, timeout=60.0) as response:
        if response.status_code >= 400:
            raise StorageError(
                f"download failed ({response.status_code}) for {url}"
            )
        ct = content_type or response.headers.get("content-type", "video/mp4")
        body = response.read()
    s3.put_object(
        Bucket=settings.s3_bucket,
        Key=key,
        Body=body,
        ContentType=ct,
    )
    return len(body)


def presigned_get_url(key: str, *, expires_in: int = 3600) -> str:
    settings = get_settings()
    s3 = _client()
    return str(
        s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.s3_bucket, "Key": key},
            ExpiresIn=expires_in,
        )
    )


def public_url(key: str) -> str:
    settings = get_settings()
    base = settings.s3_public_url.rstrip("/")
    return f"{base}/{key}"
