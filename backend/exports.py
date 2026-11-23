"""Exports built exclusively from a project's existing results."""
from __future__ import annotations

import math
import re


def timestamp(seconds, srt=False):
    seconds = float(seconds)
    if not math.isfinite(seconds):
        raise ValueError("字幕时间无效")
    milliseconds = max(0, round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole, fraction = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{whole:02},{fraction:03}" if srt else f"{hours:02}:{minutes:02}:{whole:02}"


def build_export(project: dict, format: str, content: str) -> tuple[bytes, str, str]:
    if format not in ("md", "txt", "srt") or content not in ("summary", "bilingual", "chinese", "original"):
        raise ValueError("不支持的导出格式或内容")
    if format == "srt" and content == "summary":
        raise ValueError("总结无法导出为 SRT，请选择 Markdown 或 TXT")
    title = str(project.get("title") or "Freddie Spark")
    segments = project.get("segments") or []
    lines = []
    if content == "summary":
        overview = str(project.get("overview") or "").strip()
        chapters = project.get("chapters") or []
        if not overview and not chapters:
            raise ValueError("尚无可导出的总结")
        lines = [f"# {title}" if format == "md" else title, ""]
        if overview:
            lines += [overview, ""]
        for chapter in chapters:
            heading = f"{timestamp(chapter.get('start', 0))}–{timestamp(chapter.get('end', 0))}  {chapter.get('title', '')}"
            lines += [("## " if format == "md" else "") + heading, "", str(chapter.get("summary") or "").strip()]
            lines += [f"- {bullet}" for bullet in chapter.get("bullets", []) if str(bullet).strip()]
            lines += [""]
    else:
        if not segments or not any(str(segment.get("text") or "").strip() for segment in segments):
            raise ValueError("尚无可导出的识别结果")
        if content in ("bilingual", "chinese") and not any(str(segment.get("translation") or "").strip() for segment in segments):
            raise ValueError("尚无可导出的中文翻译")
        if format != "srt":
            lines = [("# " if format == "md" else "") + title, ""]
        count = 0
        for segment in segments:
            original = str(segment.get("text") or "").strip()
            translated = str(segment.get("translation") or "").strip()
            text = original if content == "original" else translated if content == "chinese" else "\n".join(part for part in (original, translated) if part)
            if not text:
                continue
            start, end = segment.get("start", 0), segment.get("end", 0)
            if format == "srt":
                if float(end) <= float(start):
                    raise ValueError("字幕片段时间无效，请重新识别后导出")
                count += 1
                lines += [str(count), f"{timestamp(start, True)} --> {timestamp(end, True)}", text.replace("\r", ""), ""]
            else:
                heading = f"[{timestamp(start)}–{timestamp(end)}]"
                lines += [("### " if format == "md" else "") + heading, text, ""]
    safe_title = re.sub(r'[\x00-\x1f/\\:*?"<>|]', "_", title).strip(" .")[:100] or "Freddie-Spark"
    mime = {"md": "text/markdown; charset=utf-8", "txt": "text/plain; charset=utf-8", "srt": "application/x-subrip; charset=utf-8"}[format]
    return ("\n".join(lines).rstrip() + "\n").encode("utf-8"), mime, f"{safe_title}-{content}.{format}"
