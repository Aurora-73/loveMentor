"""
列出 docs/文档 下每个一级文件夹的二级子文件夹清单。
只递归一层，不会无限展开。
"""
import os

BASE = r"<project_root>\docs\文档"

for entry in sorted(os.listdir(BASE)):
    path = os.path.join(BASE, entry)
    if not os.path.isdir(path):
        continue
    print(f"■ {entry}")
    subs = sorted(
        d for d in os.listdir(path)
        if os.path.isdir(os.path.join(path, d))
    )
    for i, s in enumerate(subs):
        prefix = "  ├─ " if i < len(subs) - 1 else "  └─ "
        print(f"{prefix}{s}")
    print()
