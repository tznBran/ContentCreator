"""OpenRouter client.

Wraps the two endpoints we need:

* ``POST /api/v1/videos`` to submit a video generation job
  (https://openrouter.ai/docs/api/api-reference/video-generation/create-videos).
* ``GET /api/v1/videos/{jobId}`` to poll status
  (https://openrouter.ai/docs/api/api-reference/video-generation/get-videos).

Plus a chat-completions helper for LLM scoring of generated clips.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Literal

import httpx
import structlog

log = structlog.get_logger(__name__)

VideoStatus = Literal[
    "pending", "in_progress", "completed", "failed", "cancelled", "expired"
]


class OpenRouterError(RuntimeError):
    """Raised when an OpenRouter call fails."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(slots=True)
class VideoGeneration:
    """Snapshot of an OpenRouter video generation job."""

    id: str
    status: VideoStatus
    polling_url: str
    unsigned_urls: list[str]
    cost_usd: float | None
    error: str | None

    @property
    def is_terminal(self) -> bool:
        return self.status in ("completed", "failed", "cancelled", "expired")

    @property
    def succeeded(self) -> bool:
        return self.status == "completed" and bool(self.unsigned_urls)


def _parse_video_response(payload: dict[str, Any]) -> VideoGeneration:
    usage = payload.get("usage") or {}
    return VideoGeneration(
        id=payload["id"],
        status=payload["status"],
        polling_url=payload["polling_url"],
        unsigned_urls=list(payload.get("unsigned_urls") or []),
        cost_usd=usage.get("cost"),
        error=payload.get("error"),
    )


class OpenRouterClient:
    """Async OpenRouter client.

    Constructed with an API key. All methods are :keyword:`async` so they
    play nicely with asyncio-based code paths and are easy to mock from
    tests.
    """

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://openrouter.ai/api/v1",
        http_referer: str | None = None,
        x_title: str | None = "ContentCreator",
        timeout: float = 60.0,
    ) -> None:
        if not api_key:
            raise OpenRouterError("OPENROUTER_API_KEY is not set")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._http_referer = http_referer
        self._x_title = x_title
        self._timeout = timeout

    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        if self._http_referer:
            headers["HTTP-Referer"] = self._http_referer
        if self._x_title:
            headers["X-Title"] = self._x_title
        return headers

    async def submit_video(
        self,
        *,
        model: str,
        prompt: str,
        aspect_ratio: str | None = None,
        duration_seconds: int | None = None,
        frame_images: list[dict[str, Any]] | None = None,
        reference_images: list[dict[str, Any]] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> VideoGeneration:
        body: dict[str, Any] = {"model": model, "prompt": prompt}
        if aspect_ratio is not None:
            body["aspect_ratio"] = aspect_ratio
        if duration_seconds is not None:
            body["duration"] = duration_seconds
        if frame_images is not None:
            body["frame_images"] = frame_images
        if reference_images is not None:
            body["reference_images"] = reference_images
        if extra:
            body.update(extra)

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                f"{self._base_url}/videos",
                headers=self._headers(),
                json=body,
            )
        if response.status_code >= 400:
            raise OpenRouterError(
                f"submit_video failed ({response.status_code}): {response.text}",
                status_code=response.status_code,
            )
        return _parse_video_response(response.json())

    async def poll_video(self, polling_url: str) -> VideoGeneration:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.get(polling_url, headers=self._headers())
        if response.status_code >= 400:
            raise OpenRouterError(
                f"poll_video failed ({response.status_code}): {response.text}",
                status_code=response.status_code,
            )
        return _parse_video_response(response.json())

    async def wait_for_video(
        self,
        polling_url: str,
        *,
        interval_seconds: float = 5.0,
        timeout_seconds: float = 600.0,
    ) -> VideoGeneration:
        """Poll until the video job reaches a terminal status or we time out."""
        deadline = asyncio.get_event_loop().time() + timeout_seconds
        while True:
            status = await self.poll_video(polling_url)
            if status.is_terminal:
                return status
            if asyncio.get_event_loop().time() >= deadline:
                raise OpenRouterError(
                    f"Video generation did not finish within {timeout_seconds}s"
                )
            await asyncio.sleep(interval_seconds)

    async def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float = 0.2,
        max_tokens: int | None = None,
        response_format: dict[str, Any] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if response_format is not None:
            body["response_format"] = response_format
        if extra:
            body.update(extra)
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                f"{self._base_url}/chat/completions",
                headers=self._headers(),
                json=body,
            )
        if response.status_code >= 400:
            raise OpenRouterError(
                f"chat failed ({response.status_code}): {response.text}",
                status_code=response.status_code,
            )
        result: dict[str, Any] = response.json()
        return result
