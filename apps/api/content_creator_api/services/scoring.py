"""Clip scoring via a vision/multimodal LLM.

We call the LLM with the clip URL (or signed URL) and the original prompt,
asking for a JSON object with a 0-100 score and a one-sentence explanation
of how well the clip matches the prompt.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import structlog

from content_creator_api.services.openrouter import OpenRouterClient

log = structlog.get_logger(__name__)

_SCORE_SYSTEM_PROMPT = """You are a strict creative director scoring AI-generated short video clips.

Score a clip on a 0-100 scale combining:
- Prompt adherence (does it actually depict what the prompt asked for?)
- Visual quality (sharpness, lack of artifacts, coherent motion)
- Overall watchability (composition, lighting, framing)

Reply with strict JSON: {"score": <0-100 integer>, "explanation": "<one sentence>"}.
Do not include any other text.
"""


@dataclass(slots=True)
class ClipScore:
    score: float
    explanation: str


async def score_clip(
    client: OpenRouterClient,
    *,
    model: str,
    prompt: str,
    clip_url: str,
) -> ClipScore:
    """Ask a vision LLM to score a single clip.

    The model is expected to be one that accepts image/video inputs through
    OpenRouter's multimodal interface. We pass the clip URL inside an
    ``image_url`` content part since that's the broadest interop today; many
    routers will sample frames from the URL.
    """
    user_content = [
        {"type": "text", "text": f"Prompt: {prompt}\n\nScore this clip."},
        {"type": "image_url", "image_url": {"url": clip_url}},
    ]
    response = await client.chat(
        model=model,
        messages=[
            {"role": "system", "content": _SCORE_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        response_format={"type": "json_object"},
        max_tokens=200,
    )
    content = response["choices"][0]["message"]["content"]
    return _parse_score(content)


def _parse_score(content: str) -> ClipScore:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"scorer returned non-JSON: {content!r}") from exc
    raw_score = parsed.get("score")
    explanation = parsed.get("explanation") or ""
    if raw_score is None:
        raise ValueError(f"scorer missing 'score': {content!r}")
    score = float(raw_score)
    score = max(0.0, min(100.0, score))
    return ClipScore(score=score, explanation=str(explanation))
