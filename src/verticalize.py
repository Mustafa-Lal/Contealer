"""
verticalize.py

Converts landscape (16:9) clips into vertical (9:16) Shorts-ready videos
by placing the original footage centered on a blurred, scaled-up copy of
itself as the background (the standard "reels/shorts" look).

Usage:
    python -m src.verticalize <input_folder> <output_folder>
    python -m src.verticalize data/clips data/clips/vertical
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

TARGET_W, TARGET_H = 1080, 1920

FILTER = (
    f"split[original][copy];"
    f"[copy]scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=increase,"
    f"crop={TARGET_W}:{TARGET_H},gblur=sigma=20[bg];"
    f"[original]scale={TARGET_W}:-2[fg];"
    f"[bg][fg]overlay=(W-w)/2:(H-h)/2"
)

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm"}


def verticalize(input_path: Path, output_path: Path) -> bool:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-vf", FILTER,
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-c:a", "copy",
        str(output_path),
    ]
    print(f"[verticalize] {input_path.name} -> {output_path}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[verticalize] ffmpeg failed for {input_path.name}:\n{result.stderr[-1500:]}")
        return False
    print(f"[verticalize] done: {output_path.name}")
    return True


def verticalize_folder(input_folder: Path, output_folder: Path) -> None:
    video_files = sorted(
        f for f in input_folder.iterdir()
        if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS
    )
    if not video_files:
        print(f"[verticalize] no video files found in {input_folder}")
        return

    output_folder.mkdir(parents=True, exist_ok=True)

    succeeded = 0
    for video in video_files:
        output_path = output_folder / video.name
        if verticalize(video, output_path):
            succeeded += 1

    print(f"[verticalize] {succeeded}/{len(video_files)} converted successfully")


def main() -> None:
    if len(sys.argv) != 3:
        print("Usage: python -m src.verticalize <input_folder> <output_folder>")
        sys.exit(1)

    input_folder = Path(sys.argv[1])
    output_folder = Path(sys.argv[2])

    if not input_folder.exists() or not input_folder.is_dir():
        print(f"[verticalize] input folder not found: {input_folder}")
        sys.exit(1)

    verticalize_folder(input_folder, output_folder)


if __name__ == "__main__":
    main()