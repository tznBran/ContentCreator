"""RQ tasks for voice cloning + narration generation."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlmodel import Session

from content_creator_api.config import get_settings
from content_creator_api.db import engine
from content_creator_api.models import (
    NarrationJob,
    NarrationStatus,
    VoiceProfile,
    VoiceStatus,
)
from content_creator_api.services import storage
from content_creator_api.services.captions import (
    captions_to_json,
    rough_captions,
)
from content_creator_api.services.tts import TTSError, get_provider

log = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


def register_voice_profile(voice_id: str) -> None:
    job_id = UUID(voice_id)
    settings = get_settings()
    with Session(engine) as session:
        voice = session.get(VoiceProfile, job_id)
        if voice is None:
            log.warning("voice.missing %s", voice_id)
            return
        try:
            if voice.sample_storage_key is None:
                raise TTSError("voice has no sample uploaded")
            sample = storage.get_bytes(voice.sample_storage_key)
            provider = get_provider(settings)
            voice.provider = provider.name
            registration = asyncio.run(
                provider.register_voice(
                    sample_audio=sample,
                    sample_content_type="audio/wav",
                    name=voice.name,
                    reference_text=voice.reference_text,
                )
            )
            voice.provider_voice_id = registration.provider_voice_id
            voice.status = VoiceStatus.READY
            voice.updated_at = _now()
            session.add(voice)
            session.commit()
        except Exception as exc:
            log.exception("voice.register failed %s", voice_id)
            voice.status = VoiceStatus.FAILED
            voice.error = str(exc)[:2000]
            voice.updated_at = _now()
            session.add(voice)
            session.commit()


def _estimate_duration_ms(audio: bytes, content_type: str) -> int:
    """Best-effort duration estimate without a real decoder.

    For mp3 we assume ~24 kbps spoken-voice rate (~3 kB/s); for wav we
    parse the canonical RIFF header. The RQ task lives outside the
    request path, so being approximate is fine — the captions schedule
    just needs a reasonable total.
    """
    ct = (content_type or "").lower()
    if ct.startswith("audio/wav") and len(audio) > 44:
        try:
            byte_rate = int.from_bytes(audio[28:32], "little")
            data_size = int.from_bytes(audio[40:44], "little")
            if byte_rate > 0:
                return round(data_size / byte_rate * 1000)
        except Exception:
            pass
    # Default fallback: ~3 kB/s for spoken audio.
    return max(1000, round(len(audio) / 3000 * 1000))


def synthesize_narration_job(narration_id: str) -> None:
    """Synthesize the narration audio + write rough captions."""
    job_id = UUID(narration_id)
    settings = get_settings()
    with Session(engine) as session:
        narration = session.get(NarrationJob, job_id)
        if narration is None:
            log.warning("narration.missing %s", narration_id)
            return
        try:
            narration.status = NarrationStatus.SYNTHESIZING
            narration.updated_at = _now()
            session.add(narration)
            session.commit()

            voice = (
                session.get(VoiceProfile, narration.voice_id)
                if narration.voice_id
                else None
            )
            if voice is None or voice.provider_voice_id is None:
                raise TTSError("narration requires a ready voice")

            sample_bytes: bytes | None = None
            if voice.sample_storage_key:
                try:
                    sample_bytes = storage.get_bytes(voice.sample_storage_key)
                except Exception:
                    sample_bytes = None

            provider = get_provider(settings)
            audio = asyncio.run(
                provider.synthesize(
                    provider_voice_id=voice.provider_voice_id,
                    script=narration.script,
                    sample_audio=sample_bytes,
                    sample_content_type="audio/wav",
                    reference_text=voice.reference_text,
                )
            )

            narration.status = NarrationStatus.UPLOADING
            narration.updated_at = _now()
            session.add(narration)
            session.commit()

            ext = ".wav" if "wav" in audio.content_type else ".mp3"
            key = f"narration/{narration.project_id}/{narration.id}{ext}"
            if settings.s3_endpoint_url:
                storage.put_bytes(key, audio.audio, content_type=audio.content_type)

            duration_ms = audio.duration_ms or _estimate_duration_ms(
                audio.audio, audio.content_type
            )
            segments = rough_captions(narration.script, duration_ms)

            narration.storage_key = key
            narration.public_url = storage.public_url(key)
            narration.duration_ms = duration_ms
            narration.captions_json = captions_to_json(segments)
            narration.status = NarrationStatus.SUCCEEDED
            narration.updated_at = _now()
            session.add(narration)
            session.commit()
        except Exception as exc:
            log.exception("narration.failed %s", narration_id)
            narration.status = NarrationStatus.FAILED
            narration.error = str(exc)[:2000]
            narration.updated_at = _now()
            session.add(narration)
            session.commit()
