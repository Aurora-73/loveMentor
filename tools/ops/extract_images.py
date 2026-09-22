"""
将指定目录下的全部图片文件移动到 图片/ 目录，保留相对路径。

用法：python extract_images.py
"""

import io
import os
import shutil
import sys
import time
from pathlib import Path

# 修复 Windows 终端 GBK 编码问题
if sys.stdout.encoding and sys.stdout.encoding.upper() != "UTF-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# === 配置 ===
SOURCE_DIRS = [
    str(Path(__file__).resolve().parents[2] / "docs" / "文档"),
]
TARGET_ROOT = str(Path(__file__).resolve().parents[2] / "docs" / "图片")

# 覆盖已有文件？
OVERWRITE = False

# 尽可能覆盖全面的图片扩展名
IMAGE_EXTS = {
    # Web 常用
    ".jpg", ".jpeg", ".jpe", ".jif", ".jfif", ".jfi",
    ".png", ".gif", ".bmp", ".dib", ".webp",
    ".tiff", ".tif",
    ".svg", ".svgz",
    ".ico", ".cur",
    # Apple
    ".heic", ".heif", ".heics", ".heifs",
    # JPEG 2000
    ".jp2", ".j2k", ".jpx", ".jpm",
    # 下一代格式
    ".avif", ".avifs",
    # 相机 RAW
    ".raw", ".cr2", ".cr3", ".nef", ".nrw",
    ".arw", ".dng", ".orf", ".rw2", ".rwl",
    ".raf", ".srf", ".sr2", ".pef", ".x3f",
    ".3fr", ".fff", ".bay", ".iiq", ".eip",
    # Adobe / 设计软件
    ".psd", ".psb", ".ai", ".eps", ".indd",
    ".xcf", ".kra",
    # 其他
    ".wbmp", ".hdr", ".exr", ".pcx", ".tga",
    ".pbm", ".pgm", ".ppm", ".pnm", ".pfm",
    ".wmf", ".emf",
}


def ensure_dir(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)


def collect_images():
    """收集所有图片文件。"""
    files = []
    for sd in SOURCE_DIRS:
        sd_path = Path(sd)
        if not sd_path.is_dir():
            print(f"[跳过] 目录不存在: {sd}")
            continue
        for fpath in sd_path.rglob("*"):
            if not fpath.is_file():
                continue
            ext = fpath.suffix.lower()
            if ext in IMAGE_EXTS:
                files.append(fpath)
    return files


def relative_path(fpath: Path) -> Path:
    """返回相对于所在 SOURCE_DIR 的路径。"""
    for sd in SOURCE_DIRS:
        sd_path = Path(sd)
        try:
            return fpath.relative_to(sd_path)
        except ValueError:
            continue
    raise ValueError(f"文件不在任何源目录中: {fpath}")


def move_file(src: Path):
    rel = relative_path(src)
    dst = Path(TARGET_ROOT) / rel
    if dst.exists() and not OVERWRITE:
        print(f"  [跳过] {rel} (已存在)")
        return
    ensure_dir(dst)
    shutil.move(str(src), str(dst))
    print(f"  [移动] {rel}")


def main():
    t0 = time.time()

    files = collect_images()
    print(f"找到 {len(files)} 个图片文件")

    if not files:
        return

    print(f"\n=== 移动图片 ({len(files)} 个) ===")
    for i, f in enumerate(files, 1):
        print(f"[{i}/{len(files)}]", end=" ")
        move_file(f)

    elapsed = time.time() - t0
    print(f"\n完成！耗时 {elapsed:.0f} 秒")


if __name__ == "__main__":
    main()
