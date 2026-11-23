#!/usr/bin/env python3
"""Exercise genuine local recognition/translation/summary using generated speech."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--models-dir", type=Path, default=Path.home() / "Library/Application Support/Freddie Lingua")
    args = parser.parse_args()
    workspace = ROOT / ".freddie-data/smoke"
    workspace.mkdir(parents=True, exist_ok=True)
    for name in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"):
        os.environ[name] = "1"
    os.environ["NUMBA_CACHE_DIR"] = str(workspace / "cache/numba")
    os.environ["MPLCONFIGDIR"] = str(workspace / "cache/matplotlib")
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    text = (
        "Today we will talk about how to focus in a distracted world. "
        "We often blame ourselves for losing focus, but the environment around us matters. "
        "Every notification creates a small decision. Should I keep working, or should I check my phone? "
        "Before you begin, turn off unnecessary notifications and move your phone out of sight. "
        "Choose one task and define what finished looks like. Give it a clear block of time. "
        "A useful break gives your attention room to recover. Stand up, walk around, and rest your eyes. "
        "Focus is easier when your environment supports the work you want to do."
    )
    audio = workspace / "focus.aiff"
    media = workspace / "Freddie Lingua 验证片段.mp4"
    if not media.exists():
        subprocess.run(["say", "-v", "Samantha", "-r", "165", "-o", str(audio), text], check=True)
        subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=0x10252a:s=1280x720:r=24", "-i", str(audio), "-shortest", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart", str(media)], check=True)
    from backend.engines import EngineService
    from backend.server import Application
    engine = EngineService(args.models_dir)
    def no_cloud(*_args, **_kwargs):
        raise AssertionError("离线验证中不得调用云端")
    engine._generate_cloud = no_cloud
    app = Application(workspace / "results", ROOT / "frontend", engine=engine)
    app.save_settings({"mode": "local", "recognition_language": "auto"})
    project = app.import_path(str(media))
    app.start_processing(project["id"])
    deadline = time.monotonic() + 600
    last = None
    while time.monotonic() < deadline:
        current = app.project(project["id"])
        stage = current["status"]
        if stage != last:
            print(f"{stage}: {current.get('stage_message', '')}", flush=True)
            last = stage
        if stage in {"completed", "partial", "error", "cancelled"}:
            break
        time.sleep(0.5)
    else:
        app.cancel_processing(project["id"])
        raise RuntimeError("本地流程验证超时。")
    app.close()
    report = {
        "status": current["status"], "language": current.get("detected_language"),
        "segments": len(current.get("segments", [])),
        "translated": sum(bool(s.get("translation")) for s in current.get("segments", [])),
        "chapters": len(current.get("chapters", [])), "mode_used": current.get("mode_used"),
        "overview": current.get("overview"), "error": current.get("error"),
        "project_id": current["id"], "media": str(media)
    }
    (workspace / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    assert report["status"] == "completed", report["error"]
    assert report["language"] == "en", "英语识别未通过"
    assert report["segments"] > 0 and report["translated"] == report["segments"]
    assert report["chapters"] > 0 and report["mode_used"] == "local"


if __name__ == "__main__":
    main()
