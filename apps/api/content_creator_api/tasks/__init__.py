"""RQ task entrypoints. Imported by the worker."""

from content_creator_api.tasks.generation import (
    finalize_generation_job,
    generate_and_score_clip,
)

__all__ = ["finalize_generation_job", "generate_and_score_clip"]
