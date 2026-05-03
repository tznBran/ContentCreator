"""FastAPI application entrypoint."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from content_creator_api import __version__
from content_creator_api.config import get_settings
from content_creator_api.routers import (
    generations,
    health,
    projects,
    publishing,
    storyboard,
    timeline,
    voices,
)


def _configure_logging(level: str) -> None:
    logging.basicConfig(level=level.upper())
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
    )


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    _configure_logging(settings.api_log_level)
    log = structlog.get_logger().bind(component="api")
    log.info("api.start", version=__version__, environment=settings.environment)
    yield
    log.info("api.stop")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="ContentCreator API",
        version=__version__,
        description="Backend for the ContentCreator AI video platform.",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(projects.router)
    app.include_router(generations.router)
    app.include_router(storyboard.router)
    app.include_router(timeline.router)
    app.include_router(voices.router)
    app.include_router(publishing.router)

    return app


app = create_app()
