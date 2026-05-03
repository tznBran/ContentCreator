"""Phase 4 tests: OAuth + multi-platform publishing.

We don't make any real network calls. The OAuth helpers are tested
by stubbing httpx via ``transport=MockTransport``, and the publisher
abstraction is exercised in the worker task with a fully mocked
publisher impl.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import httpx
import pytest
from fastapi.testclient import TestClient

from content_creator_api.config import get_settings
from content_creator_api.models import (
    ExportJob,
    ExportStatus,
    Project,
    PublishJob,
    PublishStatus,
    PublishVisibility,
    SocialAccount,
    SocialPlatform,
)
from content_creator_api.services import storage
from content_creator_api.services.oauth import (
    OAuthError,
    YouTubeOAuth,
    decode_extra,
    encode_extra,
    get_oauth_client,
)
from content_creator_api.services.publishers import (
    PublishMetadata,
    PublishResult,
    get_publisher,
)


@pytest.fixture(autouse=True)
def disable_enqueue() -> None:
    settings = get_settings()
    settings.enqueue_jobs = False
    yield
    settings.enqueue_jobs = True


@pytest.fixture(autouse=True)
def stub_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(storage, "put_bytes", lambda *a, **k: a[0])
    monkeypatch.setattr(storage, "get_bytes", lambda *_a, **_k: b"MP4-BYTES")
    monkeypatch.setattr(
        storage, "public_url", lambda key: f"https://public.example/{key}"
    )


def test_oauth_extra_roundtrip() -> None:
    blob = encode_extra({"channel_id": "abc"})
    assert decode_extra(blob) == {"channel_id": "abc"}
    assert decode_extra(None) == {}
    assert decode_extra("not-json") == {}


def test_youtube_authorize_url_includes_required_params() -> None:
    settings = get_settings()
    settings.youtube_client_id = "client-id"
    client = YouTubeOAuth(settings)
    url = client.authorize_url("statevalue")
    assert "client_id=client-id" in url
    assert "scope=" in url and "youtube.upload" in url
    assert "state=statevalue" in url
    assert "access_type=offline" in url


def test_oauth_start_endpoint(client: TestClient) -> None:
    settings = get_settings()
    settings.youtube_client_id = "yt"
    settings.youtube_client_secret = "yt-secret"
    response = client.get("/oauth/youtube/start")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state"]
    assert "accounts.google.com" in body["authorize_url"]


def test_oauth_unknown_platform_rejected(client: TestClient) -> None:
    response = client.get("/oauth/myspace/start")
    assert response.status_code == 422


def test_oauth_callback_persists_account(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stub the OAuth client so we don't hit Google."""
    from content_creator_api.routers import publishing as publishing_router
    from content_creator_api.services.oauth import OAuthAccountInfo, OAuthTokens

    fake = MagicMock()
    fake.exchange_code = AsyncMock(
        return_value=OAuthTokens(
            access_token="access-1",
            refresh_token="refresh-1",
            expires_at=datetime(2099, 1, 1, tzinfo=UTC),
            scope="youtube.upload",
        )
    )
    fake.account_info = AsyncMock(
        return_value=OAuthAccountInfo(
            external_id="UC-channel-1",
            account_name="My Channel",
            extra={"channel_id": "UC-channel-1"},
        )
    )
    monkeypatch.setattr(
        publishing_router, "get_oauth_client", lambda *_a, **_k: fake
    )

    response = client.get(
        "/oauth/youtube/callback",
        params={"code": "auth-code"},
        follow_redirects=False,
    )
    assert response.status_code in {302, 307}
    assert "connected=youtube" in response.headers["location"]

    # Verify a SocialAccount row was created.
    accounts = client.get("/accounts").json()
    assert len(accounts) == 1
    assert accounts[0]["platform"] == SocialPlatform.YOUTUBE
    assert accounts[0]["account_name"] == "My Channel"


def test_oauth_callback_redirects_on_error(client: TestClient) -> None:
    response = client.get(
        "/oauth/youtube/callback",
        params={"error": "access_denied"},
        follow_redirects=False,
    )
    assert response.status_code in {302, 307}
    assert "oauth_error=access_denied" in response.headers["location"]


def test_publish_create_validates_account_platform(
    client: TestClient, session, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    project = Project(title="P")
    export = ExportJob(
        project_id=UUID("11111111-1111-1111-1111-111111111111"),
        status=ExportStatus.SUCCEEDED,
        storage_key="exports/x.mp4",
        public_url="https://public.example/exports/x.mp4",
    )
    account = SocialAccount(
        platform=SocialPlatform.TIKTOK,
        account_name="me",
        external_id="ext",
        access_token="tok",
    )
    session.add(project)
    session.commit()
    session.refresh(project)
    export.project_id = project.id
    session.add(export)
    session.add(account)
    session.commit()

    response = client.post(
        f"/projects/{project.id}/publishes",
        json={
            "export_id": str(export.id),
            "account_id": str(account.id),
            "platform": SocialPlatform.YOUTUBE,
            "title": "hi",
        },
    )
    assert response.status_code == 400
    assert "platform" in response.text


def test_publish_create_and_pipeline(
    monkeypatch: pytest.MonkeyPatch, session
) -> None:  # type: ignore[no-untyped-def]
    """Full happy path: create publish row, run worker task with mocked
    publisher, assert state transitions."""
    from content_creator_api.tasks import publish as publish_task

    project = Project(id=UUID("22222222-2222-2222-2222-222222222222"), title="P")
    export = ExportJob(
        id=UUID("33333333-3333-3333-3333-333333333333"),
        project_id=project.id,
        status=ExportStatus.SUCCEEDED,
        storage_key="exports/final.mp4",
        public_url="https://public.example/exports/final.mp4",
    )
    account = SocialAccount(
        id=UUID("44444444-4444-4444-4444-444444444444"),
        platform=SocialPlatform.YOUTUBE,
        account_name="ch",
        external_id="UC-1",
        access_token="tok",
    )
    job = PublishJob(
        id=UUID("55555555-5555-5555-5555-555555555555"),
        project_id=project.id,
        export_id=export.id,
        account_id=account.id,
        platform=SocialPlatform.YOUTUBE,
        title="My video",
        description="hello",
        visibility=PublishVisibility.PRIVATE,
        status=PublishStatus.PENDING,
    )
    session.add(project)
    session.add(export)
    session.add(account)
    session.add(job)
    session.commit()

    fake_publisher = MagicMock()
    fake_publisher.publish = AsyncMock(
        return_value=PublishResult(
            platform_media_id="yt-vid-id",
            platform_url="https://www.youtube.com/watch?v=yt-vid-id",
        )
    )
    monkeypatch.setattr(
        publish_task, "get_publisher", lambda *_a, **_k: fake_publisher
    )
    monkeypatch.setattr(publish_task, "engine", session.get_bind())

    captured: dict[str, object] = {}

    async def _capture(**kwargs: object) -> PublishResult:
        captured["account_id"] = kwargs["account"].id  # type: ignore[union-attr]
        captured["video_bytes"] = kwargs["video_bytes"]
        captured["metadata"] = kwargs["metadata"]
        return PublishResult(
            platform_media_id="yt-vid-id",
            platform_url="https://www.youtube.com/watch?v=yt-vid-id",
        )

    fake_publisher.publish = _capture
    publish_task.publish_video(str(job.id))
    session.expire_all()

    refreshed = session.get(PublishJob, job.id)
    assert refreshed is not None
    assert refreshed.status == PublishStatus.SUCCEEDED
    assert refreshed.platform_media_id == "yt-vid-id"
    assert refreshed.platform_url is not None
    assert "yt-vid-id" in refreshed.platform_url
    assert captured["account_id"] == account.id
    assert captured["video_bytes"] == b"MP4-BYTES"
    metadata = captured["metadata"]
    assert isinstance(metadata, PublishMetadata)
    assert metadata.visibility == PublishVisibility.PRIVATE


def test_publish_pipeline_failure_marks_job_failed(
    monkeypatch: pytest.MonkeyPatch, session
) -> None:  # type: ignore[no-untyped-def]
    from content_creator_api.services.publishers import PublisherError
    from content_creator_api.tasks import publish as publish_task

    project = Project(id=UUID("66666666-6666-6666-6666-666666666666"), title="P")
    export = ExportJob(
        id=UUID("77777777-7777-7777-7777-777777777777"),
        project_id=project.id,
        status=ExportStatus.SUCCEEDED,
        storage_key="exports/final.mp4",
    )
    account = SocialAccount(
        id=UUID("88888888-8888-8888-8888-888888888888"),
        platform=SocialPlatform.YOUTUBE,
        account_name="ch",
        external_id="UC-1",
        access_token="tok",
    )
    job = PublishJob(
        id=UUID("99999999-9999-9999-9999-999999999999"),
        project_id=project.id,
        export_id=export.id,
        account_id=account.id,
        platform=SocialPlatform.YOUTUBE,
        title="x",
        status=PublishStatus.PENDING,
    )
    session.add(project)
    session.add(export)
    session.add(account)
    session.add(job)
    session.commit()

    fake_publisher = MagicMock()
    fake_publisher.publish = AsyncMock(side_effect=PublisherError("nope"))
    monkeypatch.setattr(
        publish_task, "get_publisher", lambda *_a, **_k: fake_publisher
    )
    monkeypatch.setattr(publish_task, "engine", session.get_bind())

    publish_task.publish_video(str(job.id))
    session.expire_all()
    refreshed = session.get(PublishJob, job.id)
    assert refreshed is not None
    assert refreshed.status == PublishStatus.FAILED
    assert refreshed.error and "nope" in refreshed.error


def test_youtube_oauth_exchange_code(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercise OAuthClient.exchange_code with httpx MockTransport."""
    settings = get_settings()
    settings.youtube_client_id = "yt"
    settings.youtube_client_secret = "yt-secret"

    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = request.content.decode()
        return httpx.Response(
            200,
            json={
                "access_token": "tok-1",
                "refresh_token": "ref-1",
                "expires_in": 3600,
                "scope": "youtube.upload",
            },
        )

    transport = httpx.MockTransport(handler)

    real_init = httpx.AsyncClient.__init__

    def patched_init(self: httpx.AsyncClient, **kwargs: object) -> None:
        kwargs["transport"] = transport
        real_init(self, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    import asyncio

    tokens = asyncio.run(YouTubeOAuth(settings).exchange_code("code-1"))
    assert tokens.access_token == "tok-1"
    assert tokens.refresh_token == "ref-1"
    assert tokens.expires_at is not None
    assert "code=code-1" in captured["body"]  # type: ignore[operator]


def test_get_publisher_factory_returns_concrete_class() -> None:
    yt = get_publisher(SocialPlatform.YOUTUBE)
    tt = get_publisher(SocialPlatform.TIKTOK)
    ig = get_publisher(SocialPlatform.INSTAGRAM)
    assert yt.platform == SocialPlatform.YOUTUBE
    assert tt.platform == SocialPlatform.TIKTOK
    assert ig.platform == SocialPlatform.INSTAGRAM


def test_get_oauth_client_factory() -> None:
    settings = get_settings()
    settings.youtube_client_id = "yt"
    yt = get_oauth_client(SocialPlatform.YOUTUBE)
    assert yt.platform == SocialPlatform.YOUTUBE


def test_get_oauth_client_unknown_raises() -> None:
    with pytest.raises(OAuthError):
        # SocialPlatform is exhaustive; bypass via a fake string and the
        # registry lookup will return None.
        from content_creator_api.services import oauth as oauth_mod

        original = oauth_mod._REGISTRY.copy()
        try:
            oauth_mod._REGISTRY.clear()
            oauth_mod.get_oauth_client(SocialPlatform.YOUTUBE)
        finally:
            oauth_mod._REGISTRY.update(original)
