"""
文件夹结构备份与恢复工具

功能：
  - export: 扫描指定文件夹下的所有子文件夹（递归），将相对路径列表导出为 JSON
  - restore: 根据 JSON 文件，在目标文件夹下重建所有子文件夹

用法示例：
  # 导出 D:\\Data 下所有子文件夹结构到 structure.json
  python folder_structure_backup.py export D:\\Data structure.json

  # 根据 structure.json 在 E:\\Restore 下重建子文件夹结构
  python folder_structure_backup.py restore structure.json E:\\Restore

注意：仅处理文件夹，忽略文件。
"""

import argparse
import json
import os
import sys


def collect_subfolders(root: str):
    """递归收集 root 下所有子文件夹的相对路径（POSIX 风格，便于跨平台）。"""
    root = os.path.abspath(root)
    if not os.path.isdir(root):
        raise NotADirectoryError(f"源路径不是文件夹或不存在: {root}")

    subfolders = []
    for dirpath, dirnames, _ in os.walk(root):
        # 跳过根目录本身
        if os.path.abspath(dirpath) == root:
            continue
        rel = os.path.relpath(dirpath, root)
        # 统一为正斜杠，便于跨平台恢复
        subfolders.append(rel.replace(os.sep, "/"))

    subfolders.sort()
    return subfolders


def export_structure(src_folder: str, json_path: str) -> None:
    subfolders = collect_subfolders(src_folder)
    src_abs = os.path.abspath(src_folder)
    data = {
        "source": src_abs,
        "count": len(subfolders),
        "folders": subfolders,
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"已导出 {len(subfolders)} 个子文件夹结构 -> {json_path}")
    print(f"源文件夹: {src_abs}")


def restore_structure(json_path: str, dest_folder: str) -> None:
    if not os.path.isfile(json_path):
        raise FileNotFoundError(f"JSON 文件不存在: {json_path}")

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    folders = data.get("folders", [])
    if not isinstance(folders, list):
        raise ValueError("JSON 中 folders 字段不是列表")

    dest_abs = os.path.abspath(dest_folder)
    os.makedirs(dest_abs, exist_ok=True)

    created = 0
    skipped = 0
    for rel in folders:
        # 防御性过滤：拒绝绝对路径或包含 .. 的相对路径，防止越界
        if os.path.isabs(rel) or ".." in rel.split("/"):
            print(f"[跳过] 不安全的路径: {rel}")
            skipped += 1
            continue

        target = os.path.join(dest_abs, rel.replace("/", os.sep))
        if os.path.isdir(target):
            skipped += 1
            continue
        os.makedirs(target, exist_ok=True)
        created += 1

    print(f"目标文件夹: {dest_abs}")
    print(f"已创建 {created} 个子文件夹, 跳过 {skipped} 个(已存在或不安全)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="导出/恢复文件夹的子文件夹结构(忽略文件)"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_export = sub.add_parser("export", help="导出子文件夹结构到 JSON")
    p_export.add_argument("src", help="要扫描的源文件夹")
    p_export.add_argument("json", help="输出的 JSON 文件路径")

    p_restore = sub.add_parser("restore", help="从 JSON 重建子文件夹")
    p_restore.add_argument("json", help="JSON 文件路径")
    p_restore.add_argument("dest", help="目标文件夹(将在此处重建子文件夹)")

    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "export":
            export_structure(args.src, args.json)
        elif args.command == "restore":
            restore_structure(args.json, args.dest)
    except (NotADirectoryError, FileNotFoundError, ValueError) as e:
        print(f"错误: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
