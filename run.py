"""
run.py

Entrypoint for the ClipForge dashboard.

Usage:
    python run.py

Then open http://127.0.0.1:5000
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from web.app import app

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True, threaded=True)