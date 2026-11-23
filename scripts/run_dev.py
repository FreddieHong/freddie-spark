#!/usr/bin/env python3
"""Run the same backend/UI as the desktop app, using a browser for development."""
import os
from pathlib import Path
import secrets
import sys

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
os.environ.setdefault("FREDDIE_DATA_DIR", str(root / ".freddie-data"))
from backend.server import main

sys.argv = ["freddie-lingua", "--port", "8766", "--data-dir", os.environ["FREDDIE_DATA_DIR"], "--frontend-dir", str(root / "frontend"), "--token", secrets.token_urlsafe(32)]
main()
