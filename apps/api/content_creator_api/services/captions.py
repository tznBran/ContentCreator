"""Caption generation.

For the v1 of Phase 3 we punt on real ASR (Whisper, AssemblyAI, etc.) and
use a deterministic *rough captions* strategy: split the script into
sentences and distribute their durations proportionally to character
count. The output schema matches what real ASR will produce so when we
swap in Whisper later only the implementation changes.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")


@dataclass(slots=True)
class CaptionSegment:
    start_ms: int
    end_ms: int
    text: str


def _split_sentences(script: str) -> list[str]:
    raw = _SENTENCE_SPLIT_RE.split(script.strip())
    return [s.strip() for s in raw if s.strip()]


def rough_captions(script: str, total_duration_ms: int) -> list[CaptionSegment]:
    """Distribute sentence-level captions across ``total_duration_ms``."""
    if total_duration_ms <= 0 or not script.strip():
        return []
    sentences = _split_sentences(script)
    if not sentences:
        return []
    # Weight by character length, but cap individual durations to a sane
    # reading speed of ~200ms per character so very short sentences don't
    # explode.
    weights = [max(1, len(s)) for s in sentences]
    total_weight = sum(weights)
    cursor = 0
    out: list[CaptionSegment] = []
    for i, sentence in enumerate(sentences):
        share = total_duration_ms * weights[i] / total_weight
        duration = max(500, int(round(share)))
        end = min(total_duration_ms, cursor + duration)
        out.append(CaptionSegment(start_ms=cursor, end_ms=end, text=sentence))
        cursor = end
    # Stretch the last segment to match total duration exactly.
    if out:
        out[-1] = CaptionSegment(
            start_ms=out[-1].start_ms,
            end_ms=total_duration_ms,
            text=out[-1].text,
        )
    return out


def captions_to_json(segments: list[CaptionSegment]) -> str:
    return json.dumps([asdict(s) for s in segments], ensure_ascii=False)


def captions_from_json(blob: str) -> list[CaptionSegment]:
    data = json.loads(blob)
    return [
        CaptionSegment(
            start_ms=int(item["start_ms"]),
            end_ms=int(item["end_ms"]),
            text=str(item["text"]),
        )
        for item in data
    ]
