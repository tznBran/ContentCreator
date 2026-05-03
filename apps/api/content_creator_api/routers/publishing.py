"""OAuth + social account management + multi-platform publishing."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import RedirectResponse
from sqlmodel import Session, col, select

from content_creator_api.config import get_settings
from content_creator_api.db import get_session
from content_creator_api.models import (
    ExportJob,
    Project,
    PublishJob,
    PublishStatus,
    SocialAccount,
    SocialPlatform,
)
from content_creator_api.schemas import (
    OAuthStartResponse,
    PublishCreate,
    PublishRead,
    SocialAccountRead,
)
from content_creator_api.services.oauth import (
    OAuthError,
    encode_extra,
    get_oauth_client,
)
from content_creator_api.services.queue import get_queue
from content_creator_api.tasks.publish import publish_video

router = APIRouter(tags=["publishing"])


def _now() -> datetime:
    return datetime.now(UTC)


# ----------------------------- OAuth ----------------------------------


@router.get(
    "/oauth/{platform}/start",
    response_model=OAuthStartResponse,
)
def oauth_start(platform: SocialPlatform) -> OAuthStartResponse:
    """Return the URL the user should be redirected to.

    The frontend renders a "Connect" button for each platform; clicking
    it calls this endpoint and follows ``authorize_url`` in the same
    tab. The provider then bounces the user to ``/oauth/{platform}/callback``.
    """
    state = secrets.token_urlsafe(24)
    try:
        client = get_oauth_client(platform)
    except OAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return OAuthStartResponse(authorize_url=client.authorize_url(state), state=state)


@router.get("/oauth/{platform}/callback")
async def oauth_callback(
    platform: SocialPlatform,
    code: str | None = Query(default=None),
    error: str | None = Query(default=None),
    session: Session = Depends(get_session),
) -> Response:
    """Exchange the auth code, persist a ``SocialAccount``, redirect home."""
    settings = get_settings()
    web_base = settings.web_base_url.rstrip("/")

    if error or not code:
        return RedirectResponse(
            f"{web_base}/?oauth_error={error or 'missing_code'}"
        )

    try:
        client = get_oauth_client(platform)
        tokens = await client.exchange_code(code)
        info = await client.account_info(tokens.access_token)
    except OAuthError as exc:
        return RedirectResponse(f"{web_base}/?oauth_error={exc}")

    # Upsert: a single user only ever has one row per (platform,
    # external_id) — refresh tokens / display names are kept current.
    existing = session.exec(
        select(SocialAccount).where(
            SocialAccount.platform == platform,
            SocialAccount.external_id == info.external_id,
        )
    ).first()

    if existing is None:
        account = SocialAccount(
            platform=platform,
            account_name=info.account_name,
            external_id=info.external_id,
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            expires_at=tokens.expires_at,
            scope=tokens.scope,
            extra_json=encode_extra(info.extra),
        )
    else:
        account = existing
        account.account_name = info.account_name
        account.access_token = tokens.access_token
        if tokens.refresh_token:
            account.refresh_token = tokens.refresh_token
        account.expires_at = tokens.expires_at
        account.scope = tokens.scope
        account.extra_json = encode_extra(info.extra)
        account.updated_at = _now()

    session.add(account)
    session.commit()

    return RedirectResponse(f"{web_base}/?connected={platform.value}")


# ------------------------ Account management --------------------------


@router.get("/accounts", response_model=list[SocialAccountRead])
def list_accounts(session: Session = Depends(get_session)) -> list[SocialAccount]:
    rows = session.exec(
        select(SocialAccount).order_by(col(SocialAccount.created_at).desc())
    ).all()
    return list(rows)


@router.delete("/accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(
    account_id: UUID, session: Session = Depends(get_session)
) -> None:
    account = session.get(SocialAccount, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="account not found")
    session.delete(account)
    session.commit()


# --------------------------- Publishing -------------------------------


@router.post(
    "/projects/{project_id}/publishes",
    response_model=PublishRead,
    status_code=status.HTTP_201_CREATED,
)
def create_publish(
    project_id: UUID,
    payload: PublishCreate,
    session: Session = Depends(get_session),
) -> PublishJob:
    if session.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")
    export = session.get(ExportJob, payload.export_id)
    if export is None or export.project_id != project_id:
        raise HTTPException(status_code=404, detail="export not found for project")
    account = session.get(SocialAccount, payload.account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="account not connected")
    if account.platform != payload.platform:
        raise HTTPException(
            status_code=400,
            detail="account.platform does not match payload.platform",
        )

    job = PublishJob(
        project_id=project_id,
        export_id=payload.export_id,
        account_id=payload.account_id,
        platform=payload.platform,
        title=payload.title,
        description=payload.description,
        visibility=payload.visibility,
        status=PublishStatus.PENDING,
    )
    session.add(job)
    session.commit()
    session.refresh(job)

    if get_settings().enqueue_jobs:
        get_queue().enqueue(
            publish_video,
            str(job.id),
            job_timeout=3600,
            result_ttl=3600,
        )

    return job


@router.get(
    "/projects/{project_id}/publishes", response_model=list[PublishRead]
)
def list_publishes(
    project_id: UUID, session: Session = Depends(get_session)
) -> list[PublishJob]:
    if session.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")
    rows = session.exec(
        select(PublishJob)
        .where(PublishJob.project_id == project_id)
        .order_by(col(PublishJob.created_at).desc())
    ).all()
    return list(rows)


@router.get("/publishes/{publish_id}", response_model=PublishRead)
def get_publish(
    publish_id: UUID, session: Session = Depends(get_session)
) -> PublishJob:
    job = session.get(PublishJob, publish_id)
    if job is None:
        raise HTTPException(status_code=404, detail="publish not found")
    return job
