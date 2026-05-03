"""Redis + RQ queue plumbing."""

from __future__ import annotations

from functools import lru_cache

import redis
from rq import Queue

from content_creator_api.config import get_settings


@lru_cache(maxsize=1)
def get_redis() -> redis.Redis:
    settings = get_settings()
    return redis.from_url(settings.redis_url)


@lru_cache(maxsize=1)
def get_queue(name: str = "default") -> Queue:
    return Queue(name, connection=get_redis())
