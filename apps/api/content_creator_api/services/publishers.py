"""Platform publishers (YouTube / TikTok / Instagram).

Each publisher takes a connected :class:`SocialAccount` plus an mp4
payload + metadata and uploads it. Returns a :class:`PublishResult`
with the platform's media id + browseable URL.

The three platforms have very different upload protocols, so the
abstraction stays narrow:

- YouTube uses a resumable upload (init → PUT bytes → returns video
  id). For our prototype we use the simpler multipart upload because
  videos are typically <128 MB; can switch to resumable later.
- TikTok requires init → upload chunks → publish (3 calls).
- Instagram (via the Graph API) requires the mp4 to be at a public
  URL — Meta pulls it themselves. We pass the export's MinIO/S3
  presigned URL.

All of these talk to ``httpx.AsyncClient`` so they slot into the
``asyncio.run`` shim used by RQ tasks.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Protocol

import httpx

from content_creator_api.config import Settings, get_settings
from content_creator_api.models import (
    PublishVisibility,
    SocialAccount,
    SocialPlatform,
)
from content_creator_api.services.oauth import decode_extra

log = logging.getLogger(__name__)


class PublisherError(RuntimeError):
    pass


@dataclass(slots=True)
class PublishMetadata:
    title: str
    description: str
    visibility: PublishVisibility


@dataclass(slots=True)
class PublishResult:
    platform_media_id: str
    platform_url: str | None


class Publisher(Protocol):
    platform: SocialPlatform

    async def publish(
        self,
        *,
        account: SocialAccount,
        video_bytes: bytes,
        public_video_url: str | None,
        metadata: PublishMetadata,
    ) -> PublishResult: ...


# ----------------------------- YouTube --------------------------------


class YouTubePublisher:
    platform = SocialPlatform.YOUTUBE
    UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
    WATCH_URL = "https://www.youtube.com/watch?v={video_id}"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def publish(
        self,
        *,
        account: SocialAccount,
        video_bytes: bytes,
        public_video_url: str | None,
        metadata: PublishMetadata,
    ) -> PublishResult:
        del public_video_url
        privacy = _yt_privacy(metadata.visibility)
        snippet_resource = {
            "snippet": {
                "title": metadata.title[:100],
                "description": metadata.description[:5000],
                "categoryId": "22",
            },
            "status": {
                "privacyStatus": privacy,
                "selfDeclaredMadeForKids": False,
            },
        }
        async with httpx.AsyncClient(timeout=600) as client:
            response = await client.post(
                self.UPLOAD_URL,
                params={"part": "snippet,status", "uploadType": "multipart"},
                headers={"Authorization": f"Bearer {account.access_token}"},
                files={
                    "metadata": (
                        "metadata.json",
                        _json_bytes(snippet_resource),
                        "application/json; charset=UTF-8",
                    ),
                    "video": ("video.mp4", video_bytes, "video/mp4"),
                },
            )
        if response.status_code >= 400:
            raise PublisherError(
                f"youtube upload failed ({response.status_code}): {response.text}"
            )
        body = response.json()
        video_id = str(body.get("id", ""))
        if not video_id:
            raise PublisherError(f"youtube upload returned no video id: {body}")
        return PublishResult(
            platform_media_id=video_id,
            platform_url=self.WATCH_URL.format(video_id=video_id),
        )


def _yt_privacy(v: PublishVisibility) -> str:
    return {
        PublishVisibility.PRIVATE: "private",
        PublishVisibility.UNLISTED: "unlisted",
        PublishVisibility.PUBLIC: "public",
    }[v]


# ------------------------------ TikTok --------------------------------


class TikTokPublisher:
    platform = SocialPlatform.TIKTOK
    INIT_URL = "https://open.tiktokapis.com/v2/post/publish/video/init/"
    STATUS_URL = "https://open.tiktokapis.com/v2/post/publish/status/fetch/"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def publish(
        self,
        *,
        account: SocialAccount,
        video_bytes: bytes,
        public_video_url: str | None,
        metadata: PublishMetadata,
    ) -> PublishResult:
        del public_video_url
        privacy = _tiktok_privacy(metadata.visibility)
        post_info = {
            "title": metadata.title[:150],
            "description": metadata.description[:2200],
            "privacy_level": privacy,
            "disable_duet": False,
            "disable_comment": False,
            "disable_stitch": False,
            "video_cover_timestamp_ms": 0,
        }
        async with httpx.AsyncClient(timeout=600) as client:
            init_resp = await client.post(
                self.INIT_URL,
                headers={
                    "Authorization": f"Bearer {account.access_token}",
                    "Content-Type": "application/json; charset=UTF-8",
                },
                json={
                    "post_info": post_info,
                    "source_info": {
                        "source": "FILE_UPLOAD",
                        "video_size": len(video_bytes),
                        "chunk_size": len(video_bytes),
                        "total_chunk_count": 1,
                    },
                },
            )
            init_body = _ok_json(init_resp, "tiktok init")
            data_raw = init_body.get("data", {})
            data: dict[str, object] = data_raw if isinstance(data_raw, dict) else {}
            publish_id = str(data.get("publish_id", ""))
            upload_url = str(data.get("upload_url", ""))
            if not publish_id or not upload_url:
                raise PublisherError(f"tiktok init missing fields: {init_body}")

            put_resp = await client.put(
                upload_url,
                content=video_bytes,
                headers={
                    "Content-Range": f"bytes 0-{len(video_bytes) - 1}/{len(video_bytes)}",
                    "Content-Type": "video/mp4",
                },
            )
            if put_resp.status_code >= 400:
                raise PublisherError(
                    f"tiktok upload PUT failed ({put_resp.status_code}): {put_resp.text}"
                )

            for _ in range(20):
                status_resp = await client.post(
                    self.STATUS_URL,
                    headers={
                        "Authorization": f"Bearer {account.access_token}",
                        "Content-Type": "application/json; charset=UTF-8",
                    },
                    json={"publish_id": publish_id},
                )
                status_body = _ok_json(status_resp, "tiktok status")
                status_data_raw = status_body.get("data", {})
                status_data: dict[str, object] = (
                    status_data_raw if isinstance(status_data_raw, dict) else {}
                )
                status = str(status_data.get("status", "PROCESSING")).upper()
                if status in {"PUBLISH_COMPLETE", "SUCCEEDED"}:
                    break
                if status in {"FAILED", "CANCELLED"}:
                    raise PublisherError(f"tiktok publish failed: {status_body}")
                await asyncio.sleep(2)
            else:
                raise PublisherError("tiktok publish status never reached terminal state")

        return PublishResult(platform_media_id=publish_id, platform_url=None)


def _tiktok_privacy(v: PublishVisibility) -> str:
    return {
        PublishVisibility.PRIVATE: "SELF_ONLY",
        PublishVisibility.UNLISTED: "MUTUAL_FOLLOW_FRIENDS",
        PublishVisibility.PUBLIC: "PUBLIC_TO_EVERYONE",
    }[v]


# ---------------------------- Instagram -------------------------------


class InstagramPublisher:
    platform = SocialPlatform.INSTAGRAM
    BASE = "https://graph.facebook.com/v19.0"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def publish(
        self,
        *,
        account: SocialAccount,
        video_bytes: bytes,
        public_video_url: str | None,
        metadata: PublishMetadata,
    ) -> PublishResult:
        del video_bytes
        if not public_video_url:
            raise PublisherError(
                "instagram publish requires a public mp4 URL; "
                "set S3_PUBLIC_URL or use a presigned URL"
            )
        extra = decode_extra(account.extra_json)
        ig_user_id = (
            extra.get("ig_user_id")
            or self._settings.instagram_user_id
            or account.external_id
        )
        if not ig_user_id:
            raise PublisherError("missing instagram_user_id for IG publish")

        caption = (metadata.title + "\n\n" + metadata.description).strip()[:2200]
        async with httpx.AsyncClient(timeout=600) as client:
            container_resp = await client.post(
                f"{self.BASE}/{ig_user_id}/media",
                params={
                    "media_type": "REELS",
                    "video_url": public_video_url,
                    "caption": caption,
                    "access_token": account.access_token,
                },
            )
            container = _ok_json(container_resp, "ig media create")
            container_id = str(container.get("id", ""))
            if not container_id:
                raise PublisherError(f"ig container has no id: {container}")

            for _ in range(30):
                status_resp = await client.get(
                    f"{self.BASE}/{container_id}",
                    params={
                        "fields": "status_code",
                        "access_token": account.access_token,
                    },
                )
                status_body = _ok_json(status_resp, "ig status")
                status_code = str(status_body.get("status_code", "IN_PROGRESS")).upper()
                if status_code == "FINISHED":
                    break
                if status_code in {"ERROR", "EXPIRED"}:
                    raise PublisherError(f"ig container failed: {status_body}")
                await asyncio.sleep(2)
            else:
                raise PublisherError("ig container never finished processing")

            publish_resp = await client.post(
                f"{self.BASE}/{ig_user_id}/media_publish",
                params={
                    "creation_id": container_id,
                    "access_token": account.access_token,
                },
            )
            publish_body = _ok_json(publish_resp, "ig publish")
            media_id = str(publish_body.get("id", ""))
            if not media_id:
                raise PublisherError(f"ig publish returned no id: {publish_body}")

        return PublishResult(
            platform_media_id=media_id,
            platform_url=f"https://www.instagram.com/p/{media_id}/",
        )


def _ok_json(response: httpx.Response, op: str) -> dict[str, object]:
    if response.status_code >= 400:
        raise PublisherError(f"{op} failed ({response.status_code}): {response.text}")
    return response.json()  # type: ignore[no-any-return]


def _json_bytes(payload: dict[str, object]) -> bytes:
    import json as _json

    return _json.dumps(payload).encode("utf-8")


_REGISTRY: dict[SocialPlatform, type] = {
    SocialPlatform.YOUTUBE: YouTubePublisher,
    SocialPlatform.TIKTOK: TikTokPublisher,
    SocialPlatform.INSTAGRAM: InstagramPublisher,
}


def get_publisher(platform: SocialPlatform) -> Publisher:
    cls = _REGISTRY.get(platform)
    if cls is None:
        raise PublisherError(f"unsupported platform {platform}")
    return cls(get_settings())  # type: ignore[no-any-return]
