"""
删除 <project_root>\docs\百度网盘 下所有空文件夹，
从内到外多轮清理，直到没有空文件夹为止。

用法：python rmdir_empty.py
"""

import os
from pathlib import Path

ROOT = Path(r"<project_root>\docs\百度网盘")


def remove_empty_dirs(root: Path) -> int:
    """从内到外删除空文件夹，返回本轮删除数。"""
    deleted = 0
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        p = Path(dirpath)
        if p == root:
            continue
        try:
            if not list(p.iterdir()):
                p.rmdir()
                print(f"  [删除] {p.relative_to(root)}")
                deleted += 1
        except (OSError, PermissionError, FileNotFoundError):
            pass
    return deleted


def main():
    total = 0
    while True:
        deleted = remove_empty_dirs(ROOT)
        total += deleted
        if deleted == 0:
            break
        print(f"  --- 本轮删除 {deleted} 个 ---")

    if total:
        print(f"\n共删除 {total} 个空文件夹")
    else:
        print("没有空文件夹需要删除")


if __name__ == "__main__":
    main()
