#!/usr/bin/env python3
"""Explicitly prepare the offline model packs for the desktop application."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.engines import EngineService


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path.home() / "Library/Application Support/Freddie Lingua")
    parser.add_argument("--models", nargs="+", choices=["asr", "llm"], default=["asr", "llm"])
    args = parser.parse_args()
    engine = EngineService(args.data_dir)
    for model in args.models:
        last = [-1]
        def progress(value, message):
            percentage = int(value * 100)
            if percentage // 5 != last[0] or percentage == 100:
                last[0] = percentage // 5
                print(f"{model}: {percentage}% {message}", flush=True)
        print(f"开始准备 {model} 离线包…", flush=True)
        engine.download_model(model, progress)
    for item in engine.models_status():
        print(f"{item['name']}: {'已就绪' if item['installed'] else '未安装'}", flush=True)


if __name__ == "__main__":
    main()
