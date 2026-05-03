"""RQ worker entrypoint.

Run with::

    uv run python -m content_creator_api.worker

Imports tasks at module load so RQ can resolve them by dotted path.
"""

from __future__ import annotations

import logging

import structlog
from rq import Worker

from content_creator_api import tasks  # noqa: F401  (registers task modules)
from content_creator_api.services.queue import get_queue, get_redis

log = structlog.get_logger(__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    queue = get_queue()
    worker = Worker([queue], connection=get_redis())
    log.info("worker.starting", queue=queue.name)
    worker.work(with_scheduler=True)


if __name__ == "__main__":
    main()
