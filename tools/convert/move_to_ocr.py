r"""将 docs\文档 中指定类型的文件移动到 docs\文档_ocr 并保持文件夹结构。

0 字节文件直接删除，不移动。

用法:
    python tools/convert/move_to_ocr.py [--exclude <名1> <名2> ...] [--workers N]

示例:
    python tools/convert/move_to_ocr.py --workers 4
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_BASE = str(PROJECT_ROOT / "docs" / "文档")
TARGET_BASE = str(PROJECT_ROOT / "docs" / "文档_ocr")

EXTENSIONS = {".pdf", ".doc", ".docx", ".epub", ".txt", ".html", ".htm", ".ppt", ".pptx"}


def collect_files(root: str, excludes: set[str]) -> list[str]:
    results: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root)
        parts = rel_dir.split(os.sep)
        if any(p in excludes for p in parts):
            continue
        dirnames[:] = [d for d in dirnames if d not in excludes]
        for name in filenames:
            ext = os.path.splitext(name)[1].lower()
            if ext in EXTENSIONS:
                results.append(os.path.join(dirpath, name))
    return sorted(results)


def _move_one(filepath: str) -> dict:
    """移动单个文件到目标目录，保持相对路径。"""
    try:
        if os.path.getsize(filepath) == 0:
            os.remove(filepath)
            return {"status": "zero", "filepath": filepath}

        rel = os.path.relpath(filepath, SOURCE_BASE)
        dst = os.path.join(TARGET_BASE, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.move(filepath, dst)
        return {"status": "ok", "filepath": filepath}
    except Exception as e:
        return {"status": "error", "filepath": filepath, "detail": str(e)}


def _print_result(result: dict, index: int, total: int, start_time: float = 0):
    filepath = result["filepath"]
    name = os.path.basename(filepath)
    status = result["status"]

    elapsed = time.time() - start_time if start_time else 0
    if index > 0 and elapsed > 0 and total > 1:
        eta = elapsed / index * (total - index)
        time_str = f"  [{int(elapsed//60)}m{int(elapsed%60)}s<{int(eta//60)}m{int(eta%60)}s]"
    else:
        time_str = ""

    prefix = f"[{index}/{total}] {name}{time_str} ... "

    if status == "ok":
        print(f"{prefix}已移动")
    elif status == "zero":
        print(f"{prefix}0字节 (已删除)")
    elif status == "error":
        print(f"{prefix}ERROR: {result['detail']}")


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="移动指定文件到 文档_ocr 并保持文件夹结构")
    parser.add_argument("--exclude", nargs="*", default=[], help="要排除的目录名")
    parser.add_argument("--workers", type=int, default=min(8, os.cpu_count() or 1),
                        help=f"并发数（默认 CPU 核数: {min(8, os.cpu_count() or 1)}）")
    args = parser.parse_args()

    excludes = set(args.exclude)
    os.makedirs(TARGET_BASE, exist_ok=True)

    print(f"扫描: {SOURCE_BASE}")
    print(f"目标: {TARGET_BASE}")
    if excludes:
        print(f"排除目录: {', '.join(excludes)}")
    files = collect_files(SOURCE_BASE, excludes)

    if not files:
        print("没有找到需要处理的文件")
        sys.exit(0)

    files.sort(key=lambda f: os.path.getsize(f))
    print(f"找到 {len(files)} 个文件（并发数 {args.workers}）\n")

    results: list[dict] = []
    start_time = time.time()

    if args.workers <= 1:
        for i, fp in enumerate(files, 1):
            result = _move_one(fp)
            _print_result(result, i, len(files), start_time)
            results.append(result)
    else:
        executor = ThreadPoolExecutor(max_workers=args.workers)
        fut_map = {executor.submit(_move_one, fp): fp for fp in files}
        done = 0
        for future in as_completed(fut_map):
            done += 1
            result = future.result()
            _print_result(result, done, len(files), start_time)
            results.append(result)
        executor.shutdown(wait=True)
        order = {fp: i for i, fp in enumerate(files)}
        results.sort(key=lambda r: order.get(r["filepath"], 0))

    ok = sum(1 for r in results if r["status"] == "ok")
    zero = sum(1 for r in results if r["status"] == "zero")
    fail = sum(1 for r in results if r["status"] == "error")

    print(f"\n完成: {ok} 已移动, {zero} 个0字节(已删除), {fail} 失败, 共 {len(files)} 个")


if __name__ == "__main__":
    main()
