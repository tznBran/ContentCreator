"""Pydantic request/response schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from content_creator_api.models import ProjectStatus


class ProjectCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    prompt: str = Field(default="", max_length=4000)


class ProjectUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    prompt: str | None = Field(default=None, max_length=4000)
    status: ProjectStatus | None = None


class ProjectRead(BaseModel):
    id: UUID
    title: str
    prompt: str
    status: ProjectStatus
    created_at: datetime
    updated_at: datetime


class HealthResponse(BaseModel):
    status: str
    version: str
