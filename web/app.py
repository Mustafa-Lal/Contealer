"""
web/app.py

Flask backend for the ClipForge dashboard. This file does NOT reimplement
any pipeline logic -- it imports and calls the existing functions from
src/ in the same order the CLI pipeline already uses, and exposes them
over a small JSON API for the frontend in web/static + web/templates.

Routes:
    GET    /                                    -> renders the dashboard
    POST   /api/process                          -> kicks off the pipeline (ingest -> ... -> verticalize)
                                                     in a background thread and returns immediately
    GET    /api/status                            -> poll this while processing to get the current step
    GET    /api/clips                             -> list already-generated vertical clips on disk
    POST   /api/clips/<filename>/publish/<platform> -> publish one clip to one platform
                                                        (facebook | youtube | instagram | tiktok)
    DELETE /api/clips/<filename>                   -> delete a generated vertical clip
    GET    /media/<file>                            -> serves an individual vertical clip (mp4)
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import traceback
from pathlib import Path
from urllib.parse import urlparse

from flask import Flask, jsonify, render_template, request, send_from_directory

# ---------------------------------------------------------------------------
# Make sure the project root is importable as `src.*`, regardless of how
# this app is launched (via run.py, `flask run`, a WSGI server, etc).
# ---------------------------------------------------------------------------
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# ---------------------------------------------------------------------------
# Existing pipeline functions -- imported, never reimplemented.
# ---------------------------------------------------------------------------
from src.ingest import ingest
from src.transcribe import transcribe
from src.hooks import extract_hooks
from src.clip_finder import find_clips
from src.clipper import extract_clips, CLIPS_DIR as _CLIPPER_CLIPS_DIR, _slugify
from src.verticalize import verticalize_folder

# NOTE: src/upload_all.py itself is intentionally NOT imported here (it
# uploads to every platform in one go and isn't relevant to the per-clip,
# per-platform buttons in the UI). We import the individual uploader
# modules it wraps directly instead. Each import is wrapped separately
# because youtube.py depends on the Google API client libraries, which
# may not be installed yet -- if so, the YouTube publish button simply
# reports "not available" instead of crashing the whole app.
PLATFORM_UPLOADERS: dict[str, object] = {}

try:
    from src.uploaders import facebook as _facebook_uploader
    PLATFORM_UPLOADERS["facebook"] = _facebook_uploader
except ImportError as exc:
    print(f"[app] facebook uploader unavailable: {exc}")

try:
    from src.uploaders import tiktok as _tiktok_uploader
    PLATFORM_UPLOADERS["tiktok"] = _tiktok_uploader
except ImportError as exc:
    print(f"[app] tiktok uploader unavailable: {exc}")

try:
    from src.uploaders import instagram as _instagram_uploader
    PLATFORM_UPLOADERS["instagram"] = _instagram_uploader
except ImportError as exc:
    print(f"[app] instagram uploader unavailable: {exc}")

try:
    from src.uploaders import youtube as _youtube_uploader
    PLATFORM_UPLOADERS["youtube"] = _youtube_uploader
except ImportError as exc:
    print(f"[app] youtube uploader unavailable: {exc}")

PLATFORM_LABELS = {
    "facebook": "Facebook",
    "youtube": "YouTube",
    "instagram": "Instagram",
    "tiktok": "TikTok",
}

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Paths -- these mirror the directories the existing pipeline modules
# already compute for themselves (ingest.INCOMING_DIR, clipper.CLIPS_DIR),
# recomputed here from web/app.py's own location so both agree on the
# same project-root-relative folders.
# ---------------------------------------------------------------------------
DATA_DIR = ROOT_DIR / "data"
INCOMING_DIR = DATA_DIR / "incoming"
CLIPS_DIR = _CLIPPER_CLIPS_DIR  # data/clips -- reuse clipper.py's own constant
VERTICAL_DIR = CLIPS_DIR / "vertical"

# Tracks which clips have already been published to which platform, e.g.
# {"01_he-almost-quit.mp4": {"youtube": true, "tiktok": true}}. This is UI
# bookkeeping only (so a published button can be disabled/checked on
# reload) -- it has nothing to do with the existing pipeline.
PUBLISH_STATE_FILE = DATA_DIR / "publish_state.json"

for _dir in (INCOMING_DIR, CLIPS_DIR, VERTICAL_DIR):
    _dir.mkdir(parents=True, exist_ok=True)

_publish_state_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Background job state. Only one processing job runs at a time; the frontend
# polls GET /api/status to find out what step it's on and when it's done.
# A lock guards the shared dict since the pipeline runs on a worker thread
# while Flask keeps handling requests on other threads.
# ---------------------------------------------------------------------------
_job_lock = threading.Lock()
_job_state = {
    "active": False,   # is a job currently running?
    "step": None,       # human-readable current step, e.g. "Downloading video..."
    "success": None,    # True/False once finished, None while idle/running
    "error": None,       # human-readable error message if the job failed
    "clips": None,        # list of clip dicts once finished successfully
}


def _set_state(**kwargs) -> None:
    with _job_lock:
        _job_state.update(kwargs)


def _get_state() -> dict:
    with _job_lock:
        return dict(_job_state)


def _validate_url(url: str) -> bool:
    if not url or not isinstance(url, str):
        return False
    url = url.strip()
    if not url:
        return False
    parsed = urlparse(url)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def _load_publish_state() -> dict:
    with _publish_state_lock:
        if not PUBLISH_STATE_FILE.exists():
            return {}
        try:
            data = json.loads(PUBLISH_STATE_FILE.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError) as exc:
            print(f"[app] could not read {PUBLISH_STATE_FILE}: {exc}")
            return {}


def _save_publish_state(state: dict) -> None:
    with _publish_state_lock:
        PUBLISH_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        PUBLISH_STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


# Generic, evergreen short-form tags mixed in alongside the keyword-derived
# ones below. NOTE: these are NOT pulled from any live "what's trending
# right now" data source -- there's no such feed wired into this project.
# It's a simple, deterministic heuristic (title/hook keywords + a handful
# of reliably high-reach short-form tags), not real-time trend data.
GENERIC_HASHTAGS = ["fyp", "viral", "shorts", "reels", "foryou", "trending"]

_HASHTAG_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "of", "to", "in", "on", "for",
    "is", "are", "was", "were", "be", "this", "that", "it", "he", "she",
    "they", "i", "we", "you", "your", "my", "at", "as", "with", "from",
    "by", "so", "just", "not", "his", "her", "its", "their", "than",
}


def _generate_hashtags(title: str, hook: str = "") -> list[str]:
    """Deterministic keyword-based hashtags for a clip: a few words pulled
    from its title/hook plus generic high-reach short-form tags."""
    text = f"{title} {hook}"
    words = re.findall(r"[A-Za-z']+", text.lower())

    keywords = []
    seen = set()
    for word in words:
        if len(word) < 4 or word in _HASHTAG_STOPWORDS or word in seen:
            continue
        seen.add(word)
        keywords.append(word)
        if len(keywords) >= 4:
            break

    tags, seen_tags = [], set()
    for word in keywords + GENERIC_HASHTAGS:
        tag = f"#{word}"
        if tag.lower() not in seen_tags:
            seen_tags.add(tag.lower())
            tags.append(tag)
        if len(tags) >= 8:
            break

    return tags


def _title_from_filename(filename: str) -> str:
    """Fallback display title built from a clip's filename, used when no
    matching *_clips.json entry can be found for it."""
    stem = Path(filename).stem
    parts = stem.split("_", 1)
    name_part = parts[1] if len(parts) == 2 and parts[0].isdigit() else stem
    words = name_part.replace("-", " ").replace("_", " ").split()
    return " ".join(w.capitalize() for w in words) or filename


def _load_all_clip_metadata() -> dict:
    """Build a {slugified_title: clip_dict} map from every *_clips.json
    file written by clip_finder.py under data/incoming/. clipper.py names
    each output file "<index>_<slug-of-title>.mp4" using the same
    _slugify() we import above, so slugs line up exactly with filenames."""
    metadata = {}
    if not INCOMING_DIR.exists():
        return metadata

    for json_path in INCOMING_DIR.glob("*_clips.json"):
        try:
            import json as _json
            clips = _json.loads(json_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"[app] could not read {json_path}: {exc}")
            continue

        if not isinstance(clips, list):
            continue

        for clip in clips:
            if not isinstance(clip, dict) or "title" not in clip:
                continue
            metadata[_slugify(clip["title"])] = clip

    return metadata


def discover_clips() -> list[dict]:
    """Scan data/clips/vertical/ for mp4 files and return what the frontend
    needs to render them, pulling titles/durations from the matching
    *_clips.json entry when one can be found."""
    if not VERTICAL_DIR.exists():
        return []

    metadata = _load_all_clip_metadata()
    publish_state = _load_publish_state()
    results = []

    for mp4_path in sorted(VERTICAL_DIR.glob("*.mp4")):
        stem = mp4_path.stem
        parts = stem.split("_", 1)
        slug = parts[1] if len(parts) == 2 and parts[0].isdigit() else stem

        clip_meta = metadata.get(slug)
        duration = None
        hook = ""
        if clip_meta:
            title = clip_meta.get("title") or _title_from_filename(mp4_path.name)
            hook = clip_meta.get("hook", "")
            try:
                duration = round(float(clip_meta["end"]) - float(clip_meta["start"]))
            except (KeyError, TypeError, ValueError):
                duration = None
        else:
            title = _title_from_filename(mp4_path.name)

        published = publish_state.get(mp4_path.name, {})

        results.append({
            "title": title,
            "filename": mp4_path.name,
            "url": f"/media/{mp4_path.name}",
            "duration": duration,
            "hashtags": _generate_hashtags(title, hook),
            "published": {
                platform: bool(published.get(platform))
                for platform in PLATFORM_LABELS
            },
        })

    return results


def _run_pipeline(url: str) -> None:
    """Runs the existing pipeline, in order, on a background thread.
    Each stage's real function is called as-is; only the status string
    shown in the UI is updated in between stages."""
    try:
        _set_state(active=True, step="Downloading video...", success=None, error=None, clips=None)
        video_path = ingest(url)

        _set_state(step="Generating transcript...")
        transcript_path = transcribe(video_path)

        _set_state(step="Finding hooks...")
        hooks_path = extract_hooks(transcript_path)

        _set_state(step="Finding clips...")
        clips_json_path = find_clips(video_path, hooks_path)

        _set_state(step="Cutting clips...")
        extract_clips(video_path, clips_json_path)

        _set_state(step="Creating vertical videos...")
        verticalize_folder(CLIPS_DIR, VERTICAL_DIR)

        clips = discover_clips()
        _set_state(active=False, step="Done", success=True, error=None, clips=clips)

    except Exception as exc:  # noqa: BLE001 -- surfaced to the UI as a plain message
        traceback.print_exc()  # full trace goes to the server console only
        _set_state(active=False, step=None, success=False, error=str(exc), clips=None)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/process", methods=["POST"])
def api_process():
    with _job_lock:
        if _job_state["active"]:
            return jsonify({
                "success": False,
                "error": "A video is already being processed. Please wait for it to finish.",
            }), 409

    payload = request.get_json(silent=True) or {}
    url = (payload.get("url") or "").strip()

    if not _validate_url(url):
        return jsonify({
            "success": False,
            "error": "Please provide a valid video URL (starting with http:// or https://).",
        }), 400

    thread = threading.Thread(target=_run_pipeline, args=(url,), daemon=True)
    thread.start()

    return jsonify({"success": True, "message": "Processing started"})


@app.route("/api/status")
def api_status():
    return jsonify(_get_state())


@app.route("/api/clips")
def api_clips():
    return jsonify({"clips": discover_clips()})


def _resolve_clip_path(filename: str) -> Path | None:
    """Shared safety check for anything that touches a clip file by name:
    strips any directory components and confirms the result both matches
    the original name and actually resolves inside VERTICAL_DIR. Returns
    None if the filename is unsafe or doesn't point at a real clip."""
    safe_name = Path(filename).name

    if safe_name != filename or not safe_name.lower().endswith(".mp4"):
        return None

    candidate = (VERTICAL_DIR / safe_name).resolve()
    vertical_resolved = VERTICAL_DIR.resolve()

    if vertical_resolved not in candidate.parents:
        return None

    return candidate


@app.route("/api/clips/<path:filename>/publish/<platform>", methods=["POST"])
def api_publish_clip(filename, platform):
    """Publish a single clip to a single platform. This is the real
    upload -- it calls into src/uploaders/<platform>.py, which is
    imported but never modified. Nothing here reimplements upload logic;
    it only looks up the clip's title/hook, checks whether it's already
    been published on this platform, and calls the existing upload()."""
    platform = (platform or "").lower()
    if platform not in PLATFORM_LABELS:
        return jsonify({"success": False, "error": f"Unknown platform: {platform}"}), 400

    clip_path = _resolve_clip_path(filename)
    if clip_path is None or not clip_path.is_file():
        return jsonify({"success": False, "error": "Clip not found."}), 404

    safe_name = clip_path.name

    state = _load_publish_state()
    if state.get(safe_name, {}).get(platform):
        return jsonify({
            "success": False,
            "error": f"This clip has already been published to {PLATFORM_LABELS[platform]}.",
        }), 409

    uploader = PLATFORM_UPLOADERS.get(platform)
    if uploader is None:
        return jsonify({
            "success": False,
            "error": (
                f"{PLATFORM_LABELS[platform]} uploader isn't available "
                f"(missing dependency). Check the server console."
            ),
        }), 503

    metadata = _load_all_clip_metadata()
    stem = clip_path.stem
    parts = stem.split("_", 1)
    slug = parts[1] if len(parts) == 2 and parts[0].isdigit() else stem
    clip_meta = metadata.get(slug, {})

    # Prefer the catchy, LLM-generated title from clip_finder.py's *_clips.json
    # (falls back to a cleaned-up filename only if that metadata is missing).
    title = clip_meta.get("title") or _title_from_filename(safe_name)
    hook = clip_meta.get("hook", "")
    hashtags = _generate_hashtags(title, hook)
    hashtag_line = " ".join(hashtags)

    # Caption used for platforms whose "caption"/"description" field is
    # what actually gets shown to viewers: lead with the catchy title,
    # then the hashtags on their own line to help the clip get found.
    caption = f"{title}\n\n{hashtag_line}".strip() if hashtag_line else title

    try:
        if platform == "facebook":
            uploader.upload(clip_path, caption)
        elif platform == "tiktok":
            uploader.upload(clip_path, caption)
        elif platform == "youtube":
            # youtube.py already appends "#Shorts" to the description itself;
            # we pass our own hashtags through as the rest of the description.
            uploader.upload(clip_path, title, hashtag_line)
        elif platform == "instagram":
            uploader.upload(clip_path, caption)
    except Exception as exc:  # noqa: BLE001 -- surfaced to the UI as a plain message
        traceback.print_exc()  # full trace goes to the server console only
        return jsonify({"success": False, "error": str(exc)}), 500

    state.setdefault(safe_name, {})[platform] = True
    _save_publish_state(state)

    return jsonify({"success": True, "filename": safe_name, "platform": platform})


@app.route("/api/clips/<path:filename>", methods=["DELETE"])
def api_delete_clip(filename):
    """Delete a generated vertical clip (data/clips/vertical/<file>.mp4)
    and forget any publish state recorded for it. This only removes the
    vertical clip shown in the dashboard -- it does not touch the
    downloaded source video or the horizontal clip in data/clips/."""
    clip_path = _resolve_clip_path(filename)
    if clip_path is None or not clip_path.is_file():
        return jsonify({"success": False, "error": "Clip not found."}), 404

    safe_name = clip_path.name

    try:
        clip_path.unlink()
    except OSError as exc:
        return jsonify({"success": False, "error": f"Could not delete file: {exc}"}), 500

    state = _load_publish_state()
    if safe_name in state:
        del state[safe_name]
        _save_publish_state(state)

    return jsonify({"success": True, "filename": safe_name})


@app.route("/media/<path:filename>")
def media(filename):
    """Serve a single vertical clip. Only plain .mp4 filenames directly
    inside data/clips/vertical/ are ever served -- no path traversal, no
    arbitrary file access."""
    clip_path = _resolve_clip_path(filename)

    if clip_path is None or not clip_path.is_file():
        return jsonify({"error": "Not found"}), 404

    return send_from_directory(VERTICAL_DIR.resolve(), clip_path.name, mimetype="video/mp4")


if __name__ == "__main__":
    # Convenience for `python web/app.py` during development.
    # Normal usage is `python run.py` from the project root.
    app.run(host="127.0.0.1", port=5000, debug=True, threaded=True)