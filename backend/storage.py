"""Thread-safe SQLite persistence and macOS Keychain credentials.

API keys never enter SQLite, JSON configuration, logs, or a child process argv.
"""
from __future__ import annotations

import copy
from contextlib import contextmanager
import ctypes
import json
import platform
import sqlite3
import threading
from pathlib import Path


DEFAULT_SETTINGS = {
    "mode": "auto",
    "recognition_language": "auto",
    "cloud": {"base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini"},
}
ACTIVE_STATUSES = {"queued", "extracting", "transcribing", "translating", "summarizing"}


class Storage:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.data_dir / "library.sqlite3"
        self._lock = threading.RLock()
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
            connection.execute("CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY CHECK (id=1), payload TEXT NOT NULL)")
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(self.path, timeout=30)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def save_project(self, project: dict) -> dict:
        payload = json.dumps(project, ensure_ascii=False, allow_nan=False)
        with self._lock, self._connection() as connection:
            connection.execute("INSERT INTO projects(id,payload) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload", (project["id"], payload))
        return copy.deepcopy(project)

    def get_project(self, project_id: str) -> dict | None:
        with self._lock, self._connection() as connection:
            row = connection.execute("SELECT payload FROM projects WHERE id=?", (project_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def update_project(self, project_id: str, **changes) -> dict:
        with self._lock:
            project = self.get_project(project_id)
            if project is None:
                raise KeyError(project_id)
            project.update(changes)
            return self.save_project(project)

    def list_projects(self) -> list[dict]:
        with self._lock, self._connection() as connection:
            rows = connection.execute("SELECT payload FROM projects ORDER BY rowid DESC").fetchall()
        return [json.loads(row[0]) for row in rows]

    def load_settings(self) -> dict:
        settings = copy.deepcopy(DEFAULT_SETTINGS)
        with self._lock, self._connection() as connection:
            row = connection.execute("SELECT payload FROM settings WHERE id=1").fetchone()
        if row:
            saved = json.loads(row[0])
            settings.update({key: saved[key] for key in ("mode", "recognition_language") if key in saved})
            settings["cloud"].update({key: saved.get("cloud", {})[key] for key in ("base_url", "model") if key in saved.get("cloud", {})})
        return settings

    def save_settings(self, settings: dict) -> dict:
        # Whitelist fields: even a caller accidentally including a key cannot persist it.
        clean = {"mode": settings["mode"], "recognition_language": settings["recognition_language"], "cloud": {key: settings["cloud"][key] for key in ("base_url", "model")}}
        with self._lock, self._connection() as connection:
            connection.execute("INSERT INTO settings(id,payload) VALUES(1,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload", (json.dumps(clean, ensure_ascii=False),))
        return clean

    def recover_interrupted(self):
        for project in self.list_projects():
            if project.get("status") in ACTIVE_STATUSES:
                has_results = bool(project.get("segments") or project.get("chapters") or project.get("overview"))
                self.update_project(project["id"], status="partial" if has_results else "error", error="上次处理已中断，已保留现有结果。点击重试继续。", stage_message="等待重试")


class MacKeychain:
    """Minimal Security.framework bridge; no shell commands or third-party modules."""
    SERVICE = "com.freddie.lingua.cloud"
    ACCOUNT = "default"
    NOT_FOUND = -25300

    def __init__(self):
        if platform.system() != "Darwin":
            raise OSError("macOS Keychain unavailable")
        self.cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        self.sec = ctypes.CDLL("/System/Library/Frameworks/Security.framework/Security")
        pointer = ctypes.c_void_p
        self.cf.CFStringCreateWithCString.argtypes = [pointer, ctypes.c_char_p, ctypes.c_uint32]
        self.cf.CFStringCreateWithCString.restype = pointer
        self.cf.CFDataCreate.argtypes = [pointer, pointer, ctypes.c_long]
        self.cf.CFDataCreate.restype = pointer
        self.cf.CFDataGetLength.argtypes = [pointer]
        self.cf.CFDataGetLength.restype = ctypes.c_long
        self.cf.CFDataGetBytePtr.argtypes = [pointer]
        self.cf.CFDataGetBytePtr.restype = pointer
        self.cf.CFDictionaryCreate.argtypes = [pointer, ctypes.POINTER(pointer), ctypes.POINTER(pointer), ctypes.c_long, pointer, pointer]
        self.cf.CFDictionaryCreate.restype = pointer
        self.cf.CFRelease.argtypes = [pointer]
        self.sec.SecItemCopyMatching.argtypes = [pointer, ctypes.POINTER(pointer)]
        self.sec.SecItemCopyMatching.restype = ctypes.c_int32
        self.sec.SecItemAdd.argtypes = [pointer, pointer]
        self.sec.SecItemAdd.restype = ctypes.c_int32
        self.sec.SecItemUpdate.argtypes = [pointer, pointer]
        self.sec.SecItemUpdate.restype = ctypes.c_int32
        self.sec.SecItemDelete.argtypes = [pointer]
        self.sec.SecItemDelete.restype = ctypes.c_int32

    def _constant(self, name, library=None):
        return ctypes.c_void_p.in_dll(library or self.sec, name).value

    def _string(self, value):
        return self.cf.CFStringCreateWithCString(None, value.encode("utf-8"), 0x08000100)

    def _dictionary(self, pairs):
        keys = (ctypes.c_void_p * len(pairs))(*(pair[0] for pair in pairs))
        values = (ctypes.c_void_p * len(pairs))(*(pair[1] for pair in pairs))
        key_callbacks = ctypes.addressof(ctypes.c_byte.in_dll(self.cf, "kCFTypeDictionaryKeyCallBacks"))
        value_callbacks = ctypes.addressof(ctypes.c_byte.in_dll(self.cf, "kCFTypeDictionaryValueCallBacks"))
        return self.cf.CFDictionaryCreate(None, keys, values, len(pairs), key_callbacks, value_callbacks)

    def _query(self, extras=()):
        service, account = self._string(self.SERVICE), self._string(self.ACCOUNT)
        try:
            return self._dictionary([(self._constant("kSecClass"), self._constant("kSecClassGenericPassword")), (self._constant("kSecAttrService"), service), (self._constant("kSecAttrAccount"), account), *extras])
        finally:
            self.cf.CFRelease(service)
            self.cf.CFRelease(account)

    def get(self):
        query = self._query([(self._constant("kSecReturnData"), self._constant("kCFBooleanTrue", self.cf))])
        result = ctypes.c_void_p()
        try:
            status = self.sec.SecItemCopyMatching(query, ctypes.byref(result))
            if status == self.NOT_FOUND:
                return ""
            if status:
                raise OSError("Keychain access failed")
            return ctypes.string_at(self.cf.CFDataGetBytePtr(result), self.cf.CFDataGetLength(result)).decode("utf-8")
        finally:
            self.cf.CFRelease(query)
            if result.value:
                self.cf.CFRelease(result)

    def set(self, key):
        encoded = key.encode("utf-8")
        data = self.cf.CFDataCreate(None, ctypes.c_char_p(encoded), len(encoded))
        query = self._query()
        attributes = self._dictionary([(self._constant("kSecValueData"), data)])
        addition = None
        try:
            status = self.sec.SecItemUpdate(query, attributes)
            if status == self.NOT_FOUND:
                addition = self._query([(self._constant("kSecValueData"), data)])
                status = self.sec.SecItemAdd(addition, None)
            if status:
                raise OSError("Keychain write failed")
        finally:
            for value in (addition, attributes, query, data):
                if value:
                    self.cf.CFRelease(value)

    def delete(self):
        query = self._query()
        try:
            if self.sec.SecItemDelete(query) not in (0, self.NOT_FOUND):
                raise OSError("Keychain deletion failed")
        finally:
            self.cf.CFRelease(query)


class Credentials:
    def __init__(self, keychain_factory=MacKeychain):
        self._lock = threading.RLock()
        self._key = ""
        self._keychain = None
        self.persistent = False
        self.warning = ""
        try:
            self._keychain = keychain_factory()
            self._key = self._keychain.get()
            self.persistent = True
        except Exception:
            self._unavailable()

    def _unavailable(self):
        self.persistent = False
        self.warning = "无法访问 macOS 钥匙串；API 密钥仅在本次运行内存中保存，退出后需重新填写。"

    def get(self):
        with self._lock:
            return self._key

    def set(self, key):
        with self._lock:
            self._key = key
            try:
                if self._keychain is None:
                    raise OSError()
                self._keychain.set(key)
                self.persistent, self.warning = True, ""
            except Exception:
                self._unavailable()

    def clear(self):
        with self._lock:
            self._key = ""
            try:
                if self._keychain is None:
                    raise OSError()
                self._keychain.delete()
                self.persistent, self.warning = True, ""
            except Exception:
                self._unavailable()
                self.warning = "当前运行已清除 API 密钥，但无法确认钥匙串中的旧密钥已删除。请在“钥匙串访问”中检查服务 com.freddie.lingua.cloud（沿用旧版密钥存储）。"
