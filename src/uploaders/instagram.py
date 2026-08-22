"""
uploaders/instagram.py

Publishes a Reel to Instagram via the Graph API.

This script uses Cloudinary to host the local video file first, as Instagram's
container-based publish flow needs a `video_url` it can fetch the file from.

--- One-time setup (manual) ---
1. Convert the target Instagram account to a Business or Creator account,
   and connect it to a Facebook Page.
2. Create an app at https://developers.facebook.com/, add the Instagram
   Graph API product, and get a long-lived access token with the
   instagram_content_publish permission.
3. Get the Instagram Business Account ID (via GET /{page-id}?fields=instagram_business_account).
4. Put the account ID and access token in .env.
5. Setup a Cloudinary account and put CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, and CLOUDINARY_API_SECRET in .env.

Usage:
    python -m src.uploaders.instagram path/to/clip.mp4 "My caption"
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import requests
import cloudinary
import cloudinary.uploader
from dotenv import load_dotenv

load_dotenv()

GRAPH_API_VERSION = "v22.0"
BASE_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}"


def upload_to_cloudinary(video_path: str | Path) -> str:
    """Upload the local video to Cloudinary and return its public URL."""
    cloudinary.config(
        cloud_name=os.environ.get("CLOUDINARY_CLOUD_NAME"),
        api_key=os.environ.get("CLOUDINARY_API_KEY"),
        api_secret=os.environ.get("CLOUDINARY_API_SECRET"),
        secure=True,
    )
    print(f"[instagram] Uploading {video_path} to Cloudinary...")
    result = cloudinary.uploader.upload_large(
        str(video_path),
        resource_type="video",
    )
    public_url = result["secure_url"]
    print(f"[instagram] Cloudinary URL: {public_url}")
    return public_url


def upload(video_path: str | Path, caption: str = "") -> str:
    """Publish a Reel from a local video file. Returns the published media ID."""
    ig_user_id = os.environ.get("INSTAGRAM_BUSINESS_ACCOUNT_ID")
    access_token = os.environ.get("INSTAGRAM_ACCESS_TOKEN") or os.environ.get("FACEBOOK_PAGE_ACCESS_TOKEN")
    if not ig_user_id or not access_token:
        raise EnvironmentError(
            "INSTAGRAM_BUSINESS_ACCOUNT_ID and INSTAGRAM_ACCESS_TOKEN (or FACEBOOK_PAGE_ACCESS_TOKEN) must be set in .env"
        )

    # Step 0: host the video temporarily so Instagram can download it
    video_url = upload_to_cloudinary(video_path)

    # Step 1: create the media container
    container_resp = requests.post(
        f"{BASE_URL}/{ig_user_id}/media",
        data={
            "media_type": "REELS",
            "video_url": video_url,
            "caption": caption,
            "share_to_feed": "true",
            "access_token": access_token,
        },
    )
    container_resp.raise_for_status()
    container_id = container_resp.json()["id"]

    # Step 2: poll until the container has finished processing
    for _ in range(30):  # up to ~5 minutes
        status_resp = requests.get(
            f"{BASE_URL}/{container_id}",
            params={"fields": "status_code", "access_token": access_token},
        )
        status_resp.raise_for_status()
        status = status_resp.json()["status_code"]
        print(f"[instagram] container status: {status}")
        if status == "FINISHED":
            break
        if status == "ERROR":
            raise RuntimeError(f"Instagram container failed: {status_resp.json()}")
        time.sleep(10)
    else:
        raise TimeoutError("Instagram container did not finish processing in time")

    # Step 3: publish
    publish_resp = requests.post(
        f"{BASE_URL}/{ig_user_id}/media_publish",
        data={"creation_id": container_id, "access_token": access_token},
    )
    publish_resp.raise_for_status()
    media_id = publish_resp.json()["id"]
    print(f"[instagram] published -> media id {media_id}")
    return media_id


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Usage: python -m src.uploaders.instagram <path/to/clip.mp4> "<caption>"')
        sys.exit(1)

    caption = sys.argv[2] if len(sys.argv) > 2 else ""
    upload(sys.argv[1], caption)