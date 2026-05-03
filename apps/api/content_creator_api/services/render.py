"""ffmpeg-based timeline renderer.

Given an ordered list of ``RenderClip`` segments (each pointing to a source
URL with a trim and target duration), this module:

1. Streams the source clips into a working directory.
2. Trims each clip with ``ffmpeg -ss ... -t ...`` to its target segment,
   normalizing the resolution / fps / pix_fmt / sar to the target output
   spec so the concat demuxer can stitch them losslessly.
3. Concatenates the trimmed segments into a single mp4.

The function is synchronous (RQ tasks are sync) and returns the path to
the rendered mp4. The caller is responsible for uploading it to S3.

We deliberately use the ffmpeg CLI rather than a Python wrapper to keep
the dependency surface small and let the operator pin a system ffmpeg.
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import httpx

log = logging.getLogger(__name__)


class RenderError(RuntimeError):
    """Raised when the render pipeline fails."""


@dataclass(slots=True)
class RenderClip:
    """One segment to render."""

    source_url: str
    source_start_ms: int = 0
    duration_ms: int = 5000


@dataclass(slots=True)
class RenderSpec:
    width: int = 1080
    height: int = 1920
    fps: int = 30
    # video bitrate; tuned for short-form social video.
    video_bitrate: str = "5M"


def _download(url: str, dest: Path) -> None:
    with httpx.stream("GET", url, follow_redirects=True, timeout=120.0) as response:
        if response.status_code >= 400:
            raise RenderError(f"download {url} failed: {response.status_code}")
        with dest.open("wb") as fh:
            for chunk in response.iter_bytes():
                fh.write(chunk)


def _run(cmd: list[str]) -> None:
    log.info("ffmpeg.run %s", " ".join(cmd))
    completed = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise RenderError(
            f"ffmpeg failed (exit {completed.returncode}):\n{completed.stderr[-2000:]}"
        )


def _normalize_segment(
    src: Path,
    dst: Path,
    *,
    start_ms: int,
    duration_ms: int,
    spec: RenderSpec,
) -> None:
    """Trim + scale + pad + reencode one clip to the canonical output spec."""
    start_s = max(0.0, start_ms / 1000.0)
    duration_s = max(0.05, duration_ms / 1000.0)
    vf = (
        f"scale={spec.width}:{spec.height}:force_original_aspect_ratio=decrease,"
        f"pad={spec.width}:{spec.height}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"setsar=1,fps={spec.fps}"
    )
    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        f"{start_s:.3f}",
        "-i",
        str(src),
        "-t",
        f"{duration_s:.3f}",
        "-vf",
        vf,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-pix_fmt",
        "yuv420p",
        "-b:v",
        spec.video_bitrate,
        "-an",
        str(dst),
    ]
    _run(cmd)


def _concat(segments: list[Path], dst: Path) -> None:
    """Concatenate normalized segments using the concat demuxer."""
    list_path = dst.parent / "concat.txt"
    list_path.write_text(
        "\n".join(f"file '{seg.as_posix()}'" for seg in segments) + "\n",
        encoding="utf-8",
    )
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_path),
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        str(dst),
    ]
    _run(cmd)


def render_timeline(
    clips: list[RenderClip],
    *,
    spec: RenderSpec | None = None,
    work_dir: Path | None = None,
) -> Path:
    """Render the given timeline. Returns the path to the resulting mp4.

    The output lives inside the work_dir (auto-created tempdir if not
    provided). The caller is expected to upload + then clean up.
    """
    if not clips:
        raise RenderError("timeline is empty")
    spec = spec or RenderSpec()
    work_dir = work_dir or Path(tempfile.mkdtemp(prefix="render-"))
    work_dir.mkdir(parents=True, exist_ok=True)

    segments: list[Path] = []
    for i, clip in enumerate(clips):
        src = work_dir / f"src-{i:03d}.mp4"
        seg = work_dir / f"seg-{i:03d}.mp4"
        _download(clip.source_url, src)
        _normalize_segment(
            src,
            seg,
            start_ms=clip.source_start_ms,
            duration_ms=clip.duration_ms,
            spec=spec,
        )
        segments.append(seg)

    out = work_dir / "out.mp4"
    _concat(segments, out)
    return out
