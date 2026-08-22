"""
clipper.py

Takes a video and its clips JSON (output of clip_finder.py) and cuts each
clip out with ffmpeg, saving them into data/clips/.

Each output file is named "<index>_<slugified-title>.mp4".

Requires ffmpeg installed and on PATH.

Usage:
    python -m src.clipper data/incoming/video.mp4 data/incoming/video_clips.json
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

CLIPS_DIR = Path(__file__).resolve().parent.parent / "data" / "clips"


def _slugify(title: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", title.lower())
    slug = re.sub(r"[\s_-]+", "-", slug).strip("-")
    return slug[:50] or "clip"


def _cut_clip(video_path: Path, start: float, end: float, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(video_path),
        "-ss", str(start),
        "-to", str(end),
        "-c:v", "libx264",
        "-c:a", "aac",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def extract_clips(video_path: str | Path, clips_json_path: str | Path) -> list[Path]:
    video_path = Path(video_path)
    clips_json_path = Path(clips_json_path)

    if not video_path.exists():
        raise FileNotFoundError(f"No such file: {video_path}")
    if not clips_json_path.exists():
        raise FileNotFoundError(f"No such file: {clips_json_path}")

    clips = json.loads(clips_json_path.read_text(encoding="utf-8"))

    out_paths = []
    for i, clip in enumerate(clips, start=1):
        slug = _slugify(clip["title"])
        out_path = CLIPS_DIR / f"{i:02d}_{slug}.mp4"

        print(f"[clipper] cutting clip {i}/{len(clips)}: {clip['title']} "
              f"({clip['start']}s - {clip['end']}s)")
        _cut_clip(video_path, clip["start"], clip["end"], out_path)
        out_paths.append(out_path)

    print(f"[clipper] done, {len(out_paths)} clips saved to {CLIPS_DIR}")
    return out_paths


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python -m src.clipper <video_path> <clips_json_path>")
        sys.exit(1)

    extract_clips(sys.argv[1], sys.argv[2])