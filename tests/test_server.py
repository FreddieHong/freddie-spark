import http.client
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from urllib.parse import quote

from backend.server import APIError, Application, COOKIE_NAME, LocalHTTPServer, parse_byte_range
from backend.storage import Credentials


class MemoryKeychain:
    def get(self):
        return ""
    def set(self, key):
        pass
    def delete(self):
        pass


class FakeEngine:
    def __init__(self):
        self.translation_fails = False
        self.summary_fails = False
        self.block = False
        self.downloads = []
        self.installed = {"asr": True, "llm": False}

    def models_status(self):
        return [{"id": kind, "installed": installed, "name": kind, "description": "test model", "size_label": "test"} for kind, installed in self.installed.items()]

    def download_model(self, kind, progress):
        self.downloads.append(kind)
        progress(0.5, "下载中")
        self.installed[kind] = True

    def transcribe(self, path, language, progress, cancelled):
        progress(1, "识别完成")
        return "en", [{"id": 0, "start": 0.1, "end": 1.5, "text": "Hello.", "translation": ""}]

    def translate(self, segments, settings, key, progress, cancelled, on_segments):
        segments[0]["translation"] = "你好。"
        on_segments(segments)
        while self.block and not cancelled():
            time.sleep(0.01)
        if cancelled():
            raise InterruptedError()
        if self.translation_fails:
            raise RuntimeError("翻译服务暂时不可用")
        progress(1, "翻译完成")
        return segments, "local", []

    def summarize(self, segments, settings, key, progress, cancelled):
        if self.summary_fails:
            raise RuntimeError("总结服务暂时不可用")
        return "一段问候。", [{"id": 0, "start": 0.1, "end": 1.5, "title": "问候", "summary": "说话人向观众问好。", "bullets": []}], "local", []


class RangeTests(unittest.TestCase):
    def test_supported_ranges(self):
        for header, expected in [(None, None), ("bytes=0-3", (0, 3)), ("bytes=4-", (4, 9)), ("bytes=-3", (7, 9)), ("bytes=-99", (0, 9)), ("bytes=2-999", (2, 9))]:
            with self.subTest(header=header):
                self.assertEqual(parse_byte_range(header, 10), expected)

    def test_invalid_ranges(self):
        for header in ("bytes=10-", "bytes=5-2", "bytes=-0", "bytes=-", "bytes=0-1,3-4", "items=0-1", "bytes=a-b"):
            with self.subTest(header=header), self.assertRaises(ValueError):
                parse_byte_range(header, 10)


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.base = Path(self.directory.name)
        frontend = self.base / "frontend"
        frontend.mkdir()
        (frontend / "index.html").write_text("<h1>Freddie Lingua</h1>")
        self.engine = FakeEngine()
        self.app = Application(self.base / "data", frontend, token="launch-token", engine=self.engine, credentials=Credentials(MemoryKeychain))
        self.server = LocalHTTPServer(self.app)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.cookie = f"{COOKIE_NAME}={self.app.session}"
        source = self.base / "source.mp4"
        source.write_bytes(b"0123456789")
        self.project = {"id": "test-project", "title": "测试视频", "file_name": "source.mp4", "duration": 2, "status": "imported", "progress": 0, "error": None, "segments": [], "chapters": [], "overview": "", "mode_used": "", "created_at": "2026-11-19T00:00:00Z", "detected_language": "", "warnings": [], "_source_path": str(source)}
        self.app.storage.save_project(self.project)
        # Actual FFmpeg and ML are tested separately; queue tests start with a prepared WAV.
        audio = self.app.data_dir / "audio" / self.project["id"] / "audio.wav"
        audio.parent.mkdir(parents=True)
        audio.write_bytes(b"prepared-audio-for-fake-engine")

    def tearDown(self):
        self.app.close()
        if self.app._job_thread:
            self.app._job_thread.join(timeout=2)
        self.server.shutdown()
        self.server.server_close()
        self.directory.cleanup()

    def request(self, method, path, payload=None, authenticated=True, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.app.port, timeout=3)
        request_headers = {"Cookie": self.cookie} if authenticated else {}
        request_headers.update(headers or {})
        body = json.dumps(payload).encode() if payload is not None else None
        if body:
            request_headers["Content-Type"] = "application/json"
        connection.request(method, path, body=body, headers=request_headers)
        response = connection.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return result

    def wait_for_job(self):
        self.app._job_thread.join(timeout=3)
        self.assertFalse(self.app._job_thread.is_alive())
        return self.app.project(self.project["id"])

    def test_health_is_public_but_projects_and_media_require_session(self):
        self.assertEqual(self.request("GET", "/api/health", authenticated=False)[0], 200)
        for path in ("/api/settings", "/api/projects", "/api/projects/test-project/media"):
            self.assertEqual(self.request("GET", path, authenticated=False)[0], 401)

    def test_launch_token_becomes_http_only_cookie_and_redirect(self):
        status, headers, _ = self.request("GET", "/?token=launch-token", authenticated=False)
        self.assertEqual(status, 303)
        self.assertEqual(headers["Location"], "/")
        self.assertIn("HttpOnly", headers["Set-Cookie"])
        self.assertIn("SameSite=Strict", headers["Set-Cookie"])
        self.assertEqual(self.request("GET", "/?token=wrong", authenticated=False)[0], 401)

    def test_write_requires_trusted_origin_even_with_cookie(self):
        self.assertEqual(self.request("PUT", "/api/settings", {"mode": "local"}, headers={"Origin": "https://untrusted.example"})[0], 403)
        self.assertEqual(self.request("PUT", "/api/settings", {"mode": "local"}, headers={"Origin": self.app.origin})[0], 200)
        self.assertEqual(self.app.settings()["mode"], "local")
        self.assertEqual(self.request("PUT", "/api/settings", {"mode": "auto"}, headers={"Sec-Fetch-Site": "cross-site"})[0], 403)

    def test_host_header_blocks_dns_rebinding(self):
        self.assertEqual(self.request("GET", "/api/health", headers={"Host": "attacker.example"})[0], 403)

    def test_source_path_is_not_public(self):
        status, _, data = self.request("GET", "/api/projects/test-project")
        self.assertEqual(status, 200)
        self.assertNotIn("_source_path", data.decode())

    def test_media_range_streaming_and_unsatisfiable_range(self):
        status, headers, data = self.request("GET", "/api/projects/test-project/media", headers={"Range": "bytes=2-5"})
        self.assertEqual((status, data), (206, b"2345"))
        self.assertEqual(headers["Content-Range"], "bytes 2-5/10")
        status, _, data = self.request("GET", "/api/projects/test-project/media", headers={"Range": "bytes=-3"})
        self.assertEqual((status, data), (206, b"789"))
        status, headers, data = self.request("GET", "/api/projects/test-project/media", headers={"Range": "bytes=99-"})
        self.assertEqual(status, 416)
        self.assertEqual(headers["Content-Range"], "bytes */10")
        self.assertEqual(data, b"")

    def test_translation_failure_keeps_original_and_partial_translation(self):
        self.engine.translation_fails = True
        self.app.start_processing(self.project["id"])
        project = self.wait_for_job()
        self.assertEqual(project["status"], "partial")
        self.assertEqual(project["segments"][0]["text"], "Hello.")
        self.assertEqual(project["segments"][0]["translation"], "你好。")
        self.assertIn("翻译服务", project["error"])
        self.engine.translation_fails = False
        self.app.start_processing(self.project["id"])
        self.assertEqual(self.wait_for_job()["status"], "completed")

    def test_summary_failure_keeps_translations(self):
        self.engine.summary_fails = True
        self.app.start_processing(self.project["id"])
        project = self.wait_for_job()
        self.assertEqual(project["status"], "partial")
        self.assertEqual(project["segments"][0]["translation"], "你好。")
        self.assertEqual(project["overview"], "")

    def test_cancel_preserves_results_and_concurrent_job_rejected(self):
        self.engine.block = True
        self.app.start_processing(self.project["id"])
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and not self.app.project(self.project["id"])["segments"]:
            time.sleep(0.01)
        with self.assertRaises(APIError) as context:
            self.app.start_processing(self.project["id"])
        self.assertEqual(context.exception.status, 409)
        self.app.cancel_processing(self.project["id"])
        project = self.wait_for_job()
        self.assertEqual(project["status"], "cancelled")
        self.assertTrue(project["segments"])

    def test_model_download_is_explicit_and_verified(self):
        self.assertEqual(self.engine.downloads, [])
        self.request("GET", "/api/models")
        self.assertEqual(self.engine.downloads, [])
        status, _, _ = self.request("POST", "/api/models/llm/download", {})
        self.assertEqual(status, 202)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and self.app.models()[1]["downloading"]:
            time.sleep(0.01)
        self.assertEqual(self.engine.downloads, ["llm"])
        self.assertTrue(self.app.models()[1]["installed"])

    def test_uninstalled_asr_fails_without_downloading(self):
        self.engine.installed["asr"] = False
        self.app.start_processing(self.project["id"])
        project = self.wait_for_job()
        self.assertEqual(project["status"], "error")
        self.assertIn("下载识别模型", project["error"])
        self.assertEqual(self.engine.downloads, [])

    def test_settings_preserves_key_until_explicit_clear(self):
        self.request("PUT", "/api/settings", {"cloud": {"api_key": "very-secret"}})
        self.assertEqual(self.app.credentials.get(), "very-secret")
        status, _, data = self.request("PUT", "/api/settings", {"cloud": {"api_key": ""}})
        self.assertEqual(status, 200)
        self.assertNotIn("very-secret", data.decode())
        self.assertTrue(json.loads(data)["cloud"]["has_api_key"])
        self.request("PUT", "/api/settings", {"cloud": {"clear_api_key": True}})
        self.assertEqual(self.app.credentials.get(), "")

    def test_local_and_automatic_modes_allow_empty_cloud_configuration(self):
        for mode in ("local", "auto"):
            status, _, data = self.request("PUT", "/api/settings", {"mode": mode, "cloud": {"base_url": "", "model": ""}})
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(data)["mode"], mode)
        self.assertEqual(self.request("PUT", "/api/settings", {"mode": "cloud"})[0], 400)

    def test_static_path_traversal_is_rejected(self):
        (self.base / "secret.html").write_text("private")
        self.assertEqual(self.request("GET", "/%2e%2e/secret.html")[0], 404)

    def test_completed_project_exports_actual_bilingual_content(self):
        self.app.start_processing(self.project["id"])
        self.wait_for_job()
        status, headers, data = self.request("GET", "/api/projects/test-project/export?format=srt&content=bilingual")
        self.assertEqual(status, 200)
        self.assertIn("filename*=UTF-8''", headers["Content-Disposition"])
        self.assertIn("Hello.\n你好。", data.decode())
        self.assertEqual(self.request("GET", "/api/projects/test-project/export?format=srt&content=summary")[0], 400)


if __name__ == "__main__":
    unittest.main()
