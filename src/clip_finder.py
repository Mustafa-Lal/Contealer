"""
clip_finder.py

Takes the video and the hooks file (output of hooks.py), and produces a
list of clips: each with a title, the hook text, and its start/end time
in the video.

Steps:
1. Ask Groq to turn the freeform hooks file into structured {title, hook}
   pairs (one API call, free tier). If this fails, fallback to heuristic.
2. Transcribe the video with word-level timestamps (faster-whisper, local,
   no API cost).
3. Fuzzy-match each hook's text against the timestamped transcript to find
   where it starts and ends in the video.

Output: <video_name>_clips.json next to the video, e.g.:
[
  {
    "title": "He almost quit on day one",
    "hook": "I almost walked out of that interview.",
    "start": 42.1,
    "end": 47.8
  },
  ...
]

Usage:
    python -m src.clip_finder <video_path> <hooks_path>
"""

from __future__ import annotations

import json
import os
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

try:
    import torch
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

from dotenv import load_dotenv
from faster_whisper import WhisperModel
from groq import Groq

load_dotenv()

MODEL = "llama-3.3-70b-versatile"
WHISPER_MODEL = "small.en"

MIN_DURATION = 30.0  # seconds
MAX_DURATION = 60.0  # seconds

START_PAD = 0.2  # seconds of breathing room before the matched start
END_PAD = 0.3    # seconds of breathing room after the matched end

STRUCTURE_PROMPT = """Here is a list of hook excerpts extracted from a video transcript:

<hooks>
{hooks_text}
</hooks>

For each hook, output a short punchy title (5-8 words, suitable as a video
title) and the exact hook excerpt.

Respond with ONLY valid JSON, no other text, in this exact shape:
[
  {{"title": "...", "hook": "..."}},
  ...
]"""


def _normalize(word: str) -> str:
    return re.sub(r"[^\w']+", "", word).lower()


def _structure_hooks(hooks_text: str) -> list[dict]:
    """Try to use LLM to structure hooks; fallback to heuristic if LLM fails."""
    # Try LLM first
    try:
        client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": STRUCTURE_PROMPT.format(hooks_text=hooks_text)}],
        )
        raw = response.choices[0].message.content.strip()
        # Model may wrap the JSON in a code fence despite instructions; strip it if present.
        raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
        if not raw:
            raise ValueError("Empty response from LLM")
        structured = json.loads(raw)
        # Validate structure
        if isinstance(structured, list) and all(
            isinstance(item, dict) and "title" in item and "hook" in item for item in structured
        ):
            return structured
        else:
            raise ValueError("Invalid structure from LLM")
    except Exception as e:
        # Log warning and fallback to heuristic
        print(f"[clip_finder] LLM structuring failed ({e}); using heuristic fallback.")
        # Heuristic: each line that looks like a hook (starting with "- " or just a line)
        hooks = []
        for line in hooks_text.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            # Remove leading dash or bullet
            if line.startswith("-"):
                line = line[1:].strip()
            # Use line as hook; generate a simple title from first few words
            hook = line
            # Create title: first 5 words, max 8 words
            words = hook.split()
            if len(words) > 8:
                title = " ".join(words[:8]) + "..."
            elif len(words) > 5:
                title = " ".join(words[:5]) + "..."
            else:
                title = hook if len(hook) <= 30 else hook[:27] + "..."
            hooks.append({"title": title, "hook": hook})
        if not hooks:
            # Ultimate fallback: use first sentence as hook
            first_sentence = hooks_text.strip().split('\n')[0]
            if first_sentence:
                hooks.append({"title": "Highlight from video", "hook": first_sentence})
        return hooks


def _get_word_timestamps(video_path: Path) -> list[dict]:
    # Determine device and compute type for Whisper
    if TORCH_AVAILABLE and torch.cuda.is_available():
        device = "cuda"
        compute_type = "float16"
        print("[clip_finder] CUDA detected, using GPU for faster transcription.")
    else:
        device = "cpu"
        compute_type = "int8"
        if TORCH_AVAILABLE:
            print("[clip_finder] CUDA not available, using CPU.")
        else:
            print("[clip_finder] Torch not installed, using CPU (consider installing torch for GPU support).")

    model = WhisperModel(WHISPER_MODEL, device=device, compute_type=compute_type)
    segments, _ = model.transcribe(str(video_path), word_timestamps=True)

    words = []
    for seg in segments:
        for w in seg.words or []:
            words.append({"word": w.word, "start": w.start, "end": w.end})
    return words


def _find_span(hook_text: str, words: list[dict]) -> tuple[float, float] | None:
    """Fuzzy-match hook_text against the timestamped word list, return (start, end)
    with the span adjusted to fall within [MIN_DURATION, MAX_DURATION] seconds."""
    transcript_norm = [_normalize(w["word"]) for w in words]
    hook_norm = [_normalize(t) for t in hook_text.split()]

    transcript_str = " ".join(transcript_norm)
    hook_str = " ".join(hook_norm)

    # char offset -> word index lookup
    offsets = []
    pos = 0
    for tok in transcript_norm:
        offsets.append(pos)
        pos += len(tok) + 1  # +1 for the joining space

    matcher = SequenceMatcher(None, transcript_str, hook_str, autojunk=False)
    match = matcher.find_longest_match(0, len(transcript_str), 0, len(hook_str))

    if match.size < 4:  # too short to trust
        return None

    start_char, end_char = match.a, match.a + match.size

    start_idx = max(i for i, off in enumerate(offsets) if off <= start_char)
    end_idx = next(
        (i for i, off in enumerate(offsets) if off >= end_char), len(offsets) - 1
    )
    end_idx = max(end_idx, start_idx)

    start_time = max(0.0, words[start_idx]["start"] - START_PAD)
    end_time = words[end_idx]["end"] + END_PAD

    # Enforce the 30-60s window using neighboring words as needed.
    duration = end_time - start_time

    if duration < MIN_DURATION:
        # Extend forward into subsequent words first.
        i = end_idx
        while i + 1 < len(words) and (words[i + 1]["end"] - start_time) < MIN_DURATION:
            i += 1
        end_idx = min(i + 1, len(words) - 1)
        end_time = words[end_idx]["end"] + END_PAD
        duration = end_time - start_time

        # If still short (near end of video), pull the start back instead.
        if duration < MIN_DURATION:
            start_time = max(0.0, end_time - MIN_DURATION)

    elif duration > MAX_DURATION:
        # Trim end time back to the max window.
        end_time = start_time + MAX_DURATION

    return round(start_time, 2), round(end_time, 2)


def find_clips(video_path: str | Path, hooks_path: str | Path) -> Path:
    video_path = Path(video_path)
    hooks_path = Path(hooks_path)

    if not video_path.exists():
        raise FileNotFoundError(f"No such file: {video_path}")
    if not hooks_path.exists():
        raise FileNotFoundError(f"No such file: {hooks_path}")

    hooks_text = hooks_path.read_text(encoding="utf-8")

    print("[clip_finder] structuring hooks via LLM (with fallback)...")
    structured = _structure_hooks(hooks_text)

    print("[clip_finder] transcribing video for word timestamps...")
    words = _get_word_timestamps(video_path)

    clips = []
    for item in structured:
        span = _find_span(item["hook"], words)
        if span is None:
            print(f"[clip_finder] could not locate hook in video, skipping: {item['hook'][:60]}...")
            continue
        start, end = span
        clips.append({"title": item["title"], "hook": item["hook"], "start": start, "end": end})

    out_path = video_path.with_name(video_path.stem + "_clips.json")
    out_path.write_text(json.dumps(clips, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[clip_finder] wrote -> {out_path}")
    return out_path


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python -m src.clip_finder <video_path> <hooks_path>")
        sys.exit(1)

    find_clips(sys.argv[1], sys.argv[2])