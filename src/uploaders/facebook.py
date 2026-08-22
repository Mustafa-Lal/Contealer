"""
uploaders/facebook.py

Uploads a video directly to a Facebook Page via the Graph API.

--- One-time setup (manual) ---
1. Create an app at https://developers.facebook.com/.
2. Add the "Facebook Login" and get a Page Access Token for the target
   Page, with the pages_manage_posts and pages_read_engagement permissions.
   Easiest path: use the Graph API Explorer to generate a long-lived Page
   token, or implement the full OAuth login flow if this needs to run
   unattended long-term (short-lived tokens expire in ~1-2 hours; a
   long-lived Page token can last ~60 days or be non-expiring for some
   setups - see Meta's token guide).
3. Put the Page ID and Page Access Token in .env.

Usage:
    python -m src.uploaders.facebook path/to/clip.mp4 "My caption"
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

GRAPH_API_VERSION = "v22.0"


def upload(video_path: str | Path, caption: str = "") -> str:
    """Upload a video to the configured Facebook Page. Returns the video ID."""
    video_path = Path(video_path)
    if not video_path.exists():
        raise FileNotFoundError(f"No such file: {video_path}")

    page_id = os.environ.get("FACEBOOK_PAGE_ID")
    access_token = os.environ.get("FACEBOOK_PAGE_ACCESS_TOKEN")
    if not page_id or not access_token:
        raise EnvironmentError(
            "FACEBOOK_PAGE_ID and FACEBOOK_PAGE_ACCESS_TOKEN must be set in .env"
        )

    url = f"https://graph-video.facebook.com/{GRAPH_API_VERSION}/{page_id}/videos"

    with open(video_path, "rb") as f:
        files = {"source": f}
        data = {"description": caption, "access_token": access_token}
        resp = requests.post(url, files=files, data=data)

    resp.raise_for_status()
    video_id = resp.json()["id"]
    print(f"[facebook] uploaded -> https://facebook.com/{video_id}")
    return video_id


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Usage: python -m src.uploaders.facebook <video_path> "<caption>"')
        sys.exit(1)

    caption = sys.argv[2] if len(sys.argv) > 2 else ""
    upload(sys.argv[1], caption)