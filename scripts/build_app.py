#!/usr/bin/env python3
"""Build a local, self-contained Apple Silicon .app without a Node dependency."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(list(map(str, args)), cwd=ROOT, check=check, capture_output=True, text=True)


def dependencies(binary: Path) -> list[str]:
    return [line.strip().split(" (", 1)[0] for line in run("otool", "-L", str(binary)).stdout.splitlines()[1:] if line.strip().startswith("/opt/homebrew/") or line.strip().startswith("/usr/local/")]


def bundle_ffmpeg(resources: Path) -> None:
    binaries, libraries = resources / "bin", resources / "lib"
    binaries.mkdir(parents=True, exist_ok=True)
    libraries.mkdir(parents=True, exist_ok=True)
    copies: dict[Path, Path] = {}
    queue: list[tuple[Path, Path]] = []
    for name in ("ffmpeg", "ffprobe"):
        source = shutil.which(name)
        if not source:
            raise RuntimeError(f"缺少 {name}。请先安装 FFmpeg，再重新构建。")
        original = Path(source).resolve()
        target = binaries / name
        shutil.copy2(original, target)
        queue.append((original, target))
    index = 0
    while index < len(queue):
        source, target = queue[index]
        index += 1
        for dependency in dependencies(source):
            original = Path(dependency).resolve()
            if original not in copies:
                destination = libraries / original.name
                if destination.exists() and any(p != original and v == destination for p, v in copies.items()):
                    raise RuntimeError(f"动态库重名：{original.name}")
                shutil.copy2(original, destination)
                copies[original] = destination
                queue.append((original, destination))
    for source, target in queue:
        run("codesign", "--remove-signature", target, check=False)
        replacements: list[str] = []
        for dependency in dependencies(source):
            destination = copies[Path(dependency).resolve()]
            relative = os.path.relpath(destination, target.parent)
            replacements.extend(["-change", dependency, "@loader_path/" + relative])
        if target.parent == libraries:
            replacements.extend(["-id", "@rpath/" + target.name])
        if replacements:
            run("install_name_tool", *replacements, target)
        run("codesign", "--force", "--sign", "-", target)
    run(binaries / "ffmpeg", "-version")
    run(binaries / "ffprobe", "-version")
    print(f"已打包 FFmpeg 和 {len(copies)} 个动态库。", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "dist" / "Freddie Lingua.app")
    parser.add_argument("--reuse-runtime", action="store_true", help="重建代码时复用 app 已有运行时")
    args = parser.parse_args()
    runtime = args.runtime
    if runtime is None:
        candidates = sorted((ROOT / ".runtime").glob("cpython-3.12*-macos-aarch64-none"))
        if not candidates:
            raise RuntimeError("尚未准备项目运行时，请先按 README 安装 Python 和依赖。")
        runtime = candidates[-1]
    runtime = runtime.resolve()
    if not (runtime / "bin/python3.12").exists():
        raise RuntimeError("运行时中找不到 Python 3.12。")
    app = args.output.resolve()
    contents = app / "Contents"
    resources = contents / "Resources"
    (contents / "MacOS").mkdir(parents=True, exist_ok=True)
    (resources / "app").mkdir(parents=True, exist_ok=True)
    (ROOT / "build/swift-cache").mkdir(parents=True, exist_ok=True)
    print("正在构建原生窗口…", flush=True)
    run("swiftc", "-swift-version", "5", "-target", "arm64-apple-macosx14.0", "-module-cache-path", ROOT / "build/swift-cache", "-O", "-framework", "AppKit", "-framework", "WebKit", "-framework", "UniformTypeIdentifiers", ROOT / "native/FreddieLingua.swift", "-o", contents / "MacOS/FreddieLingua")
    shutil.copy2(ROOT / "native/Info.plist", contents / "Info.plist")
    for folder in ("backend", "frontend"):
        shutil.copytree(ROOT / folder, resources / "app" / folder, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in ("requirements.txt", "README.md", "THIRD_PARTY_NOTICES.md"):
        if (ROOT / name).exists():
            shutil.copy2(ROOT / name, resources / "app" / name)
    if not args.reuse_runtime or not (resources / "runtime/bin/python3.12").exists():
        print("正在打包独立 Python 与本地 AI 依赖…", flush=True)
        shutil.copytree(runtime, resources / "runtime", dirs_exist_ok=True, symlinks=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "pip", "pip-*.dist-info", "setuptools", "setuptools-*.dist-info"))
    if not args.reuse_runtime or not (resources / "bin/ffmpeg").exists():
        bundle_ffmpeg(resources)
    print("正在生成应用图标…", flush=True)
    iconset = ROOT / "build/AppIcon-v1.iconset"
    run("swiftc", "-swift-version", "5", "-module-cache-path", ROOT / "build/swift-cache", "-framework", "AppKit", ROOT / "native/MakeIcon.swift", "-o", ROOT / "build/MakeIcon")
    run(ROOT / "build/MakeIcon", iconset)
    # ICNS supports PNG payloads directly. Build the container deterministically
    # rather than depending on iconutil's WindowServer-dependent conversion.
    chunks = []
    for name, kind in (("icon_16x16.png", b"icp4"), ("icon_32x32.png", b"icp5"),
                       ("icon_32x32@2x.png", b"icp6"), ("icon_128x128.png", b"ic07"),
                       ("icon_256x256.png", b"ic08"), ("icon_512x512.png", b"ic09"),
                       ("icon_512x512@2x.png", b"ic10")):
        png = (iconset / name).read_bytes()
        chunks.append(kind + struct.pack(">I", len(png) + 8) + png)
    payload = b"".join(chunks)
    (resources / "AppIcon.icns").write_bytes(b"icns" + struct.pack(">I", len(payload) + 8) + payload)
    print("正在签名并检查应用…", flush=True)
    run("codesign", "--force", "--deep", "--sign", "-", app)
    run("codesign", "--verify", "--deep", "--strict", app)
    print(f"构建完成：{app}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        print(exc.stderr or exc.stdout or str(exc), file=sys.stderr)
        raise SystemExit(exc.returncode)
    except Exception as exc:
        print(f"构建失败：{exc}", file=sys.stderr)
        raise SystemExit(1)
