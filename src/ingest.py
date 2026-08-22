"""
ingest.py

Takes a URL and downloads the video into data/incoming/.

- If the URL points to a site yt-dlp knows how to handle (YouTube, Twitch,
  Twitter/X, TikTok, etc.), it uses yt-dlp to fetch the best quality video.
- Otherwise it falls back to a plain HTTP streaming download (for direct
  links to .mp4 / .mov / etc. files).

Usage:
    python -m src.ingest "https://www.youtube.com/watch?v=XXXXXXXX"
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
from urllib.parse import urlparse

import requests
import yt_dlp
from yt_dlp.networking.impersonate import ImpersonateTarget

INCOMING_DIR = Path(__file__).resolve().parent.parent / "data" / "incoming"
DIRECT_FILE_EXTENSIONS = (".mp4", ".mov", ".mkv", ".webm", ".avi")


def _looks_like_direct_file(url: str) -> bool:
    path = urlparse(url).path.lower()
    return path.endswith(DIRECT_FILE_EXTENSIONS)


def _download_direct_file(url: str, dest_dir: Path) -> Path:
    """Stream-download a direct link to a video file."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    ext = Path(urlparse(url).path).suffix or ".mp4"
    out_path = dest_dir / f"{uuid.uuid4().hex}{ext}"

    with requests.get(url, stream=True, timeout=30) as r:
        r.raise_for_status()
        with open(out_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)

    return out_path


def _download_with_ytdlp(url: str, dest_dir: Path) -> Path:
    """Download via yt-dlp (handles YouTube, TikTok, Twitter/X, Twitch, etc.)."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    out_template = str(dest_dir / f"{uuid.uuid4().hex}.%(ext)s")

    base_opts = {
        "outtmpl": out_template,
        "format": "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/b",
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "extractor_args": {"youtube": ["player_client=ios"]},
    }

    # Try with chrome impersonation first (helps dodge bot detection on some
    # sites). Note: when using yt-dlp as a library (not the CLI), the
    # "impersonate" option must be an ImpersonateTarget instance, not a raw
    # string -- the CLI normally does that string->object parsing for you.
    # If the impersonate target isn't available in this environment (e.g.
    # curl_cffi/yt-dlp version mismatch), fall back to a plain request
    # instead of crashing the whole pipeline.
    try:
        ydl_opts = {**base_opts, "impersonate": ImpersonateTarget.from_str("chrome")}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            return Path(ydl.prepare_filename(info)).with_suffix(".mp4")
    except (yt_dlp.utils.YoutubeDLError, AssertionError) as e:
        print(f"[ingest] chrome impersonation unavailable ({e!r}); retrying without it.")
        with yt_dlp.YoutubeDL(base_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            return Path(ydl.prepare_filename(info)).with_suffix(".mp4")


def ingest(url: str, dest_dir: Path = INCOMING_DIR) -> Path:
    """
    Download `url` into `dest_dir` and return the local file path.
    """
    if _looks_like_direct_file(url):
        path = _download_direct_file(url, dest_dir)
    else:
        path = _download_with_ytdlp(url, dest_dir)

    print(f"[ingest] downloaded -> {path}")
    return path


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python -m src.ingest <url>")
        sys.exit(1)

    ingest(sys.argv[1])