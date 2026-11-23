"""Deterministic, local-only project for UI integration checks. No cloud/model use."""
from pathlib import Path
import json
import subprocess
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.server import Application, LocalHTTPServer
from backend.storage import Credentials


class NoKeychain:
    def get(self): return ""
    def set(self, value): pass
    def delete(self): pass


class InstalledModels:
    def models_status(self):
        return [{"id": kind, "name": kind, "installed": True} for kind in ("asr", "llm")]


fixture_dir = ROOT / "build/ui-test-data"
fixture_dir.mkdir(parents=True, exist_ok=True)
video_path = fixture_dir / "ui-verification.mp4"
if not video_path.exists():
    subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=0x10252a:s=640x360:r=12", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=16000", "-t", "35.4", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast", "-c:a", "aac", "-movflags", "+faststart", str(video_path)], check=True)
app = Application(fixture_dir, ROOT / "frontend", engine=InstalledModels(), credentials=Credentials(NoKeychain()))
project = {
    "id": "ui-check", "title": "独立滚动与字幕复制验证", "file_name": "UI verification.mp4",
    "duration": 35.4, "detected_language": "en", "status": "completed", "progress": 100,
    "overview": "这是一份界面集成测试内容，用于验证视频播放与阅读互不干扰，以及按当前阅读模式复制字幕。",
    "mode_used": "local", "error": None, "warnings": [], "created_at": "2026-11-23T00:00:00Z",
    "_source_path": str(video_path),
    "segments": [{"id": i, "start": i * .5, "end": (i + 1) * .5,
                  "text": f"Sentence {i + 1}: remove distractions and focus on one task.",
                  "translation": f"第 {i + 1} 句：减少干扰，专注于当前的一项任务。"} for i in range(60)],
    "chapters": [{"id": i, "start": i * 2, "end": (i + 1) * 2,
                  "title": f"章节 {i + 1} · 关注当前任务", "summary": "先关闭非必要通知，明确任务的完成标准，再安排适当的专注与休息时间。",
                  "bullets": ["减少干扰，保留当前任务需要的内容。", "保持阅读和视频播放彼此独立。"]} for i in range(15)],
}
app.storage.save_project(project)
server = LocalHTTPServer(app)
print(json.dumps({"url": f"{app.origin}/?token={app.token}"}), flush=True)
try:
    server.serve_forever(poll_interval=.1)
finally:
    app.close()
    server.server_close()
