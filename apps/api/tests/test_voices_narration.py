"""Phase 3 tests: voice cloning + narration synthesis + captions.

The TTS providers are mocked at the abstraction boundary; the storage
helper is monkeypatched so we never hit MinIO from CI.
"""

from __future__ import annotations

import io
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from content_creator_api.config import get_settings
from content_creator_api.models import (
    NarrationJob,
    NarrationStatus,
    Project,
    VoiceProfile,
    VoiceStatus,
)
from content_creator_api.services import storage
from content_creator_api.services.captions import (
    CaptionSegment,
    captions_from_json,
    captions_to_json,
    rough_captions,
)
from content_creator_api.services.tts import (
    SynthesizedAudio,
    TTSError,
    TTSProvider,
    VoiceRegistration,
)


@pytest.fixture(autouse=True)
def disable_enqueue() -> None:
    settings = get_settings()
    settings.enqueue_jobs = False
    yield
    settings.enqueue_jobs = True


@pytest.fixture(autouse=True)
def stub_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make storage helpers no-ops so the routes don't need MinIO."""
    settings = get_settings()
    monkeypatch.setattr(settings, "s3_endpoint_url", "")
    monkeypatch.setattr(storage, "put_bytes", lambda *a, **k: a[0])
    monkeypatch.setattr(storage, "get_bytes", lambda *_a, **_k: b"WAV-BYTES")
    monkeypatch.setattr(
        storage, "public_url", lambda key: f"https://public.example/{key}"
    )


def test_rough_captions_distribute_evenly() -> None:
    script = "First sentence here. Second slightly longer one. Third!"
    out = rough_captions(script, 6000)
    assert len(out) == 3
    assert out[0].start_ms == 0
    assert out[-1].end_ms == 6000
    # monotonic
    for prev, nxt in zip(out, out[1:], strict=False):
        assert prev.end_ms == nxt.start_ms
        assert prev.text


def test_captions_roundtrip() -> None:
    segments = [CaptionSegment(0, 1000, "hi"), CaptionSegment(1000, 2000, "yo")]
    blob = captions_to_json(segments)
    parsed = captions_from_json(blob)
    assert parsed == segments


def test_create_voice_endpoint(client: TestClient) -> None:
    audio_bytes = b"RIFFfake-wav-payload"
    response = client.post(
        "/voices",
        data={"name": "MyVoice", "reference_text": "hello world"},
        files={"audio": ("sample.wav", io.BytesIO(audio_bytes), "audio/wav")},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["name"] == "MyVoice"
    assert body["status"] == VoiceStatus.PENDING
    assert body["sample_storage_key"]


def test_create_voice_rejects_empty_audio(client: TestClient) -> None:
    response = client.post(
        "/voices",
        data={"name": "x"},
        files={"audio": ("sample.wav", io.BytesIO(b""), "audio/wav")},
    )
    assert response.status_code == 400


def test_narration_requires_ready_voice(client: TestClient, session) -> None:  # type: ignore[no-untyped-def]
    project = Project(title="P")
    voice = VoiceProfile(name="v", status=VoiceStatus.PENDING)
    session.add(project)
    session.add(voice)
    session.commit()
    session.refresh(project)
    session.refresh(voice)

    response = client.post(
        f"/projects/{project.id}/narrations",
        json={"voice_id": str(voice.id), "script": "hello"},
    )
    assert response.status_code == 409


def test_narration_create_and_pipeline(monkeypatch: pytest.MonkeyPatch, session) -> None:  # type: ignore[no-untyped-def]
    """End-to-end: create voice (READY) → create narration → run worker
    task → assert audio key + duration + captions present.
    """
    from content_creator_api.tasks import narration as narration_task

    project = Project(id=UUID("aaaa1111-aaaa-1111-aaaa-111111111111"), title="P")
    voice = VoiceProfile(
        id=UUID("bbbb2222-bbbb-2222-bbbb-222222222222"),
        name="v",
        status=VoiceStatus.READY,
        provider="f5tts",
        provider_voice_id="elevenlabs-or-f5-id",
        sample_storage_key="voices/v/sample.wav",
        reference_text="ref",
    )
    narration = NarrationJob(
        id=UUID("cccc3333-cccc-3333-cccc-333333333333"),
        project_id=project.id,
        voice_id=voice.id,
        script="One. Two longer one. Three!",
        status=NarrationStatus.PENDING,
    )
    session.add(project)
    session.add(voice)
    session.add(narration)
    session.commit()

    fake_provider = MagicMock(spec=TTSProvider)
    fake_provider.name = "f5tts"
    fake_provider.synthesize = AsyncMock(
        return_value=SynthesizedAudio(
            audio=b"\x00" * 6000,  # ~2s @3kB/s heuristic
            content_type="audio/mpeg",
            duration_ms=4500,
        )
    )

    monkeypatch.setattr(narration_task, "get_provider", lambda *_a, **_k: fake_provider)
    monkeypatch.setattr(narration_task, "engine", session.get_bind())
    # Re-enable the storage upload path (the autouse fixture clears it).
    settings = get_settings()
    monkeypatch.setattr(settings, "s3_endpoint_url", "http://stub:9000")

    captured: dict[str, object] = {}

    def _put_bytes(key: str, body: bytes, *, content_type: str = "audio/mpeg") -> str:
        captured["key"] = key
        captured["bytes"] = len(body)
        return key

    monkeypatch.setattr(narration_task.storage, "put_bytes", _put_bytes)
    monkeypatch.setattr(
        narration_task.storage,
        "public_url",
        lambda key: f"https://public.example/{key}",
    )

    narration_task.synthesize_narration_job(str(narration.id))

    session.expire_all()
    refreshed = session.get(NarrationJob, narration.id)
    assert refreshed is not None
    assert refreshed.status == NarrationStatus.SUCCEEDED
    assert refreshed.duration_ms == 4500
    assert refreshed.public_url and refreshed.public_url.endswith(".mp3")
    assert captured["key"] == f"narration/{project.id}/{narration.id}.mp3"
    assert refreshed.captions_json
    segments = captions_from_json(refreshed.captions_json)
    assert len(segments) == 3
    assert segments[-1].end_ms == 4500


def test_register_voice_pipeline(monkeypatch: pytest.MonkeyPatch, session) -> None:  # type: ignore[no-untyped-def]
    from content_creator_api.tasks import narration as narration_task

    voice = VoiceProfile(
        id=UUID("dddd4444-dddd-4444-dddd-444444444444"),
        name="v",
        sample_storage_key="voices/v/sample.wav",
        status=VoiceStatus.PENDING,
    )
    session.add(voice)
    session.commit()

    fake_provider = MagicMock(spec=TTSProvider)
    fake_provider.name = "f5tts"
    fake_provider.register_voice = AsyncMock(
        return_value=VoiceRegistration(provider_voice_id="provider-voice-1")
    )

    monkeypatch.setattr(narration_task, "get_provider", lambda *_a, **_k: fake_provider)
    monkeypatch.setattr(narration_task, "engine", session.get_bind())

    narration_task.register_voice_profile(str(voice.id))
    session.expire_all()
    refreshed = session.get(VoiceProfile, voice.id)
    assert refreshed is not None
    assert refreshed.status == VoiceStatus.READY
    assert refreshed.provider_voice_id == "provider-voice-1"


def test_register_voice_failure_marks_voice_failed(
    monkeypatch: pytest.MonkeyPatch, session
) -> None:  # type: ignore[no-untyped-def]
    from content_creator_api.tasks import narration as narration_task

    voice = VoiceProfile(
        id=UUID("eeee5555-eeee-5555-eeee-555555555555"),
        name="v",
        sample_storage_key="voices/v/sample.wav",
        status=VoiceStatus.PENDING,
    )
    session.add(voice)
    session.commit()

    fake_provider = MagicMock(spec=TTSProvider)
    fake_provider.name = "f5tts"
    fake_provider.register_voice = AsyncMock(side_effect=TTSError("nope"))

    monkeypatch.setattr(narration_task, "get_provider", lambda *_a, **_k: fake_provider)
    monkeypatch.setattr(narration_task, "engine", session.get_bind())

    narration_task.register_voice_profile(str(voice.id))
    session.expire_all()
    refreshed = session.get(VoiceProfile, voice.id)
    assert refreshed is not None
    assert refreshed.status == VoiceStatus.FAILED
    assert refreshed.error and "nope" in refreshed.error
