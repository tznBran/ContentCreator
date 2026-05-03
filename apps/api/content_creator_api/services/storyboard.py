"""Use an LLM to expand a single project prompt into an ordered shot list.

Output schema (the LLM must respond with strict JSON):

    {
      "shots": [
        {"prompt": "...", "duration_seconds": 5, "notes": "..."},
        ...
      ]
    }
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from content_creator_api.services.openrouter import OpenRouterClient

_SYSTEM_PROMPT = """You are a short-form video director. Given a high-level
prompt, plan an ordered list of N short visual shots that, when stitched
together, tell a coherent ~30-second TikTok / Reels / Short.

Each shot must be 1 sentence, visual-only (no audio cues), suitable for a
text-to-video model that has no audio. Distribute the requested total
duration across the shots in roughly equal chunks (each shot 3-8 seconds).

Respond with strict JSON of the form:
{"shots": [{"prompt": "<sentence>", "duration_seconds": <int>, "notes": "<one short sentence>"}]}
No other text.
"""


@dataclass(slots=True)
class StoryboardShot:
    prompt: str
    duration_seconds: int
    notes: str | None = None


def _user_prompt(prompt: str, n_shots: int, total_duration_seconds: int) -> str:
    return (
        f"Project prompt: {prompt}\n\n"
        f"Generate exactly {n_shots} ordered shots covering "
        f"~{total_duration_seconds} seconds total."
    )


async def generate_storyboard(
    client: OpenRouterClient,
    *,
    model: str,
    prompt: str,
    n_shots: int,
    total_duration_seconds: int,
) -> list[StoryboardShot]:
    response = await client.chat(
        model=model,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": _user_prompt(prompt, n_shots, total_duration_seconds),
            },
        ],
        response_format={"type": "json_object"},
        max_tokens=1500,
    )
    content = response["choices"][0]["message"]["content"]
    return _parse_storyboard(content, n_shots=n_shots)


def _parse_storyboard(content: str, *, n_shots: int) -> list[StoryboardShot]:
    data = json.loads(content)
    raw_shots = data.get("shots") or data.get("Shots") or []
    if not isinstance(raw_shots, list):
        raise ValueError("storyboard response missing 'shots' array")
    out: list[StoryboardShot] = []
    for item in raw_shots[:n_shots]:
        if not isinstance(item, dict):
            continue
        prompt = str(item.get("prompt") or item.get("description") or "").strip()
        if not prompt:
            continue
        try:
            duration = int(item.get("duration_seconds") or item.get("duration") or 5)
        except (TypeError, ValueError):
            duration = 5
        duration = max(1, min(30, duration))
        notes = item.get("notes") or item.get("note")
        out.append(
            StoryboardShot(
                prompt=prompt,
                duration_seconds=duration,
                notes=str(notes).strip() if notes else None,
            )
        )
    return out
