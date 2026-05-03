"""Health-check endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from content_creator_api import __version__
from content_creator_api.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", version=__version__)
