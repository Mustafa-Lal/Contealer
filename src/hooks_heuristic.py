"""
hooks_heuristic.py

Heuristic hook extraction as a fallback when LLM is not available or fails.
Selects interesting sentences based on simple heuristics:
- Contains exclamation or question marks
- Contains uppercase words (indicating emphasis)
- Contains certain keywords (amazing, incredible, wow, etc.)
- Length between 20 and 30 words (approx)
"""

from __future__ import annotations

import re
from pathlib import Path

def extract_hooks_heuristic(transcript_path: str | Path) -> Path:
    transcript_path = Path(transcript_path)
    if not transcript_path.exists():
        raise FileNotFoundError(f"No such file: {transcript_path}")

    transcript = transcript_path.read_text(encoding="utf-8")
    # Simple sentence split (not perfect but okay)
    sentences = re.split(r'(?<=[.!?])\s+', transcript.strip())
    # Filter sentences
    keywords = set(['amazing', 'incredible', 'wow', 'unbelievable', 'fantastic',
                    'hilarious', 'crazy', 'insane', 'shocking', 'awesome',
                    'love', 'hate', 'best', 'worst', 'never', 'ever', 'first',
                    'last', 'major', 'breakthrough', 'secret', 'exposed'])
    scored = []
    for sent in sentences:
        if len(sent) < 10:
            continue
        score = 0
        # exclamation or question
        if '!' in sent or '?' in sent:
            score += 2
        # uppercase words
        uppercase_words = re.findall(r'\b[A-Z]{2,}\b', sent)
        score += len(uppercase_words)
        # keyword matches
        lower_sent = sent.lower()
        for kw in keywords:
            if kw in lower_sent:
                score += 2
        # length preference: 20-30 words
        word_count = len(sent.split())
        if 15 <= word_count <= 35:
            score += 1
        elif word_count < 10:
            score -= 1
        scored.append((score, sent))
    # Sort by score descending
    scored.sort(key=lambda x: x[0], reverse=True)
    # Take top 5 sentences (or fewer if not enough)
    top_n = min(5, len(scored))
    selected = [sent for score, sent in scored[:top_n] if score > 0]
    # If none selected, fallback to first few sentences
    if not selected:
        selected = sentences[:3]

    out_path = transcript_path.with_name(transcript_path.stem + "_hooks.txt")
    # Write each hook on its own line (could add dummy category/reason lines)
    # For compatibility with find_clips, we just need text lines; the LLM structuring step will handle.
    out_lines = []
    for hook in selected:
        out_lines.append(f"- {hook}")
    out_path.write_text("\n".join(out_lines), encoding="utf-8")
    print(f"[hooks_heuristic] wrote -> {out_path}")
    return out_path


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        print("Usage: python -m src.hooks_heuristic <transcript_path>")
        sys.exit(1)
    extract_hooks_heuristic(sys.argv[1])