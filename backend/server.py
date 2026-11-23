"""Authenticated, loopback-only HTTP service for Freddie Lingua.

Run: python -m backend.server --port 0 --data-dir PATH --frontend-dir PATH
The first stdout line is the launch handshake consumed by the native shell.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import mimetypes
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import signal
import sys
import threading
import time
from urllib.parse import parse_qs, quote, unquote, urlsplit
import uuid

from . import __version__
from .exports import build_export
from .storage import Credentials, Storage


MEDIA_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".mpg", ".mpeg", ".mts", ".m2ts", ".mxf", ".wmv", ".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg", ".opus", ".aiff", ".aif"}
MAX_UPLOAD_BYTES = 50 * 1024 ** 3
COOKIE_NAME = "freddie_session"


class APIError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def parse_byte_range(header: str | None, size: int) -> tuple[int, int] | None:
    """Parse exactly one RFC 9110 byte range. Invalid/unsatisfiable -> ValueError."""
    if header is None:
        return None
    if size < 1 or not re.fullmatch(r"bytes=\d*-\d*", header.strip()):
        raise ValueError("无效的媒体范围")
    first, last = header.strip()[6:].split("-", 1)
    if not first:
        if not last or int(last) <= 0:
            raise ValueError("无效的媒体范围")
        return max(0, size - int(last)), size - 1
    start = int(first)
    end = min(int(last), size - 1) if last else size - 1
    if start >= size or end < start:
        raise ValueError("媒体范围超出文件")
    return start, end


def public_project(project: dict, compact=False):
    result = {key: copy.deepcopy(value) for key, value in project.items() if not key.startswith("_")}
    if compact:
        result.pop("segments", None)
        result.pop("chapters", None)
    return result


def executable(name):
    configured = os.environ.get(f"FREDDIE_{name.upper()}")
    choices = [configured] if configured else [shutil.which(name), f"/opt/homebrew/bin/{name}", f"/usr/local/bin/{name}"]
    for candidate in choices:
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    raise APIError(503, f"找不到 {name}。请安装 FFmpeg 后重新打开应用。")


class Application:
    def __init__(self, data_dir: Path, frontend_dir: Path, token=None, engine=None, credentials=None):
        self.data_dir, self.frontend_dir = Path(data_dir).resolve(), Path(frontend_dir).resolve()
        self.storage = Storage(self.data_dir)
        self.storage.recover_interrupted()
        self.credentials = credentials if credentials is not None else Credentials()
        self.token = token or secrets.token_urlsafe(32)
        self.session = secrets.token_urlsafe(48)
        self.port = 0
        self._job_lock = threading.RLock()
        self._job_thread = None
        self._job_id = None
        self._cancel = threading.Event()
        self._model_lock = threading.RLock()
        self._model_jobs = {}
        self._closed = False
        if engine is None:
            from .engines import EngineService
            engine = EngineService(self.data_dir)
        self.engine = engine

    @property
    def origin(self):
        return f"http://127.0.0.1:{self.port}"

    def project(self, project_id):
        project = self.storage.get_project(project_id)
        if project is None:
            raise APIError(404, "找不到该视频，请从资料库重新选择。")
        return project

    def settings(self):
        settings = self.storage.load_settings()
        settings["cloud"]["has_api_key"] = bool(self.credentials.get())
        settings["credential_persistent"] = self.credentials.persistent
        settings["credential_warning"] = self.credentials.warning
        return settings

    def save_settings(self, incoming):
        if not isinstance(incoming, dict):
            raise APIError(400, "设置格式无效")
        settings = self.storage.load_settings()
        mode = incoming.get("mode", settings["mode"])
        if mode not in ("auto", "cloud", "local"):
            raise APIError(400, "请选择自动、云端或本地模式")
        language = incoming.get("recognition_language", settings["recognition_language"])
        if not isinstance(language, str) or not re.fullmatch(r"auto|[a-z]{2,3}(?:-[A-Za-z]{2,8})?", language):
            raise APIError(400, "识别语言代码无效")
        cloud = incoming.get("cloud", {})
        if not isinstance(cloud, dict):
            raise APIError(400, "云端设置格式无效")
        base_url = cloud.get("base_url", settings["cloud"]["base_url"])
        model = cloud.get("model", settings["cloud"]["model"])
        if not isinstance(base_url, str) or len(base_url) > 2048:
            raise APIError(400, "服务地址无效")
        base_url = base_url.strip().rstrip("/")
        try:
            endpoint = urlsplit(base_url)
            valid = endpoint.scheme in ("https", "http") and endpoint.hostname and not endpoint.username and not endpoint.password and not endpoint.query and not endpoint.fragment
            valid = valid and (endpoint.scheme == "https" or endpoint.hostname in ("localhost", "127.0.0.1", "::1"))
            endpoint.port
        except ValueError:
            valid = False
        if not base_url and mode != "cloud":
            valid = True
        if not valid:
            raise APIError(400, "请填写 HTTPS 服务地址；本机服务可使用 HTTP。地址不能包含密钥或查询参数。")
        if not isinstance(model, str) or (not model.strip() and mode == "cloud") or len(model) > 256 or any(ord(character) < 32 for character in model):
            raise APIError(400, "请填写有效的模型名称")
        api_key = cloud.get("api_key")
        if api_key is not None and (not isinstance(api_key, str) or len(api_key) > 8192):
            raise APIError(400, "API 密钥格式无效")
        settings.update(mode=mode, recognition_language=language)
        settings["cloud"] = {"base_url": base_url, "model": model.strip()}
        self.storage.save_settings(settings)
        if cloud.get("clear_api_key") is True:
            self.credentials.clear()
        elif api_key and api_key.strip():
            self.credentials.set(api_key.strip())
        return self.settings()

    def _safe_error(self, exception):
        if isinstance(exception, (RuntimeError, APIError, ValueError, InterruptedError)):
            message = str(exception) or "处理未能完成，请重试。"
        else:
            message = "处理未能完成，请重试；如仍失败，请检查模型和本地运行环境。"
        key = self.credentials.get()
        if key:
            message = message.replace(key, "[已隐藏密钥]")
        return message[:1200]

    def probe_media(self, path: Path):
        if not path.is_absolute() or not path.is_file() or not os.access(path, os.R_OK):
            raise APIError(400, "请选择可读取的本地视频或音频文件。")
        if path.suffix.lower() not in MEDIA_EXTENSIONS:
            raise APIError(400, "暂不支持该文件格式，请使用 MP4、MOV、MKV、WebM 或常见音频格式。")
        try:
            result = subprocess.run([executable("ffprobe"), "-v", "error", "-show_entries", "format=duration:stream=codec_type", "-of", "json", str(path)], capture_output=True, timeout=45, check=False)
            if result.returncode:
                raise ValueError()
            metadata = json.loads(result.stdout)
            if not any(stream.get("codec_type") == "audio" for stream in metadata.get("streams", [])):
                raise APIError(400, "这个文件没有可读取的音轨，无法识别讲话内容。")
            duration = float(metadata.get("format", {}).get("duration", 0))
            if not math.isfinite(duration) or duration <= 0:
                raise ValueError()
            return duration
        except APIError:
            raise
        except (OSError, ValueError, subprocess.TimeoutExpired, json.JSONDecodeError):
            raise APIError(400, "无法读取这个媒体文件；文件可能损坏、加密或尚未下载完整。") from None

    def import_path(self, path: str, original_name=None):
        if not isinstance(path, str) or not Path(path).is_absolute():
            raise APIError(400, "请选择一个绝对路径的本地文件。")
        media_path = Path(path).resolve()
        duration = self.probe_media(media_path)
        file_name = original_name or media_path.name
        project = {
            "id": uuid.uuid4().hex, "title": Path(file_name).stem, "file_name": file_name,
            "duration": duration, "detected_language": "", "status": "imported", "progress": 0,
            "error": None, "segments": [], "chapters": [], "overview": "", "mode_used": "",
            "created_at": datetime.now(timezone.utc).isoformat(), "warnings": [], "stage_message": "等待开始识别",
            "_source_path": str(media_path),
        }
        return self.storage.save_project(project)

    def models(self):
        with self._model_lock:
            models = copy.deepcopy(self.engine.models_status())
            for model in models:
                model.setdefault("downloading", False)
                model.setdefault("progress", 100 if model.get("installed") else 0)
                model.setdefault("error", None)
                job = self._model_jobs.get(model["id"])
                if job:
                    model.update(job)
                    if model.get("installed") and not job.get("downloading"):
                        model["progress"] = 100
            return models

    def download_model(self, kind):
        if kind not in ("asr", "llm"):
            raise APIError(404, "找不到这个模型")
        with self._model_lock:
            if self._model_jobs.get(kind, {}).get("downloading"):
                return
            if any(model["id"] == kind and model.get("installed") for model in self.engine.models_status()):
                return
            self._model_jobs[kind] = {"downloading": True, "progress": 0, "error": None}
            thread = threading.Thread(target=self._download, args=(kind,), daemon=True, name=f"download-{kind}")
            thread.start()

    @staticmethod
    def _percentage(value):
        try:
            value = float(value)
            if not math.isfinite(value):
                return 0
            return max(0, min(100, value * 100 if value <= 1 else value))
        except (ValueError, TypeError):
            return 0

    def _download(self, kind):
        def progress(value, message=""):
            with self._model_lock:
                self._model_jobs[kind].update(progress=self._percentage(value))
        try:
            self.engine.download_model(kind, progress)
            with self._model_lock:
                installed = any(model["id"] == kind and model.get("installed") for model in self.engine.models_status())
                if not installed:
                    raise RuntimeError("下载结束后未检测到完整模型，请重试。")
                self._model_jobs[kind].update(downloading=False, progress=100, error=None)
        except Exception as exception:
            with self._model_lock:
                self._model_jobs[kind].update(downloading=False, error=self._safe_error(exception))

    def start_processing(self, project_id):
        with self._job_lock:
            if self._closed:
                raise APIError(503, "应用正在退出")
            if self._job_thread is not None and self._job_thread.is_alive():
                raise APIError(409, "已有视频正在处理，请等待完成或先取消当前任务。")
            self.project(project_id)
            self._cancel = threading.Event()
            self._job_id = project_id
            self.storage.update_project(project_id, status="queued", progress=0, error=None, stage_message="已加入处理队列")
            self._job_thread = threading.Thread(target=self._process, args=(project_id, self._cancel), daemon=True, name=f"process-{project_id}")
            self._job_thread.start()
            return self.project(project_id)

    def cancel_processing(self, project_id):
        with self._job_lock:
            self.project(project_id)
            if self._job_id == project_id and self._job_thread and self._job_thread.is_alive():
                self._cancel.set()
                self.storage.update_project(project_id, stage_message="正在取消；已完成的内容会保留")
            return self.project(project_id)

    def _extract(self, project, audio_path, cancelled):
        audio_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = audio_path.with_name("audio.partial.wav")
        command = [executable("ffmpeg"), "-nostdin", "-y", "-v", "error", "-i", project["_source_path"], "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(temporary)]
        process = None
        try:
            process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            while True:
                if cancelled():
                    process.terminate()
                    try:
                        process.communicate(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.communicate()
                    raise InterruptedError("已取消处理，现有结果已保留。")
                try:
                    process.communicate(timeout=0.25)
                    break
                except subprocess.TimeoutExpired:
                    continue
            if process.returncode or not temporary.exists() or temporary.stat().st_size <= 44:
                raise RuntimeError("无法提取音轨，请检查视频文件是否可正常播放。")
            temporary.replace(audio_path)
        finally:
            if process is not None and process.poll() is None:
                process.kill()
                process.communicate()
            if temporary.exists():
                temporary.unlink()

    def _process(self, project_id, cancel_event):
        settings = self.storage.load_settings()
        api_key = self.credentials.get()
        def check_cancel():
            if cancel_event.is_set():
                raise InterruptedError("已取消处理，现有结果已保留。")
        def stage(name, start, end, message):
            check_cancel()
            self.storage.update_project(project_id, status=name, progress=start, stage_message=message)
            def report(value, detail=""):
                check_cancel()
                self.storage.update_project(project_id, progress=round(start + (end - start) * self._percentage(value) / 100, 1), stage_message=self._safe_error(RuntimeError(detail)) if detail else message)
            return report
        try:
            project = self.project(project_id)
            check_cancel()
            segments = project.get("segments") or []
            recognition_matches = project.get("_recognition_language") == settings["recognition_language"]
            if not segments or not recognition_matches:
                if not any(model["id"] == "asr" and model.get("installed") for model in self.engine.models_status()):
                    raise RuntimeError("尚未安装语音识别模型。请先在设置中下载识别模型，再点击重试。")
                stage("extracting", 2, 10, "正在本地提取音轨")
                audio_path = self.data_dir / "audio" / project_id / "audio.wav"
                if not audio_path.exists():
                    self._extract(project, audio_path, cancel_event.is_set)
                report = stage("transcribing", 10, 55, "正在本地识别语言与原文")
                language, segments = self.engine.transcribe(audio_path, settings["recognition_language"], report, cancel_event.is_set)
                check_cancel()
                if not segments:
                    raise RuntimeError("没有识别到可用的讲话内容，请检查音轨或尝试手动指定语言。")
                self.storage.update_project(project_id, segments=segments, detected_language=language, _recognition_language=settings["recognition_language"])
            check_cancel()
            report = stage("translating", 55, 83, "正在翻译中文")
            def retain_segments(partial):
                self.storage.update_project(project_id, segments=copy.deepcopy(partial))
            translated, translation_mode, translation_warnings = self.engine.translate(copy.deepcopy(segments), settings, api_key, report, cancel_event.is_set, retain_segments)
            check_cancel()
            self.storage.update_project(project_id, segments=translated, mode_used=translation_mode, warnings=self._clean_warnings(translation_warnings))
            report = stage("summarizing", 83, 99, "正在按内容分段总结")
            overview, chapters, summary_mode, summary_warnings = self.engine.summarize(translated, settings, api_key, report, cancel_event.is_set)
            check_cancel()
            warnings = list(translation_warnings) + list(summary_warnings)
            if summary_mode != translation_mode:
                warnings.append(f"翻译使用{('云端' if translation_mode == 'cloud' else '本地')}模型，总结使用{('云端' if summary_mode == 'cloud' else '本地')}模型。")
            self.storage.update_project(project_id, status="completed", progress=100, overview=overview, chapters=chapters, mode_used=summary_mode, warnings=self._clean_warnings(warnings), error=None, stage_message="识别、翻译与总结已完成")
        except InterruptedError:
            self.storage.update_project(project_id, status="cancelled", error=None, stage_message="已取消，现有结果已保留")
        except Exception as exception:
            project = self.project(project_id)
            self.storage.update_project(project_id, status="partial" if project.get("segments") or project.get("overview") or project.get("chapters") else "error", error=self._safe_error(exception), stage_message="处理未完成，可重试")
        finally:
            with self._job_lock:
                if self._job_id == project_id:
                    self._job_id = None

    def _clean_warnings(self, warnings):
        return list(dict.fromkeys(self._safe_error(RuntimeError(str(warning))) for warning in warnings if warning))

    def close(self):
        with self._job_lock:
            self._closed = True
            self._cancel.set()
            worker = self._job_thread
        if worker is not None and worker is not threading.current_thread():
            worker.join(timeout=4)


class LocalHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, app, port=0):
        self.app = app
        super().__init__(("127.0.0.1", port), RequestHandler)
        app.port = self.server_address[1]


class RequestHandler(BaseHTTPRequestHandler):
    server_version = "FreddieLingua/0.1"
    protocol_version = "HTTP/1.1"

    @property
    def app(self):
        return self.server.app

    def log_message(self, *args):
        pass  # Launch tokens, filenames and credentials must not enter request logs.

    def _headers(self, status, mime, length, extra=None):
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()

    def _send(self, status, payload, extra=None):
        data = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self._headers(status, "application/json; charset=utf-8", len(data), extra)
        if self.command != "HEAD":
            self.wfile.write(data)

    def _authorize(self, write=False):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
            session = cookie[COOKIE_NAME].value if COOKIE_NAME in cookie else ""
        except Exception:
            session = ""
        if not secrets.compare_digest(session, self.app.session):
            raise APIError(401, "本地会话已过期，请重新打开 Freddie Lingua。")
        origin = self.headers.get("Origin")
        if origin is not None and origin != self.app.origin:
            raise APIError(403, "已拒绝非本机应用来源的请求")
        if write and self.headers.get("Sec-Fetch-Site") in ("cross-site", "same-site"):
            raise APIError(403, "已拒绝跨站写入请求")

    def _validate_host(self):
        if self.headers.get("Host") != f"127.0.0.1:{self.app.port}":
            raise APIError(403, "无效的本地服务地址")

    def _body_length(self, limit):
        if self.headers.get("Transfer-Encoding"):
            raise APIError(400, "请使用带有明确文件长度的请求")
        try:
            value = self.headers.get("Content-Length", "0")
            if not value.isdigit():
                raise ValueError()
            length = int(value)
        except ValueError:
            raise APIError(400, "请求长度无效") from None
        if length > limit:
            raise APIError(413, "文件或请求过大")
        return length

    def _json_body(self):
        length = self._body_length(2 * 1024 * 1024)
        if length == 0:
            return {}
        data = self.rfile.read(length)
        if len(data) != length:
            raise APIError(400, "请求未完整接收")
        try:
            payload = json.loads(data)
            if not isinstance(payload, dict):
                raise ValueError()
            return payload
        except (ValueError, UnicodeDecodeError):
            raise APIError(400, "请求 JSON 格式无效") from None

    def do_GET(self):
        self._dispatch()

    def do_HEAD(self):
        self._dispatch()

    def do_POST(self):
        self._dispatch()

    def do_PUT(self):
        self._dispatch()

    def do_OPTIONS(self):
        self._send(403, {"error": "不允许跨站访问本地服务"})

    def _dispatch(self):
        try:
            self._validate_host()
            path = urlsplit(self.path).path
            query = parse_qs(urlsplit(self.path).query)
            read = self.command in ("GET", "HEAD")
            if read and path == "/api/health":
                return self._send(200, {"ok": True, "version": __version__})
            if read and path == "/" and "token" in query:
                supplied = query["token"][0]
                if not secrets.compare_digest(supplied, self.app.token):
                    raise APIError(401, "启动凭证无效，请重新打开应用。")
                self._headers(303, "text/plain; charset=utf-8", 0, {"Location": "/", "Set-Cookie": f"{COOKIE_NAME}={self.app.session}; HttpOnly; SameSite=Strict; Path=/"})
                return
            if path.startswith("/api/"):
                self._authorize(write=not read)
                return self._api(path, query, read)
            if not read:
                raise APIError(405, "不支持该请求方式")
            self._static(path)
        except APIError as exception:
            # Do not reuse a connection containing an unread rejected request body.
            self.close_connection = True
            self._send(exception.status, {"error": self.app._safe_error(exception)}, {"Connection": "close"})
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            self.close_connection = True
        except Exception as exception:
            self.close_connection = True
            self._send(500, {"error": self.app._safe_error(exception)}, {"Connection": "close"})

    def _api(self, path, query, read):
        if path == "/api/settings":
            if read:
                return self._send(200, self.app.settings())
            if self.command == "PUT":
                return self._send(200, self.app.save_settings(self._json_body()))
        if path == "/api/models" and read:
            return self._send(200, {"models": self.app.models()})
        match = re.fullmatch(r"/api/models/(asr|llm)/download", path)
        if match and self.command == "POST":
            self._json_body()
            self.app.download_model(match[1])
            return self._send(202, {"models": self.app.models()})
        if path == "/api/projects" and read:
            return self._send(200, {"projects": [public_project(project, compact=True) for project in self.app.storage.list_projects()]})
        if path == "/api/import-path" and self.command == "POST":
            payload = self._json_body()
            paths = payload.get("paths")
            if not isinstance(paths, list) or not paths:
                raise APIError(400, "请选择一个本地视频文件")
            return self._send(201, {"project": public_project(self.app.import_path(paths[0]))})
        if path == "/api/import" and self.command == "POST":
            return self._upload()
        match = re.fullmatch(r"/api/projects/([A-Za-z0-9_-]+)(?:/(process|cancel|media|export))?", path)
        if match:
            project_id, action = match.groups()
            project = self.app.project(project_id)
            if read and action is None:
                return self._send(200, {"project": public_project(project)})
            if self.command == "POST" and action in ("process", "cancel"):
                self._json_body()
                result = self.app.start_processing(project_id) if action == "process" else self.app.cancel_processing(project_id)
                return self._send(202 if action == "process" else 200, {"project": public_project(result)})
            if read and action == "media":
                return self._media(project)
            if read and action == "export":
                try:
                    data, mime, filename = build_export(project, query.get("format", ["md"])[0], query.get("content", ["summary"])[0])
                except ValueError as exception:
                    raise APIError(400, str(exception)) from None
                self._headers(200, mime, len(data), {"Content-Disposition": f"attachment; filename=Freddie-Lingua.{filename.rsplit('.', 1)[-1]}; filename*=UTF-8''{quote(filename)}"})
                if self.command != "HEAD":
                    self.wfile.write(data)
                return
        raise APIError(404, "找不到这个接口或不支持该操作")

    def _upload(self):
        length = self._body_length(MAX_UPLOAD_BYTES)
        if length <= 0:
            raise APIError(400, "文件为空，请重新选择")
        filename = unquote(self.headers.get("X-Filename", ""))
        filename = Path(filename.replace("\\", "/")).name
        if not filename or any(ord(character) < 32 for character in filename) or Path(filename).suffix.lower() not in MEDIA_EXTENSIONS:
            raise APIError(400, "文件名或媒体格式无效")
        upload_dir = self.app.data_dir / "imports"
        upload_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        destination = upload_dir / f"{uuid.uuid4().hex}{Path(filename).suffix.lower()}"
        try:
            with destination.open("xb") as output:
                remaining = length
                while remaining:
                    chunk = self.rfile.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise APIError(400, "文件传输中断，请重新导入")
                    output.write(chunk)
                    remaining -= len(chunk)
            project = self.app.import_path(str(destination), original_name=filename)
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        self._send(201, {"project": public_project(project)})

    def _media(self, project):
        path = Path(project["_source_path"])
        if not path.is_file():
            raise APIError(404, "原始视频已移动或删除，请重新导入；已有字幕和总结仍保留。")
        size = path.stat().st_size
        try:
            requested = parse_byte_range(self.headers.get("Range"), size)
        except ValueError:
            self._headers(416, "application/octet-stream", 0, {"Content-Range": f"bytes */{size}", "Accept-Ranges": "bytes"})
            return
        start, end = requested if requested is not None else (0, size - 1)
        length = max(0, end - start + 1)
        extra = {"Accept-Ranges": "bytes"}
        if requested is not None:
            extra["Content-Range"] = f"bytes {start}-{end}/{size}"
        mime = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        self._headers(206 if requested is not None else 200, mime, length, extra)
        if self.command == "HEAD":
            return
        with path.open("rb") as media:
            media.seek(start)
            remaining = length
            while remaining:
                chunk = media.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def _static(self, request_path):
        relative = unquote(request_path).lstrip("/") or "index.html"
        path = (self.app.frontend_dir / relative).resolve()
        if not path.is_relative_to(self.app.frontend_dir) or any(part.startswith(".") for part in Path(relative).parts) or not path.is_file():
            raise APIError(404, "找不到该页面")
        if path.suffix.lower() not in {".html", ".js", ".css", ".svg", ".png", ".jpg", ".jpeg", ".webp", ".ico", ".woff", ".woff2", ".ttf", ".map"}:
            raise APIError(404, "找不到该资源")
        data = path.read_bytes()
        mime = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        if mime.startswith("text/") or path.suffix == ".js":
            mime += "; charset=utf-8"
        self._headers(200, mime, len(data))
        if self.command != "HEAD":
            self.wfile.write(data)


def default_data_dir():
    configured = os.environ.get("FREDDIE_DATA_DIR")
    if configured:
        return Path(configured).expanduser()
    if os.environ.get("FREDDIE_PRODUCTION") == "1":
        return Path.home() / "Library" / "Application Support" / "Freddie Lingua"
    return Path(__file__).resolve().parent.parent / ".freddie-data"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Freddie Lingua 本地服务")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--data-dir", type=Path, default=default_data_dir())
    parser.add_argument("--frontend-dir", type=Path, default=Path(__file__).resolve().parent.parent / "frontend")
    parser.add_argument("--token", default=None)
    args = parser.parse_args(argv)
    app = Application(args.data_dir, args.frontend_dir, token=args.token)
    server = LocalHTTPServer(app, port=args.port)
    print(json.dumps({"port": app.port, "token": app.token}), flush=True)
    def terminate(signum, frame):
        raise KeyboardInterrupt
    previous_sigterm = signal.signal(signal.SIGTERM, terminate)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        app.close()
        server.server_close()
        signal.signal(signal.SIGTERM, previous_sigterm)


if __name__ == "__main__":
    main()
