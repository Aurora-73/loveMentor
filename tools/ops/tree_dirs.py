"""Tree 展示 <project_root>\docs\聊天记录 的目录结构（仅文件夹）。"""

import sys
from pathlib import Path

ROOT = Path(r"<project_root>\docs\聊天记录")


def show_tree(path: Path, prefix: str = "", is_last: bool = True):
    connector = "└── " if is_last else "├── "
    print(f"{prefix}{connector}{path.name}")

    children = sorted(
        [p for p in path.iterdir() if p.is_dir()],
        key=lambda p: p.name,
    )
    sub_prefix = prefix + ("    " if is_last else "│   ")
    for i, child in enumerate(children):
        show_tree(child, sub_prefix, i == len(children) - 1)


def main():
    root = ROOT
    if not root.is_dir():
        print(f"目录不存在: {root}", file=sys.stderr)
        return

    print(root.name)
    children = sorted(
        [p for p in root.iterdir() if p.is_dir()],
        key=lambda p: p.name,
    )
    for i, child in enumerate(children):
        show_tree(child, is_last=(i == len(children) - 1))


if __name__ == "__main__":
    main()
