"""RQ task entrypoints. Imported by the worker."""

from content_creator_api.tasks.generation import (
    finalize_generation_job,
    generate_and_score_clip,
)
from content_creator_api.tasks.narration import (
    register_voice_profile,
    synthesize_narration_job,
)
from content_creator_api.tasks.render import render_export_job

__all__ = [
    "finalize_generation_job",
    "generate_and_score_clip",
    "register_voice_profile",
    "render_export_job",
    "synthesize_narration_job",
]
