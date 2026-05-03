"""OAuth helpers for the three publishing providers.

Each provider exposes the same shape:

- ``authorize_url(state)`` — the URL to redirect the user to.
- ``exchange_code(code)`` → :class:`OAuthTokens` — swap the auth code
  for tokens.
- ``refresh(refresh_token)`` → :class:`OAuthTokens` — refresh an
  expired access token.
- ``account_info(access_token)`` → :class:`OAuthAccountInfo` — fetch
  the display name + external id we persist on ``SocialAccount``.

Everything is async + httpx-based so it slots into FastAPI handlers
and the ``asyncio.run`` shim used by RQ tasks.

The real provider URLs/scopes are baked in but every network hop is
isolated behind a tiny method, which makes the providers easy to
mock in tests.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

import httpx

from content_creator_api.config import Settings, get_settings
from content_creator_api.models import SocialPlatform

log = logging.getLogger(__name__)


class OAuthError(RuntimeError):
    pass


@dataclass(slots=True)
class OAuthTokens:
    access_token: str
    refresh_token: str | None
    expires_at: datetime | None
    scope: str | None


@dataclass(slots=True)
class OAuthAccountInfo:
    external_id: str
    account_name: str
    extra: dict[str, str]


class OAuthClient(Protocol):
    platform: SocialPlatform

    def authorize_url(self, state: str) -> str: ...

    async def exchange_code(self, code: str) -> OAuthTokens: ...

    async def refresh(self, refresh_token: str) -> OAuthTokens: ...

    async def account_info(self, access_token: str) -> OAuthAccountInfo: ...


def _expires_at(expires_in: int | None) -> datetime | None:
    if expires_in is None or expires_in <= 0:
        return None
    return datetime.now(UTC) + timedelta(seconds=int(expires_in))


def _redirect_uri(settings: Settings, platform: SocialPlatform) -> str:
    base = settings.oauth_redirect_base.rstrip("/")
    return f"{base}/oauth/{platform.value}/callback"


# ----------------------- YouTube (Google) -----------------------------


class YouTubeOAuth:
    platform = SocialPlatform.YOUTUBE
    SCOPES = (
        "https://www.googleapis.com/auth/youtube.upload "
        "https://www.googleapis.com/auth/youtube.readonly"
    )
    AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN_URL = "https://oauth2.googleapis.com/token"
    CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def authorize_url(self, state: str) -> str:
        params = {
            "client_id": self._settings.youtube_client_id,
            "redirect_uri": _redirect_uri(self._settings, self.platform),
            "response_type": "code",
            "scope": self.SCOPES,
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
        return f"{self.AUTHORIZE_URL}?{httpx.QueryParams(params)}"

    async def exchange_code(self, code: str) -> OAuthTokens:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                self.TOKEN_URL,
                data={
                    "client_id": self._settings.youtube_client_id,
                    "client_secret": self._settings.youtube_client_secret,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": _redirect_uri(self._settings, self.platform),
                },
            )
        return _parse_token_response(response)

    async def refresh(self, refresh_token: str) -> OAuthTokens:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                self.TOKEN_URL,
                data={
                    "client_id": self._settings.youtube_client_id,
                    "client_secret": self._settings.youtube_client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
            )
        tokens = _parse_token_response(response)
        # Google omits refresh_token on refresh; keep the original.
        if tokens.refresh_token is None:
            tokens.refresh_token = refresh_token
        return tokens

    async def account_info(self, access_token: str) -> OAuthAccountInfo:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                self.CHANNELS_URL,
                params={"part": "snippet", "mine": "true"},
                headers={"Authorization": f"Bearer {access_token}"},
            )
        if response.status_code >= 400:
            raise OAuthError(f"youtube channels.list failed: {response.text}")
        items = response.json().get("items", [])
        if not items:
            raise OAuthError("youtube account has no channel")
        channel = items[0]
        return OAuthAccountInfo(
            external_id=str(channel["id"]),
            account_name=str(channel["snippet"]["title"]),
            extra={"channel_id": str(channel["id"])},
        )


# ------------------------------ TikTok --------------------------------


class TikTokOAuth:
    platform = SocialPlatform.TIKTOK
    SCOPES = "user.info.basic,video.upload,video.publish"
    AUTHORIZE_URL = "https://www.tiktok.com/v2/auth/authorize/"
    TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
    USER_INFO_URL = "https://open.tiktokapis.com/v2/user/info/"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def authorize_url(self, state: str) -> str:
        params = {
            "client_key": self._settings.tiktok_client_key,
            "redirect_uri": _redirect_uri(self._settings, self.platform),
            "response_type": "code",
            "scope": self.SCOPES,
            "state": state,
        }
        return f"{self.AUTHORIZE_URL}?{httpx.QueryParams(params)}"

    async def exchange_code(self, code: str) -> OAuthTokens:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                self.TOKEN_URL,
                data={
                    "client_key": self._settings.tiktok_client_key,
                    "client_secret": self._settings.tiktok_client_secret,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": _redirect_uri(self._settings, self.platform),
                },
            )
        return _parse_token_response(response)

    async def refresh(self, refresh_token: str) -> OAuthTokens:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                self.TOKEN_URL,
                data={
                    "client_key": self._settings.tiktok_client_key,
                    "client_secret": self._settings.tiktok_client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
            )
        return _parse_token_response(response)

    async def account_info(self, access_token: str) -> OAuthAccountInfo:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                self.USER_INFO_URL,
                params={"fields": "open_id,union_id,display_name"},
                headers={"Authorization": f"Bearer {access_token}"},
            )
        if response.status_code >= 400:
            raise OAuthError(f"tiktok user.info failed: {response.text}")
        body = response.json()
        user = body.get("data", {}).get("user", {})
        if not user:
            raise OAuthError("tiktok user.info empty")
        open_id = str(user.get("open_id", ""))
        return OAuthAccountInfo(
            external_id=open_id or str(user.get("union_id", "")),
            account_name=str(user.get("display_name", "TikTok user")),
            extra={"open_id": open_id},
        )


# ------------------------------ Meta ----------------------------------


class InstagramOAuth:
    platform = SocialPlatform.INSTAGRAM
    SCOPES = (
        "instagram_basic,instagram_content_publish,"
        "pages_show_list,pages_read_engagement"
    )
    AUTHORIZE_URL = "https://www.facebook.com/v19.0/dialog/oauth"
    TOKEN_URL = "https://graph.facebook.com/v19.0/oauth/access_token"
    ME_URL = "https://graph.facebook.com/v19.0/me"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def authorize_url(self, state: str) -> str:
        params = {
            "client_id": self._settings.meta_app_id,
            "redirect_uri": _redirect_uri(self._settings, self.platform),
            "response_type": "code",
            "scope": self.SCOPES,
            "state": state,
        }
        return f"{self.AUTHORIZE_URL}?{httpx.QueryParams(params)}"

    async def exchange_code(self, code: str) -> OAuthTokens:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                self.TOKEN_URL,
                params={
                    "client_id": self._settings.meta_app_id,
                    "client_secret": self._settings.meta_app_secret,
                    "redirect_uri": _redirect_uri(self._settings, self.platform),
                    "code": code,
                },
            )
        return _parse_token_response(response)

    async def refresh(self, refresh_token: str) -> OAuthTokens:
        # Meta uses long-lived tokens rather than refresh tokens. We
        # extend the existing access token (passed in as ``refresh_token``
        # for symmetry with the other providers).
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                self.TOKEN_URL,
                params={
                    "grant_type": "fb_exchange_token",
                    "client_id": self._settings.meta_app_id,
                    "client_secret": self._settings.meta_app_secret,
                    "fb_exchange_token": refresh_token,
                },
            )
        return _parse_token_response(response)

    async def account_info(self, access_token: str) -> OAuthAccountInfo:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                self.ME_URL,
                params={"fields": "id,name", "access_token": access_token},
            )
        if response.status_code >= 400:
            raise OAuthError(f"meta /me failed: {response.text}")
        body = response.json()
        return OAuthAccountInfo(
            external_id=str(body.get("id", "")),
            account_name=str(body.get("name", "Instagram account")),
            extra={"ig_user_id": self._settings.instagram_user_id},
        )


def _parse_token_response(response: httpx.Response) -> OAuthTokens:
    if response.status_code >= 400:
        raise OAuthError(
            f"oauth token endpoint returned {response.status_code}: {response.text}"
        )
    body = response.json()
    if "error" in body:
        raise OAuthError(
            f"oauth token endpoint error: {body.get('error')} {body.get('error_description', '')}"
        )
    return OAuthTokens(
        access_token=str(body["access_token"]),
        refresh_token=body.get("refresh_token"),
        expires_at=_expires_at(body.get("expires_in")),
        scope=body.get("scope"),
    )


_REGISTRY: dict[SocialPlatform, type] = {
    SocialPlatform.YOUTUBE: YouTubeOAuth,
    SocialPlatform.TIKTOK: TikTokOAuth,
    SocialPlatform.INSTAGRAM: InstagramOAuth,
}


def get_oauth_client(platform: SocialPlatform) -> OAuthClient:
    cls = _REGISTRY.get(platform)
    if cls is None:
        raise OAuthError(f"unsupported platform {platform}")
    return cls(get_settings())  # type: ignore[no-any-return]


def encode_extra(extra: dict[str, str] | None) -> str | None:
    if not extra:
        return None
    return json.dumps(extra)


def decode_extra(blob: str | None) -> dict[str, str]:
    if not blob:
        return {}
    try:
        parsed = json.loads(blob)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {str(k): str(v) for k, v in parsed.items()}
