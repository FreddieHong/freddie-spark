import unittest

from backend.exports import build_export, timestamp


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.project = {
            "title": "课程 / 第一集",
            "overview": "关于机器学习的介绍。",
            "segments": [{"id": 0, "start": 1.125, "end": 3.5, "text": "Hello, world.", "translation": "你好，世界。"}, {"id": 1, "start": 4, "end": 6, "text": "Welcome.", "translation": ""}],
            "chapters": [{"id": 0, "start": 1.125, "end": 6, "title": "介绍", "summary": "课程开场。", "bullets": ["问候观众"]}],
        }

    def test_srt_preserves_source_time_and_bilingual_text(self):
        data, mime, filename = build_export(self.project, "srt", "bilingual")
        result = data.decode()
        self.assertIn("1\n00:00:01,125 --> 00:00:03,500\nHello, world.\n你好，世界。", result)
        self.assertIn("2\n00:00:04,000 --> 00:00:06,000\nWelcome.", result)
        self.assertNotIn("/", filename)
        self.assertIn("subrip", mime)

    def test_chinese_export_contains_only_existing_translation(self):
        data, _, _ = build_export(self.project, "txt", "chinese")
        self.assertIn("你好，世界。", data.decode())
        self.assertNotIn("Welcome", data.decode())

    def test_summary_markdown_retains_chapter_source_times(self):
        data, _, _ = build_export(self.project, "md", "summary")
        self.assertIn("## 00:00:01–00:00:06  介绍", data.decode())
        self.assertIn("- 问候观众", data.decode())

    def test_summary_srt_and_empty_data_rejected(self):
        with self.assertRaises(ValueError):
            build_export(self.project, "srt", "summary")
        for content in ("original", "summary", "chinese", "bilingual"):
            with self.subTest(content=content), self.assertRaises(ValueError):
                build_export({}, "txt", content)

    def test_srt_rejects_reversed_times(self):
        self.project["segments"][0]["end"] = 0
        with self.assertRaises(ValueError):
            build_export(self.project, "srt", "original")

    def test_timestamp_handles_long_recordings(self):
        self.assertEqual(timestamp(3600.999, True), "01:00:00,999")
        self.assertEqual(timestamp(59.9996, True), "00:01:00,000")


if __name__ == "__main__":
    unittest.main()
