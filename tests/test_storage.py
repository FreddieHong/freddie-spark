import tempfile
import unittest
from pathlib import Path

from backend.storage import Credentials, Storage


class MemoryKeychain:
    key = ""
    def get(self):
        return self.key
    def set(self, key):
        self.key = key
    def delete(self):
        self.key = ""


class StorageTests(unittest.TestCase):
    def test_restart_preserves_results_and_recovers_interrupted_job(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Storage(Path(directory))
            store.save_project({"id": "p1", "status": "translating", "segments": [{"text": "Hello", "translation": "你好"}], "_source_path": "/original.mp4"})
            reopened = Storage(Path(directory))
            reopened.recover_interrupted()
            project = reopened.get_project("p1")
            self.assertEqual(project["status"], "partial")
            self.assertEqual(project["segments"][0]["translation"], "你好")
            self.assertEqual(project["_source_path"], "/original.mp4")

    def test_settings_whitelist_never_persists_api_key(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Storage(Path(directory))
            settings = {"mode": "cloud", "recognition_language": "ja", "cloud": {"base_url": "https://example.com/v1", "model": "example", "api_key": "VERY-SECRET", "has_api_key": True}, "api_key": "OTHER-SECRET"}
            store.save_settings(settings)
            reopened = Storage(Path(directory))
            self.assertEqual(reopened.load_settings()["recognition_language"], "ja")
            for file in Path(directory).iterdir():
                self.assertNotIn(b"SECRET", file.read_bytes())
            self.assertNotIn("api_key", reopened.load_settings()["cloud"])

    def test_unavailable_keychain_uses_memory_only(self):
        def unavailable():
            raise OSError("unavailable")
        credentials = Credentials(unavailable)
        credentials.set("session-secret")
        self.assertEqual(credentials.get(), "session-secret")
        self.assertFalse(credentials.persistent)
        self.assertIn("本次运行", credentials.warning)
        self.assertEqual(Credentials(unavailable).get(), "")

    def test_keychain_roundtrip_and_explicit_delete(self):
        keychain = MemoryKeychain()
        credentials = Credentials(lambda: keychain)
        credentials.set("saved-secret")
        self.assertTrue(credentials.persistent)
        self.assertEqual(Credentials(lambda: keychain).get(), "saved-secret")
        credentials.clear()
        self.assertEqual(keychain.get(), "")


if __name__ == "__main__":
    unittest.main()
