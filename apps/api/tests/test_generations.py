"""Generation flow tests.

The HTTP layer is tested with the in-memory SQLite test client. RQ is
disabled via the ``enqueue_jobs=False`` config knob so creating a
generation just inserts the rows.

The clip pipeline (``generate_and_score_clip``) is tested by mocking the
OpenRouter client and the storage helper.
"""

from __future__ import annotations

import asyncio
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from content_creator_api.config import get_settings
from content_creator_api.models import (
    Clip,
    ClipStatus,
    GenerationJob,
    GenerationJobStatus,
)
from content_creator_api.services.openrouter import VideoGeneration


@pytest.fixture(autouse=True)
def disable_enqueue() -> None:
    settings = get_settings()
    settings.enqueue_jobs = False
    yield
    settings.enqueue_jobs = True


def _create_project(client: TestClient) -> str:
    response = client.post("/projects", json={"title": "Test", "prompt": "p"})
    assert response.status_code == 201
    return str(response.json()["id"])


def test_create_generation_inserts_pending_clips(client: TestClient) -> None:
    project_id = _create_project(client)

    response = client.post(
        f"/projects/{project_id}/generations",
        json={"prompt": "a cat surfing", "n_variants": 3, "duration_seconds": 5},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["project_id"] == project_id
    assert body["n_variants"] == 3
    assert body["status"] == "running"
    assert len(body["clips"]) == 3
    statuses = {c["status"] for c in body["clips"]}
    assert statuses == {"pending"}
    indexes = sorted(c["variant_index"] for c in body["clips"])
    assert indexes == [0, 1, 2]


def test_get_generation_returns_clips(client: TestClient) -> None:
    project_id = _create_project(client)
    create = client.post(
        f"/projects/{project_id}/generations",
        json={"prompt": "boats", "n_variants": 2},
    ).json()
    job_id = create["id"]

    response = client.get(f"/generations/{job_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == job_id
    assert len(body["clips"]) == 2


def test_set_winner(client: TestClient, session) -> None:  # type: ignore[no-untyped-def]
    project_id = _create_project(client)
    create = client.post(
        f"/projects/{project_id}/generations",
        json={"prompt": "x", "n_variants": 2},
    ).json()
    job_id = create["id"]
    clip_id = create["clips"][0]["id"]

    response = client.post(
        f"/generations/{job_id}/winner",
        json={"clip_id": clip_id},
    )
    assert response.status_code == 200
    assert response.json()["best_clip_id"] == clip_id


def test_create_generation_unknown_project_404(client: TestClient) -> None:
    response = client.post(
        "/projects/00000000-0000-0000-0000-000000000000/generations",
        json={"prompt": "x"},
    )
    assert response.status_code == 404


def test_clip_pipeline_happy_path(monkeypatch: pytest.MonkeyPatch, session) -> None:  # type: ignore[no-untyped-def]
    """Run the worker task end-to-end with the OpenRouter + storage layer mocked."""
    from content_creator_api.tasks import generation as gen_module

    project_id = UUID("11111111-1111-1111-1111-111111111111")
    job_id = UUID("22222222-2222-2222-2222-222222222222")
    clip_id = UUID("33333333-3333-3333-3333-333333333333")

    # Insert fixtures directly via the test session.
    from content_creator_api.models import Project

    session.add(Project(id=project_id, title="t"))
    session.add(
        GenerationJob(
            id=job_id,
            project_id=project_id,
            prompt="cats",
            n_variants=1,
            model="bytedance/seedance-2.0",
            status=GenerationJobStatus.RUNNING,
        )
    )
    session.add(
        Clip(
            id=clip_id,
            project_id=project_id,
            generation_job_id=job_id,
            prompt="cats",
            variant_index=0,
        )
    )
    session.commit()

    # Mocks
    submit_response = VideoGeneration(
        id="vid_abc",
        status="in_progress",
        polling_url="https://or.example/poll/vid_abc",
        unsigned_urls=[],
        cost_usd=None,
        error=None,
    )
    finished = VideoGeneration(
        id="vid_abc",
        status="completed",
        polling_url="https://or.example/poll/vid_abc",
        unsigned_urls=["https://or.example/output/vid_abc.mp4"],
        cost_usd=0.12,
        error=None,
    )

    class _MockClient:
        def __init__(self, *_: object, **__: object) -> None:
            pass

        async def submit_video(self, **_: object) -> VideoGeneration:
            return submit_response

        async def wait_for_video(self, *_: object, **__: object) -> VideoGeneration:
            return finished

        async def chat(self, **_: object) -> dict:  # type: ignore[type-arg]
            return {"choices": [{"message": {"content": '{"score": 87, "explanation": "good"}'}}]}

    monkeypatch.setattr(gen_module, "OpenRouterClient", _MockClient)

    upload_calls: list[tuple[str, str]] = []

    def _fake_upload(url: str, key: str, *, content_type: str = "video/mp4") -> int:
        upload_calls.append((url, key))
        return 1024

    monkeypatch.setattr(gen_module.storage, "upload_from_url", _fake_upload)
    monkeypatch.setattr(
        gen_module.storage,
        "presigned_get_url",
        lambda key, **_: f"https://signed.example/{key}",
    )
    monkeypatch.setattr(
        gen_module.storage, "public_url", lambda key: f"https://public.example/{key}"
    )

    # Patch the worker's engine to use our test session's engine.
    monkeypatch.setattr(gen_module, "engine", session.get_bind())

    asyncio.run(gen_module._run_clip(clip_id))

    session.expire_all()
    refreshed = session.get(Clip, clip_id)
    assert refreshed is not None
    assert refreshed.status == ClipStatus.SUCCEEDED
    assert refreshed.score == 87.0
    assert refreshed.score_explanation == "good"
    assert refreshed.public_url == f"https://public.example/clips/{project_id}/{clip_id}.mp4"
    assert refreshed.cost_usd == 0.12
    assert upload_calls == [
        (
            "https://or.example/output/vid_abc.mp4",
            f"clips/{project_id}/{clip_id}.mp4",
        )
    ]

    refreshed_job = session.get(GenerationJob, job_id)
    assert refreshed_job is not None
    assert refreshed_job.status == GenerationJobStatus.SUCCEEDED
    assert refreshed_job.best_clip_id == clip_id
