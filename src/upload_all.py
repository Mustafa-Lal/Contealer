"""
upload_all.py

Takes the clips JSON (for titles) and the matching files in data/clips/,
and uploads each clip to every platform you've configured credentials for
in .env. Platforms without credentials set are skipped with a warning
rather than failing the whole run.

Usage:
    python -m src.upload_all data/incoming/video_clips.json
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from src.uploaders import facebook, instagram, tiktok, youtube

load_dotenv()

CLIPS_DIR = Path(__file__).resolve().parent.parent / "data" / "clips" / "vertical"


def _configured(*env_vars: str) -> bool:
    return all(os.environ.get(v) for v in env_vars)


def upload_all(clips_json_path: str | Path) -> None:
    clips_json_path = Path(clips_json_path)
    clips = json.loads(clips_json_path.read_text(encoding="utf-8"))

    clip_files = sorted(CLIPS_DIR.glob("*.mp4"))
    if len(clip_files) != len(clips):
        print(
            f"[upload_all] warning: {len(clips)} clips in JSON but "
            f"{len(clip_files)} files in {CLIPS_DIR} - matching by order, double check this."
        )

    have_youtube = (Path(__file__).resolve().parent.parent / "client_secret.json").exists()
    have_tiktok = _configured("TIKTOK_ACCESS_TOKEN")
    have_facebook = _configured("FACEBOOK_PAGE_ID", "FACEBOOK_PAGE_ACCESS_TOKEN")
    have_instagram = _configured("INSTAGRAM_BUSINESS_ACCOUNT_ID", "INSTAGRAM_ACCESS_TOKEN")
    public_base_url = os.environ.get("PUBLIC_CLIPS_BASE_URL")  # needed for Instagram

    if not have_youtube:
        print("[upload_all] skipping YouTube: client_secret.json not found")
    if not have_tiktok:
        print("[upload_all] skipping TikTok: TIKTOK_ACCESS_TOKEN not set in .env")
    if not have_facebook:
        print("[upload_all] skipping Facebook: FACEBOOK_PAGE_ID / FACEBOOK_PAGE_ACCESS_TOKEN not set")
    if not have_instagram:
        print("[upload_all] skipping Instagram: INSTAGRAM_BUSINESS_ACCOUNT_ID / INSTAGRAM_ACCESS_TOKEN not set")
    elif not public_base_url:
        print(
            "[upload_all] skipping Instagram: needs PUBLIC_CLIPS_BASE_URL in .env "
            "(Instagram requires a public URL, not a local file)"
        )
        have_instagram = False

    for clip, file_path in zip(clips, clip_files):
        title = clip["title"]
        caption = clip.get("hook", title)
        print(f"\n[upload_all] --- {file_path.name} ---")

        if have_youtube:
            try:
                youtube.upload(file_path, title, caption)
            except Exception as e:
                print(f"[upload_all] YouTube upload failed: {e}")

        if have_tiktok:
            try:
                tiktok.upload(file_path, caption)
            except Exception as e:
                print(f"[upload_all] TikTok upload failed: {e}")

        if have_facebook:
            try:
                facebook.upload(file_path, caption)
            except Exception as e:
                print(f"[upload_all] Facebook upload failed: {e}")

        if have_instagram:
            try:
                video_url = f"{public_base_url.rstrip('/')}/{file_path.name}"
                instagram.upload(video_url, caption)
            except Exception as e:
                print(f"[upload_all] Instagram upload failed: {e}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python -m src.upload_all <clips_json_path>")
        sys.exit(1)

    upload_all(sys.argv[1])