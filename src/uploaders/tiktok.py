"""
uploaders/tiktok.py

Uploads a video to TikTok using the Content Posting API (Direct Post,
FILE_UPLOAD source) - no external hosting needed, the file is PUT directly
to TikTok's servers.

--- One-time setup (manual, you'll need to do this yourself) ---
1. Register an app at https://developers.tiktok.com/.
2. Add the "Content Posting API" product and request the video.publish
   scope. Note: video.publish requires TikTok's app audit (2-4 weeks)
   before you can post publicly. Until audited, posts are private-only.
3. Complete TikTok's OAuth flow for the target creator account to get an
   access token (TIKTOK_ACCESS_TOKEN in .env). Tokens expire and need
   refreshing - see TikTok's OAuth docs for the refresh flow.

Usage:
    python -m src.uploaders.tiktok path/to/clip.mp4 "My caption"
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

API_BASE = "https://open.tiktokapis.com/v2"


def _headers() -> dict:
    token = os.environ.get("TIKTOK_ACCESS_TOKEN")
    if not token:
        raise EnvironmentError("TIKTOK_ACCESS_TOKEN not set in .env")
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def upload(video_path: str | Path, caption: str = "", privacy_level: str = "SELF_ONLY") -> str:
    """
    Upload a video to TikTok via Direct Post. Returns the publish_id.

    privacy_level options (until your app is audited, only SELF_ONLY works):
    PUBLIC_TO_EVERYONE, MUTUAL_FOLLOW_FRIENDS, SELF_ONLY
    """
    video_path = Path(video_path)
    if not video_path.exists():
        raise FileNotFoundError(f"No such file: {video_path}")

    video_size = video_path.stat().st_size

    # Step 1: initialize the post, get an upload_url + publish_id
    init_body = {
        "post_info": {
            "title": caption,
            "privacy_level": privacy_level,
            "disable_duet": False,
            "disable_comment": False,
            "disable_stitch": False,
        },
        "source_info": {
            "source": "FILE_UPLOAD",
            "video_size": video_size,
            "chunk_size": video_size,
            "total_chunk_count": 1,
        },
    }
    init_resp = requests.post(
        f"{API_BASE}/post/publish/video/init/", headers=_headers(), json=init_body
    )
    init_resp.raise_for_status()
    init_data = init_resp.json()["data"]
    publish_id = init_data["publish_id"]
    upload_url = init_data["upload_url"]

    # Step 2: PUT the video bytes to the returned upload_url
    with open(video_path, "rb") as f:
        video_bytes = f.read()

    put_headers = {
        "Content-Type": "video/mp4",
        "Content-Range": f"bytes 0-{video_size - 1}/{video_size}",
    }
    put_resp = requests.put(upload_url, headers=put_headers, data=video_bytes)
    put_resp.raise_for_status()

    # Step 3: poll publish status
    status_body = {"publish_id": publish_id}
    for _ in range(30):  # up to ~5 minutes
        status_resp = requests.post(
            f"{API_BASE}/post/publish/status/fetch/", headers=_headers(), json=status_body
        )
        status_resp.raise_for_status()
        status = status_resp.json()["data"]["status"]
        print(f"[tiktok] status: {status}")
        if status == "PUBLISH_COMPLETE":
            break
        if status == "FAILED":
            raise RuntimeError(f"TikTok publish failed: {status_resp.json()}")
        time.sleep(10)

    print(f"[tiktok] uploaded, publish_id={publish_id}")
    return publish_id


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Usage: python -m src.uploaders.tiktok <video_path> "<caption>"')
        sys.exit(1)

    caption = sys.argv[2] if len(sys.argv) > 2 else ""
    upload(sys.argv[1], caption)