#!/usr/bin/env python3
"""一键递归删除指定目录下的所有空文件夹"""

import argparse
import os
from pathlib import Path


def delete_empty_dirs(root: Path, dry_run: bool = False) -> int:
    """递归删除 root 下的所有空文件夹，返回删除数量。"""
    count = 0
    # 自底向上遍历，确保子空目录先删，父目录才能变空
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        p = Path(dirpath)
        try:
            # 如果目录为空（没有子目录也没有文件）
            if not any(p.iterdir()):
                if dry_run:
                    print(f"[DRY RUN] 将删除: {p}")
                else:
                    p.rmdir()
                    print(f"已删除: {p}")
                count += 1
        except (PermissionError, OSError) as e:
            print(f"跳过: {p} ({e})")
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description="递归删除空文件夹")
    parser.add_argument("root", nargs="?", default=".",
                        help="目标目录（默认当前目录）")
    parser.add_argument("--dry-run", "-n", action="store_true",
                        help="只列出将删除的目录，不实际删除")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.exists() or not root.is_dir():
        print(f"错误: 目录不存在或不是文件夹: {root}")
        return 1

    print(f"{'[DRY RUN] ' if args.dry_run else ''}扫描: {root}")
    count = delete_empty_dirs(root, dry_run=args.dry_run)

    if count == 0:
        print("没有空文件夹。")
    else:
        print(f"{'[DRY RUN] ' if args.dry_run else ''}共处理 {count} 个空文件夹。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
