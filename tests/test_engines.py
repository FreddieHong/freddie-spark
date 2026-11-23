import io
import json
import tempfile
import types
import unittest
import urllib.error
import wave
from pathlib import Path
from unittest.mock import Mock, patch

from backend.engines import (
    EngineService, MODEL_SPECS, _InvalidOutput, _Route, _safe_json,
    _split_text, _validate_summary, _validate_translation, _merge_fragments,
)


def settings(mode="cloud"):
    return {"mode": mode, "cloud": {"base_url": "https://example.test/v1", "model": "demo"}}


def segments(count=3, long=False):
    return [{"id": 10 + i, "start": i * 10, "end": i * 10 + 8,
             "text": ("Source words. " * 80 if long else f"Sentence {i}."), "translation": ""}
            for i in range(count)]


def translated_response(prompt, *_):
    items = json.loads(prompt.split("原文：", 1)[1].split("\n上一次", 1)[0])
    return json.dumps({"translations": [{"id": x["id"], "translation": "这是中文译文。"} for x in reversed(items)]})


def summary_response(prompt, *_):
    items = json.loads(prompt.split("转写数据：", 1)[1].split("\n上一次", 1)[0])
    return json.dumps({"overview": "视频说明了如何减少干扰并安排专注时间。", "chapters": [
        {"start_id": items[0]["id"], "end_id": items[-1]["id"], "title": "减少干扰", "summary": "先观察干扰，再安排专注时段。", "bullets": ["减少通知"]}
    ]})


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.service = EngineService(Path(self.temp.name))
        self.progress = Mock()
        self.cancelled = lambda: False

    def install_fixture(self, kind):
        path = self.service._model_path(kind)
        path.mkdir(parents=True)
        (path / "config.json").write_text('{"model_type":"test"}')
        (path / "model.safetensors").write_bytes(b"w" * 2048)
        if kind == "llm":
            (path / "tokenizer.json").write_text('{"tokens":["a"]}')
            (path / "tokenizer_config.json").write_text('{}')
        (path / ".freddie-model.json").write_text(json.dumps({"repo": MODEL_SPECS[kind]["repo"], "complete": True}))
        return path

    def test_startup_does_not_import_or_download_models(self):
        with patch("urllib.request.build_opener") as remote:
            rows = self.service.models_status()
        self.assertEqual([x["installed"] for x in rows], [False, False])
        remote.assert_not_called()

    def test_partial_or_missing_shard_is_not_installed(self):
        path = self.install_fixture("llm")
        self.assertTrue(self.service._model_installed("llm"))
        self.assertEqual(self.service.models_status()[1]["progress"], 100)
        (path / "model.safetensors.index.json").write_text(json.dumps({"weight_map": {"a": "missing.safetensors"}}))
        self.assertFalse(self.service._model_installed("llm"))
        (path / "model.safetensors.index.json").write_text(json.dumps({"weight_map": {"a": "../outside.safetensors"}}))
        self.assertFalse(self.service._model_installed("llm"))

    def test_weights_without_completion_marker_are_not_ready(self):
        path = self.install_fixture("asr")
        (path / ".freddie-model.json").unlink()
        self.assertFalse(self.service._model_installed("asr"))

    def test_missing_local_pack_fails_without_remote_request(self):
        with patch.object(self.service, "_generate_cloud") as remote:
            with self.assertRaisesRegex(RuntimeError, "下载"):
                self.service.translate(segments(), settings("local"), "key", self.progress, self.cancelled, Mock())
        remote.assert_not_called()

    def test_translation_reordered_response_keeps_source_ids_and_times(self):
        source = segments()
        callbacks = []
        with patch.object(self.service, "_generate_cloud", side_effect=translated_response):
            result, mode, warnings = self.service.translate(source, settings(), "key", self.progress, self.cancelled, callbacks.append)
        self.assertEqual(mode, "cloud")
        self.assertFalse(warnings)
        self.assertEqual([x["id"] for x in result], [10, 11, 12])
        self.assertEqual([x["start"] for x in result], [0, 10, 20])
        self.assertTrue(all(x["translation"] for x in result))
        self.assertTrue(all(not x["translation"] for x in source))
        self.assertTrue(callbacks)

    def test_translation_rejects_missing_and_duplicate_ids(self):
        items = [{"id": "a"}, {"id": "b"}]
        for rows in ([{"id": "a", "translation": "甲"}],
                     [{"id": "a", "translation": "甲"}, {"id": "a", "translation": "乙"}],
                     [{"id": "a", "translation": "甲"}, {"id": "unknown", "translation": "乙"}]):
            with self.assertRaises(_InvalidOutput):
                _validate_translation({"translations": rows}, items)

    def test_invalid_model_translation_does_not_become_completed(self):
        callback = Mock()
        with patch.object(self.service, "_generate_cloud", return_value='{"translations":[]}') as generate:
            with self.assertRaisesRegex(RuntimeError, "遗漏"):
                self.service.translate(segments(), settings(), "key", self.progress, self.cancelled, callback)
        self.assertEqual(generate.call_count, 2)
        callback.assert_not_called()

    def test_automatic_cloud_failure_falls_back_to_local(self):
        with patch.object(self.service, "_model_installed", return_value=True), \
             patch.object(self.service, "_generate_cloud", side_effect=RuntimeError("云端暂时不可用。")), \
             patch.object(self.service, "_generate_local", side_effect=translated_response):
            result, mode, warnings = self.service.translate(segments(), settings("auto"), "key", self.progress, self.cancelled, Mock())
        self.assertEqual(mode, "local")
        self.assertTrue(all(x["translation"] for x in result))
        self.assertIn("自动切换", warnings[0])

    def test_explicit_cloud_mode_does_not_silently_change_modes(self):
        with patch.object(self.service, "_generate_cloud", side_effect=RuntimeError("云端暂时不可用。")), \
             patch.object(self.service, "_generate_local") as local:
            with self.assertRaisesRegex(RuntimeError, "云端暂时不可用"):
                self.service.translate(segments(), settings("cloud"), "key", self.progress, self.cancelled, Mock())
        local.assert_not_called()

    def test_local_mode_never_calls_cloud_even_with_cloud_credentials(self):
        with patch.object(self.service, "_require_model", return_value=Path(self.temp.name)), \
             patch.object(self.service, "_generate_local", side_effect=translated_response), \
             patch.object(self.service, "_generate_cloud") as remote:
            result, mode, _ = self.service.translate(segments(), settings("local"), "secret", self.progress, self.cancelled, Mock())
        remote.assert_not_called()
        self.assertEqual(mode, "local")
        self.assertTrue(result[0]["translation"])

    def test_cloud_failure_without_offline_pack_explains_recovery(self):
        with patch.object(self.service, "_generate_cloud", side_effect=RuntimeError("云端暂时不可用。")):
            with self.assertRaisesRegex(RuntimeError, "离线语言包尚未就绪"):
                self.service.translate(segments(), settings("auto"), "key", self.progress, self.cancelled, Mock())

    def test_cancel_after_batch_preserves_completed_callback(self):
        cancelled = [False]
        updates = []
        def update(value):
            updates.append(value)
            cancelled[0] = True
        with patch.object(self.service, "_generate_cloud", side_effect=translated_response):
            with self.assertRaises(InterruptedError):
                self.service.translate(segments(4, long=True), settings(), "key", self.progress, lambda: cancelled[0], update)
        self.assertEqual(len(updates), 1)
        self.assertTrue(any(x["translation"] for x in updates[0]))
        self.assertTrue(any(not x["translation"] for x in updates[0]))

    def test_cancel_before_processing_does_not_call_model(self):
        with patch.object(self.service, "_generate_cloud") as remote:
            with self.assertRaises(InterruptedError):
                self.service.translate(segments(), settings(), "key", self.progress, lambda: True, Mock())
        remote.assert_not_called()

    def test_splitting_retains_every_source_character(self):
        source = ("Hello, world. 你好世界！ " * 300) + "last"
        pieces = _split_text(source)
        self.assertEqual("".join(pieces), source)
        self.assertTrue(all(len(x) <= 1000 for x in pieces))

    def test_chapter_time_comes_only_from_original_segment_ids(self):
        items = [{"id": "a", "start": 18, "end": 24}, {"id": "b", "start": 31, "end": 40}]
        value = {"overview": "视频说明了如何减少环境中的干扰。", "chapters": [{"start_id": "a", "end_id": "b", "start": -999,
                 "end": 999999, "title": "减少干扰", "summary": "关闭不必要的通知以减少分心。", "bullets": []}]}
        _, chapters = _validate_summary(value, items)
        self.assertEqual((chapters[0]["start"], chapters[0]["end"]), (18, 40))

    def test_summary_rejects_unknown_refs_and_omitted_source(self):
        items = [{"id": "a", "start": 0, "end": 2}, {"id": "b", "start": 3, "end": 4}]
        for start, end in (("x", "b"), ("a", "a"), ("b", "b")):
            with self.assertRaises(_InvalidOutput):
                _validate_summary({"overview": "中文概览", "chapters": [{"start_id": start, "end_id": end,
                                  "title": "标题", "summary": "摘要"}]}, items)

    def test_summary_uses_valid_original_times_and_chinese_overview(self):
        with patch.object(self.service, "_generate_cloud", side_effect=summary_response), \
             patch.object(self.service, "release_models"):
            overview, chapters, mode, warnings = self.service.summarize(segments(), settings(), "key", self.progress, self.cancelled)
        self.assertIn("专注", overview)
        self.assertEqual((chapters[0]["start"], chapters[-1]["end"]), (0, 28))
        self.assertEqual(chapters[0]["id"], 0)
        self.assertEqual(mode, "cloud")
        self.assertFalse(warnings)

    def test_placeholder_summary_is_rejected(self):
        items = [{"id": "a", "start": 0, "end": 5}]
        value = {"overview": "中文概览", "chapters": [{"start_id": "a", "end_id": "a", "title": "减少干扰", "summary": "关闭通知可以帮助集中注意力。"}]}
        with self.assertRaisesRegex(_InvalidOutput, "占位"):
            _validate_summary(value, items)

    def test_each_chapter_is_summarized_from_only_its_own_source(self):
        source = segments()
        for index, row in enumerate(source):
            row.update(start=index * 60, end=(index + 1) * 60)
        seen = []
        def generate(prompt, *_):
            if "只规划范围" in prompt:
                return '{"chapters":[{"start_id":"s0","end_id":"s0"},{"start_id":"s1","end_id":"s2"}]}'
            if "转写数据：" not in prompt:
                return '{"overview":"减少环境干扰并安排明确的工作时间。"}'
            group = json.loads(prompt.split("转写数据：", 1)[1])
            seen.append([item["id"] for item in group])
            return '{"overview":"减少不必要的信息干扰，让注意力回到当前任务。","title":"减少信息干扰","summary":"关闭无关通知并专注于当前任务。","bullets":[]}'
        with patch.object(self.service, "_generate_cloud", side_effect=generate), patch.object(self.service, "release_models"):
            _, chapters, _, _ = self.service.summarize(source, settings(), "key", self.progress, self.cancelled)
        self.assertEqual(seen, [["s0"], ["s1", "s2"]])
        self.assertEqual([(c["start"], c["end"]) for c in chapters], [(0, 60), (60, 180)])

    def test_incomplete_asr_sentences_merge_without_losing_time_or_text(self):
        rows = [{"id": 0, "start": 0, "end": 3, "text": "Should I check", "translation": ""},
                {"id": 1, "start": 3, "end": 6, "text": "my phone?", "translation": ""},
                {"id": 2, "start": 7, "end": 9, "text": "Keep working.", "translation": ""}]
        merged = _merge_fragments(rows)
        self.assertEqual([x["text"] for x in merged], ["Should I check my phone?", "Keep working."])
        self.assertEqual((merged[0]["start"], merged[0]["end"]), (0, 6))
        self.assertEqual(len(rows), 3)

    def test_long_overview_reduction_has_bounded_prompts(self):
        prompts = []
        def generate(prompt, *_):
            prompts.append(prompt)
            return '{"overview":"这是一段合并后的中文概览。"}'
        route = _Route("cloud", False, settings(), "key")
        with patch.object(self.service, "_generate_cloud", side_effect=generate):
            result = self.service._combine_overviews(["原始内容。" * 190 for _ in range(20)], route, self.cancelled)
        self.assertIn("中文概览", result)
        self.assertTrue(all(len(x) < 3500 for x in prompts))

    def test_endpoint_validation_rejects_embedded_secrets(self):
        for base in ("file:///tmp/x", "https://user:secret@host/v1", "https://host/v1?key=secret", "javascript:alert(1)"):
            with self.assertRaises(RuntimeError) as error:
                self.service._endpoint({"cloud": {"base_url": base, "model": "m"}})
            self.assertNotIn("secret", str(error.exception))
        self.assertEqual(self.service._endpoint(settings())[0], "https://example.test/v1/chat/completions")

    def test_cloud_http_error_never_exposes_key_or_response_body(self):
        opener = Mock()
        opener.open.side_effect = urllib.error.HTTPError("https://host/?key=TOPSECRET", 401, "TOPSECRET", {}, io.BytesIO(b"TOPSECRET"))
        with patch("urllib.request.build_opener", return_value=opener):
            with self.assertRaises(RuntimeError) as error:
                self.service._generate_cloud("plain transcript only", _Route("cloud", False, settings(), "TOPSECRET"), self.cancelled)
        self.assertNotIn("TOPSECRET", str(error.exception))
        self.assertIn("权限", str(error.exception))

    def test_json_rejects_nonfinite_values_and_code(self):
        self.assertEqual(_safe_json('```json\n{"a":1}\n```'), {"a": 1})
        for value in ('{"a":NaN}', '__import__("os").system("echo bad")', ''):
            with self.assertRaises(_InvalidOutput):
                _safe_json(value)

    def test_asr_skips_empty_invalid_segments_and_bounds_timestamps(self):
        audio_path = Path(self.temp.name) / "audio.wav"
        with wave.open(str(audio_path), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16000)
            audio.writeframes(b"\0\0" * 32000)
        class Array:
            def astype(self, _): return self
            def __truediv__(self, _): return self
        fake_np = types.SimpleNamespace(int16="int16", float32="float32", frombuffer=lambda *a, **k: Array())
        fake_whisper = types.SimpleNamespace(transcribe=Mock(return_value={"language": "en", "segments": [
            {"start": -1, "end": 1, "text": "  Hello. "},
            {"start": 1, "end": 9, "text": "World."},
            {"start": 0, "end": 0, "text": ""},
            {"start": float("nan"), "end": 2, "text": "Invalid."},
        ]}))
        with patch.dict("sys.modules", {"numpy": fake_np, "mlx_whisper": fake_whisper}), \
             patch.object(self.service, "_require_model", return_value=Path(self.temp.name)), \
             patch.object(self.service, "_clear_gpu_cache"):
            language, result = self.service.transcribe(audio_path, "auto", self.progress, self.cancelled)
        self.assertEqual(language, "en")
        self.assertEqual([x["text"] for x in result], ["Hello.", "World."])
        self.assertEqual((result[0]["start"], result[-1]["end"]), (0, 2))
        self.assertEqual(fake_whisper.transcribe.call_args.kwargs["path_or_hf_repo"], self.temp.name)


if __name__ == "__main__":
    unittest.main()
