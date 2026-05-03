"""TTS / voice-cloning provider abstraction.

A ``TTSProvider`` knows how to:
1. Register a voice clone from a sample audio file (``register_voice``).
2. Synthesize speech from a script using a registered voice
   (``synthesize``), returning audio bytes plus a content-type and
   duration estimate.

Three concrete providers are shipped:

* ``F5TTSProvider`` — the self-hosted default. Talks to a sidecar HTTP
  service that wraps the F5-TTS reference inference script. The sidecar
  contract is intentionally tiny so it can be implemented in <100 lines.
* ``ElevenLabsProvider`` — production option. Hits the ElevenLabs
  Instant Voice Clone + TTS endpoints.
* ``ReplicateProvider`` — runs F5-TTS on Replicate when there is no
  local GPU.

The factory ``get_provider()`` reads ``settings.tts_provider``.
"""

from __future__ import annotations

import asyncio
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import httpx

from content_creator_api.config import Settings, get_settings

log = logging.getLogger(__name__)


class TTSError(RuntimeError):
    """Raised when a TTS provider call fails."""


@dataclass(slots=True)
class VoiceRegistration:
    provider_voice_id: str
    notes: str | None = None


@dataclass(slots=True)
class SynthesizedAudio:
    audio: bytes
    content_type: str = "audio/mpeg"
    duration_ms: int | None = None


class TTSProvider(ABC):
    name: str = "abstract"

    @abstractmethod
    async def register_voice(
        self,
        *,
        sample_audio: bytes,
        sample_content_type: str,
        name: str,
        reference_text: str | None,
    ) -> VoiceRegistration:
        ...

    @abstractmethod
    async def synthesize(
        self,
        *,
        provider_voice_id: str,
        script: str,
        sample_audio: bytes | None = None,
        sample_content_type: str | None = None,
        reference_text: str | None = None,
    ) -> SynthesizedAudio:
        ...


# --- F5-TTS sidecar ---------------------------------------------------


class F5TTSProvider(TTSProvider):
    """Talks to a self-hosted F5-TTS sidecar over HTTP.

    Sidecar contract:

      POST {base}/voices  (multipart: audio, name, reference_text)
        -> {"voice_id": "..."}

      POST {base}/synthesize  (json: voice_id, script, [reference_text])
        -> audio/wav (or audio/mpeg) bytes
    """

    name = "f5tts"

    def __init__(self, base_url: str, *, timeout: float = 600.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    async def register_voice(
        self,
        *,
        sample_audio: bytes,
        sample_content_type: str,
        name: str,
        reference_text: str | None,
    ) -> VoiceRegistration:
        if not self._base_url:
            raise TTSError("F5_TTS_BASE_URL is not configured")
        files = {"audio": ("sample.wav", sample_audio, sample_content_type)}
        data: dict[str, str] = {"name": name}
        if reference_text:
            data["reference_text"] = reference_text
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                f"{self._base_url}/voices", files=files, data=data
            )
        if response.status_code >= 400:
            raise TTSError(f"f5tts.register failed: {response.status_code} {response.text}")
        body = response.json()
        return VoiceRegistration(
            provider_voice_id=str(body.get("voice_id") or body.get("id") or "")
        )

    async def synthesize(
        self,
        *,
        provider_voice_id: str,
        script: str,
        sample_audio: bytes | None = None,
        sample_content_type: str | None = None,
        reference_text: str | None = None,
    ) -> SynthesizedAudio:
        if not self._base_url:
            raise TTSError("F5_TTS_BASE_URL is not configured")
        payload: dict[str, Any] = {
            "voice_id": provider_voice_id,
            "script": script,
        }
        if reference_text:
            payload["reference_text"] = reference_text
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                f"{self._base_url}/synthesize", json=payload
            )
        if response.status_code >= 400:
            raise TTSError(
                f"f5tts.synthesize failed: {response.status_code} {response.text[:500]}"
            )
        return SynthesizedAudio(
            audio=response.content,
            content_type=response.headers.get("content-type", "audio/wav"),
        )


# --- ElevenLabs --------------------------------------------------------


class ElevenLabsProvider(TTSProvider):
    """Hits ElevenLabs Instant Voice Clone + TTS endpoints."""

    name = "elevenlabs"

    def __init__(
        self, api_key: str, *, base_url: str = "https://api.elevenlabs.io/v1"
    ) -> None:
        if not api_key:
            raise TTSError("ELEVENLABS_API_KEY is not set")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")

    def _headers(self, *, json_body: bool = False) -> dict[str, str]:
        h = {"xi-api-key": self._api_key}
        if json_body:
            h["accept"] = "audio/mpeg"
            h["content-type"] = "application/json"
        return h

    async def register_voice(
        self,
        *,
        sample_audio: bytes,
        sample_content_type: str,
        name: str,
        reference_text: str | None,
    ) -> VoiceRegistration:
        files = {"files": ("sample.wav", sample_audio, sample_content_type)}
        data: dict[str, str] = {"name": name}
        if reference_text:
            data["description"] = reference_text
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{self._base_url}/voices/add",
                files=files,
                data=data,
                headers=self._headers(),
            )
        if response.status_code >= 400:
            raise TTSError(
                f"elevenlabs.register failed: {response.status_code} {response.text[:500]}"
            )
        body = response.json()
        voice_id = body.get("voice_id") or body.get("id")
        if not voice_id:
            raise TTSError("elevenlabs.register: missing voice_id in response")
        return VoiceRegistration(provider_voice_id=str(voice_id))

    async def synthesize(
        self,
        *,
        provider_voice_id: str,
        script: str,
        sample_audio: bytes | None = None,
        sample_content_type: str | None = None,
        reference_text: str | None = None,
    ) -> SynthesizedAudio:
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.post(
                f"{self._base_url}/text-to-speech/{provider_voice_id}",
                json={"text": script, "model_id": "eleven_turbo_v2_5"},
                headers=self._headers(json_body=True),
            )
        if response.status_code >= 400:
            raise TTSError(
                f"elevenlabs.synthesize failed: {response.status_code} {response.text[:500]}"
            )
        return SynthesizedAudio(audio=response.content, content_type="audio/mpeg")


# --- Replicate (F5-TTS hosted) ----------------------------------------


class ReplicateProvider(TTSProvider):
    """Replicate-hosted F5-TTS. Skips the registration step (Replicate
    treats the sample audio as input on every synthesis call).
    """

    name = "replicate"

    def __init__(
        self,
        api_token: str,
        *,
        model: str = "lucataco/f5-tts:latest",
        base_url: str = "https://api.replicate.com/v1",
    ) -> None:
        if not api_token:
            raise TTSError("REPLICATE_API_TOKEN is not set")
        self._api_token = api_token
        self._model = model
        self._base_url = base_url.rstrip("/")

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Token {self._api_token}",
            "Content-Type": "application/json",
        }

    async def register_voice(
        self,
        *,
        sample_audio: bytes,
        sample_content_type: str,
        name: str,
        reference_text: str | None,
    ) -> VoiceRegistration:
        # Replicate has no concept of a registered voice for F5-TTS — the
        # sample is supplied per-call. We mint a synthetic id so the rest
        # of our pipeline doesn't have to special-case None.
        return VoiceRegistration(
            provider_voice_id=f"replicate:{name}",
            notes="replicate provider passes the sample on every synthesis",
        )

    async def synthesize(
        self,
        *,
        provider_voice_id: str,
        script: str,
        sample_audio: bytes | None = None,
        sample_content_type: str | None = None,
        reference_text: str | None = None,
    ) -> SynthesizedAudio:
        if sample_audio is None:
            raise TTSError("replicate provider requires sample_audio per call")
        # Replicate accepts file uploads via a multipart endpoint then
        # references the returned URL as a model input.
        async with httpx.AsyncClient(timeout=300.0) as client:
            upload = await client.post(
                f"{self._base_url}/files",
                files={
                    "content": (
                        "sample.wav",
                        sample_audio,
                        sample_content_type or "audio/wav",
                    )
                },
                headers={"Authorization": f"Token {self._api_token}"},
            )
            if upload.status_code >= 400:
                raise TTSError(
                    f"replicate.upload failed: {upload.status_code} {upload.text[:500]}"
                )
            upload_url = upload.json().get("urls", {}).get("get")
            if not upload_url:
                raise TTSError("replicate.upload missing urls.get in response")

            payload = {
                "version": self._model,
                "input": {
                    "gen_text": script,
                    "ref_audio": upload_url,
                    "ref_text": reference_text or "",
                },
            }
            create = await client.post(
                f"{self._base_url}/predictions",
                json=payload,
                headers=self._headers(),
            )
            if create.status_code >= 400:
                raise TTSError(
                    f"replicate.create failed: {create.status_code} {create.text[:500]}"
                )
            prediction = create.json()
            poll_url = prediction.get("urls", {}).get("get")
            if not poll_url:
                raise TTSError("replicate.create missing urls.get in response")

            for _ in range(120):  # ~10 minutes max
                poll = await client.get(poll_url, headers=self._headers())
                snap = poll.json()
                status = snap.get("status")
                if status == "succeeded":
                    output = snap.get("output")
                    audio_url = output if isinstance(output, str) else (
                        output[0] if isinstance(output, list) and output else None
                    )
                    if not audio_url:
                        raise TTSError("replicate prediction had no audio output")
                    audio = await client.get(audio_url)
                    if audio.status_code >= 400:
                        raise TTSError(
                            f"replicate.audio fetch {audio.status_code}"
                        )
                    return SynthesizedAudio(
                        audio=audio.content,
                        content_type=audio.headers.get(
                            "content-type", "audio/wav"
                        ),
                    )
                if status in ("failed", "canceled"):
                    raise TTSError(
                        f"replicate prediction {status}: {snap.get('error')}"
                    )
                await asyncio.sleep(5)
            raise TTSError("replicate prediction timed out")


# --- Factory ----------------------------------------------------------


def get_provider(settings: Settings | None = None) -> TTSProvider:
    settings = settings or get_settings()
    name = (settings.tts_provider or "f5tts").lower()
    if name == "f5tts":
        # Honor either the typed setting or a plain env var so users who
        # leave the typed default in place can still configure the
        # sidecar URL with one knob.
        base_url = os.environ.get("F5_TTS_BASE_URL", "")
        return F5TTSProvider(base_url=base_url)
    if name == "elevenlabs":
        return ElevenLabsProvider(api_key=settings.elevenlabs_api_key)
    if name == "replicate":
        return ReplicateProvider(api_token=settings.replicate_api_token)
    raise TTSError(f"unknown tts provider: {name}")
