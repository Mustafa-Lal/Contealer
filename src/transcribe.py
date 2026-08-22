"""
transcribe.py

Takes a video/audio file and saves its spoken-word transcript as a plain
text file next to it (same name, .txt extension).

Usage:
    python -m src.transcribe data/incoming/video.mp4
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    import torch
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

from faster_whisper import WhisperModel

MODEL_SIZE = "small.en"  # English-only, fast on CPU


def transcribe(media_path: str | Path) -> Path:
    media_path = Path(media_path)
    if not media_path.exists():
        raise FileNotFoundError(f"No such file: {media_path}")

    # Determine device and compute type
    if TORCH_AVAILABLE and torch.cuda.is_available():
        device = "cuda"
        compute_type = "float16"
        print("[transcribe] CUDA detected, using GPU for faster transcription.")
    else:
        device = "cpu"
        compute_type = "int8"
        if TORCH_AVAILABLE:
            print("[transcribe] CUDA not available, using CPU.")
        else:
            print("[transcribe] Torch not installed, using CPU (consider installing torch for GPU support).")

    model = WhisperModel(MODEL_SIZE, device=device, compute_type=compute_type)
    segments, _ = model.transcribe(str(media_path))

    text = " ".join(seg.text.strip() for seg in segments)

    out_path = media_path.with_suffix(".txt")
    out_path.write_text(text, encoding="utf-8")
    print(f"[transcribe] wrote -> {out_path}")
    return out_path


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python -m src.transcribe <media_path>")
        sys.exit(1)

    transcribe(sys.argv[1])