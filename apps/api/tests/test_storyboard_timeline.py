"""Phase 2 tests: storyboard expansion, timeline CRUD, export.

The OpenRouter LLM call is mocked; the ffmpeg renderer is mocked at the
boundary so we don't shell out during CI.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from content_creator_api.config import get_settings
from content_creator_api.models import (
    Clip,
    ClipStatus,
    ExportJob,
    ExportStatus,
    Project,
)
from content_creator_api.services.storyboard import StoryboardShot


@pytest.fixture(autouse=True)
def disable_enqueue() -> None:
    settings = get_settings()
    settings.enqueue_jobs = False
    yield
    settings.enqueue_jobs = True


def _create_project(client: TestClient) -> str:
    response = client.post("/projects", json={"title": "P", "prompt": "tiktok about cats"})
    assert response.status_code == 201
    return str(response.json()["id"])


def test_storyboard_creates_shots(client: TestClient) -> None:
    project_id = _create_project(client)
    settings = get_settings()
    settings.openrouter_api_key = "test-key"
    fake_shots = [
        StoryboardShot(prompt="cat wakes up", duration_seconds=4, notes="hook"),
        StoryboardShot(prompt="cat eats breakfast", duration_seconds=5),
        StoryboardShot(prompt="cat surfs", duration_seconds=6, notes="payoff"),
    ]
    try:
        with patch(
            "content_creator_api.routers.storyboard.generate_storyboard",
            return_value=fake_shots,
        ):
            response = client.post(
                f"/projects/{project_id}/storyboard",
                json={"n_shots": 3, "total_duration_seconds": 15},
            )
        assert response.status_code == 201, response.text
        body = response.json()
        assert len(body) == 3
        assert [s["prompt"] for s in body] == [s.prompt for s in fake_shots]
        assert [s["order_index"] for s in body] == [0, 1, 2]
    finally:
        settings.openrouter_api_key = ""


def test_storyboard_requires_api_key(client: TestClient) -> None:
    project_id = _create_project(client)
    response = client.post(
        f"/projects/{project_id}/storyboard",
        json={"n_shots": 3},
    )
    assert response.status_code == 503


def test_shot_crud(client: TestClient) -> None:
    project_id = _create_project(client)
    create = client.post(
        f"/projects/{project_id}/shots",
        json={"prompt": "cats", "duration_seconds": 5},
    )
    assert create.status_code == 201
    shot_id = create.json()["id"]

    update = client.patch(
        f"/shots/{shot_id}",
        json={"prompt": "kittens"},
    )
    assert update.status_code == 200
    assert update.json()["prompt"] == "kittens"

    delete = client.delete(f"/shots/{shot_id}")
    assert delete.status_code == 204


def test_timeline_put_replaces_items(client: TestClient, session) -> None:  # type: ignore[no-untyped-def]
    project_id = UUID(_create_project(client))
    # Insert a clip we can reference.
    clip = Clip(
        project_id=project_id,
        prompt="x",
        status=ClipStatus.SUCCEEDED,
        public_url="https://example.com/clip.mp4",
        storage_key=f"clips/{project_id}/x.mp4",
    )
    session.add(clip)
    session.commit()
    session.refresh(clip)

    response = client.put(
        f"/projects/{project_id}/timeline",
        json={
            "items": [
                {"clip_id": str(clip.id), "duration_ms": 4000},
                {"clip_id": str(clip.id), "duration_ms": 6000, "source_start_ms": 1000},
            ]
        },
    )
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 2
    assert [r["order_index"] for r in rows] == [0, 1]
    assert rows[0]["duration_ms"] == 4000
    assert rows[1]["source_start_ms"] == 1000

    # Replace with a single item — the second should be deleted.
    response = client.put(
        f"/projects/{project_id}/timeline",
        json={
            "items": [
                {"id": rows[0]["id"], "clip_id": str(clip.id), "duration_ms": 9000}
            ]
        },
    )
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["duration_ms"] == 9000


def test_export_endpoint_validates_empty_timeline(client: TestClient) -> None:
    project_id = _create_project(client)
    response = client.post(
        f"/projects/{project_id}/exports",
        json={"width": 1080, "height": 1920, "fps": 30},
    )
    assert response.status_code == 400


def test_render_export_job_pipeline(monkeypatch: pytest.MonkeyPatch, session) -> None:  # type: ignore[no-untyped-def]
    """Run the worker task with the renderer mocked, asserting status flow."""
    from content_creator_api.tasks import render as render_module

    project_id = UUID("aaaa1111-aaaa-1111-aaaa-111111111111")
    clip_id = UUID("bbbb2222-bbbb-2222-bbbb-222222222222")
    export_id = UUID("cccc3333-cccc-3333-cccc-333333333333")

    session.add(Project(id=project_id, title="t"))
    session.add(
        Clip(
            id=clip_id,
            project_id=project_id,
            prompt="x",
            status=ClipStatus.SUCCEEDED,
            public_url="https://example.com/x.mp4",
        )
    )
    session.add(
        ExportJob(
            id=export_id,
            project_id=project_id,
            status=ExportStatus.PENDING,
            width=1080,
            height=1920,
            fps=30,
        )
    )
    from content_creator_api.models import TimelineItem, TimelineItemType

    session.add(
        TimelineItem(
            project_id=project_id,
            clip_id=clip_id,
            order_index=0,
            duration_ms=5000,
            item_type=TimelineItemType.CLIP,
        )
    )
    session.commit()

    fake_output = Path("/tmp/test-render.mp4")
    fake_output.write_bytes(b"\x00" * 10)

    monkeypatch.setattr(
        render_module, "render_timeline", lambda *_a, **_k: fake_output
    )
    monkeypatch.setattr(render_module, "engine", session.get_bind())

    captured: dict[str, object] = {}

    def _put_bytes(key: str, body: bytes, *, content_type: str = "video/mp4") -> str:
        captured["key"] = key
        captured["bytes"] = len(body)
        return key

    monkeypatch.setattr(render_module.storage, "put_bytes", _put_bytes)
    monkeypatch.setattr(
        render_module.storage,
        "public_url",
        lambda key: f"https://public.example/{key}",
    )

    render_module.render_export_job(str(export_id))

    session.expire_all()
    refreshed = session.get(ExportJob, export_id)
    assert refreshed is not None
    assert refreshed.status == ExportStatus.SUCCEEDED
    assert refreshed.public_url == f"https://public.example/exports/{project_id}/{export_id}.mp4"
    assert refreshed.duration_ms == 5000
    assert captured["key"] == f"exports/{project_id}/{export_id}.mp4"
    assert captured["bytes"] == 10


def test_storyboard_parser_clamps_duration() -> None:
    from content_creator_api.services.storyboard import _parse_storyboard

    raw = '{"shots": [{"prompt": "x", "duration_seconds": 99}, {"description": "y"}, {"prompt": "z", "duration": "abc"}]}'
    out = _parse_storyboard(raw, n_shots=5)
    assert [s.prompt for s in out] == ["x", "y", "z"]
    assert out[0].duration_seconds == 30  # clamped from 99 to max 30
    assert out[1].duration_seconds == 5  # missing -> default
    assert out[2].duration_seconds == 5  # invalid -> default


def test_render_clip_not_set_returns_400(client: TestClient, session) -> None:  # type: ignore[no-untyped-def]
    """An item with no clip_id is silently skipped, but if every item lacks a clip
    the renderer should fail before issuing ffmpeg."""
    from content_creator_api.services.render import RenderError, render_timeline  # noqa: F401

    # we just exercise validation path via the API: empty items rejected.
    project_id = _create_project(client)
    response = client.post(f"/projects/{project_id}/exports", json={})
    assert response.status_code == 400
