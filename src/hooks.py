"""
hooks.py

Takes a transcript .txt file and extracts the best "hooks" — funny,
emotional, or exciting lines/moments that would grab attention as the
opening of a short clip. Saves the result to a text file next to it
(same name, _hooks.txt suffix).

Uses Groq's free API (fast, no cost) instead of a paid LLM.
Get a free key at https://console.groq.com — no credit card required.
Requires GROQ_API_KEY to be set (e.g. in a .env file, loaded via
python-dotenv, or exported in your shell).

Usage:
    python -m src.hooks data/incoming/video.txt
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from groq import Groq

load_dotenv()

MODEL = "llama-3.3-70b-versatile"

PROMPT = """Here is the transcript of a video:

<transcript>
{transcript}
</transcript>

Find the best hooks in this transcript — moments that are funny, emotional,
or exciting, and would work as a standalone short clip.

Each hook must be a CONTIGUOUS excerpt copied verbatim from the transcript,
roughly 30 to 60 seconds of spoken audio (about 75-150 words at typical
speaking pace). Not a single line — a full excerpt with enough context to
make sense on its own, but not so long it drags.

For each hook, output:
1. The exact excerpt, copied verbatim from the transcript (75-150 words)
2. Which category it is: Funny, Emotional, or Exciting
3. A one-sentence reason it works as a hook

List them in order from strongest to weakest. Only include genuinely strong
hooks (skip a category if the transcript has none of that type)."""


def extract_hooks(transcript_path: str | Path) -> Path:
    transcript_path = Path(transcript_path)
    if not transcript_path.exists():
        raise FileNotFoundError(f"No such file: {transcript_path}")

    transcript = transcript_path.read_text(encoding="utf-8")

    client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": PROMPT.format(transcript=transcript)}],
    )

    hooks_text = response.choices[0].message.content

    out_path = transcript_path.with_name(transcript_path.stem + "_hooks.txt")
    out_path.write_text(hooks_text, encoding="utf-8")
    print(f"[hooks] wrote -> {out_path}")
    return out_path


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python -m src.hooks <transcript_path>")
        sys.exit(1)

    extract_hooks(sys.argv[1])