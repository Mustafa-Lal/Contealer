"""
uploaders/youtube.py

Uploads a video to YouTube (as a Short) using the YouTube Data API v3.

--- One-time setup (you have to do this manually, I can't do it for you) ---
1. Go to https://console.cloud.google.com/, create a project.
2. Enable the "YouTube Data API v3" for that project.
3. Create OAuth 2.0 credentials of type "Desktop app".
4. Download the JSON and save it as client_secret.json in the project root.
5. First time you run this, a browser window will open asking you to log
   into the YouTube account you want to upload to, and grant permission.
   After that, credentials are cached in token.json so you won't need to
   log in again (until the token expires/is revoked).

Note: new/unverified Google Cloud projects are capped at 10,000 quota
units/day by default, and each upload costs 1,600 units (~6 uploads/day).
For higher volume, submit your project for verification.

Usage:
    python -m src.uploaders.youtube path/to/clip.mp4 "My Short Title"
"""

from __future__ import annotations

import sys
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
CLIENT_SECRET_FILE = Path(__file__).resolve().parent.parent.parent / "client_secret.json"
TOKEN_FILE = Path(__file__).resolve().parent.parent.parent / "token.json"


def _get_credentials() -> Credentials:
    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CLIENT_SECRET_FILE.exists():
                raise FileNotFoundError(
                    f"Missing {CLIENT_SECRET_FILE}. Download OAuth client credentials "
                    "from Google Cloud Console (Desktop app type) and save them there."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET_FILE), SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN_FILE.write_text(creds.to_json())

    return creds


def upload(
    video_path: str | Path,
    title: str,
    description: str = "",
    privacy_status: str = "public",
) -> str:
    """Upload a video to YouTube. Returns the resulting video ID."""
    video_path = Path(video_path)
    if not video_path.exists():
        raise FileNotFoundError(f"No such file: {video_path}")

    creds = _get_credentials()
    youtube = build("youtube", "v3", credentials=creds)

    if "#shorts" not in title.lower() and "#shorts" not in description.lower():
        description = f"{description}\n\n#Shorts".strip()

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "categoryId": "22",  # People & Blogs
        },
        "status": {"privacyStatus": privacy_status},
    }

    media = MediaFileUpload(str(video_path), chunksize=-1, resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"[youtube] upload progress: {int(status.progress() * 100)}%")

    video_id = response["id"]
    print(f"[youtube] uploaded -> https://youtube.com/shorts/{video_id}")
    return video_id


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print('Usage: python -m src.uploaders.youtube <video_path> "<title>"')
        sys.exit(1)

    upload(sys.argv[1], sys.argv[2])