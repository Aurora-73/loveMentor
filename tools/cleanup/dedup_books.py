"""分析三个书籍目录的重复情况。

对比 泡妞231本 / 泡妞250本 / 泡妞356本 的文件名，
找出重复文件和各自独有的文件。
"""

import os
import sys
from collections import defaultdict

ROOT = os.path.join(os.path.dirname(__file__), "..", "docs", "百度网盘", "[REDACTED]")

COLLECTIONS = {
    "231本": os.path.join(ROOT, "泡妞231本"),
    "250本": os.path.join(ROOT, "泡妞250本"),
    "356本": os.path.join(ROOT, "泡妞356本"),
}

# 231本中已排除的目录（不参与对比）
EXCLUDED_DIRS_231 = {"D 红丸米格道", "E the rational male", "K X"}


def normalize_name(filename: str) -> str:
    """归一化文件名用于比较：去扩展名、去空格、去标点。"""
    name = os.path.splitext(filename)[0]
    # 去掉常见标点和空格
    for ch in " -_—（）()【】[]{}「」""''·.,，。！？!?…":
        name = name.replace(ch, "")
    return name.lower()


def collect_files(root: str, excluded_dirs: set[str] | None = None) -> dict[str, str]:
    """收集目录下所有文件，返回 {归一化文件名: 完整路径}。"""
    excluded_dirs = excluded_dirs or set()
    results = {}
    for dirpath, dirnames, filenames in os.walk(root):
        rel = os.path.relpath(dirpath, root)
        parts = rel.split(os.sep)
        if any(p in excluded_dirs for p in parts):
            continue
        dirnames[:] = [d for d in dirnames if d not in excluded_dirs]
        for name in filenames:
            ext = os.path.splitext(name)[1].lower()
            if ext not in (".pdf", ".epub", ".doc", ".docx", ".txt", ".html", ".htm"):
                continue
            if name in ("README.md", "update.sh"):
                continue
            key = normalize_name(name)
            results[key] = os.path.join(dirpath, name)
    return results


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    all_files: dict[str, dict[str, str]] = {}
    for label, path in COLLECTIONS.items():
        excl = EXCLUDED_DIRS_231 if label == "231本" else set()
        all_files[label] = collect_files(path, excl)

    # 统计每个归一化文件名出现在哪些集合中
    name_to_collections: dict[str, list[str]] = defaultdict(list)
    for label, files in all_files.items():
        for name in files:
            name_to_collections[name].append(label)

    # 分类输出
    only_in = {label: [] for label in COLLECTIONS}
    dup_250_356 = []
    dup_231_250 = []
    dup_231_356 = []
    in_all_three = []
    in_two = defaultdict(list)

    for name, labels in name_to_collections.items():
        if len(labels) == 1:
            only_in[labels[0]].append(name)
        elif len(labels) == 2:
            pair = "+".join(sorted(labels))
            in_two[pair].append(name)
        else:
            in_all_three.append(name)

    print("=" * 60)
    print("书籍去重分析报告")
    print("=" * 60)

    for label in COLLECTIONS:
        print(f"\n【{label}】总文件数: {len(all_files[label])}")
        print(f"  独有文件: {len(only_in[label])}")

    print(f"\n--- 重复文件统计 ---")
    print(f"三本都有: {len(in_all_three)} 个")
    for pair, names in sorted(in_two.items()):
        print(f"{pair} 都有: {len(names)} 个")

    # 输出 250本 和 356本 之间的重复（这些是要去重的重点）
    dup_250_356_names = in_two.get("250本+356本", []) + in_all_three
    print(f"\n--- 250本 vs 356本 重复 ---")
    print(f"250本和356本之间重复: {len(dup_250_356_names)} 个")
    print(f"250本独有: {len(only_in['250本'])} 个")
    print(f"356本独有: {len(only_in['356本'])} 个")

    # 输出 250本 和 356本 之间的重复文件名列表
    if dup_250_356_names:
        print(f"\n--- 250本∩356本 重复文件名 ---")
        for name in sorted(dup_250_356_names):
            # 找到原始文件名
            orig = None
            for label in ("250本", "356本"):
                if name in all_files[label]:
                    orig = os.path.basename(all_files[label][name])
                    break
            print(f"  {orig}")

    # 输出 231本 独有文件（这些是 231本 的价值所在）
    print(f"\n--- 231本独有文件（不在250/356中）---")
    for name in sorted(only_in["231本"]):
        orig = os.path.basename(all_files["231本"][name])
        print(f"  {orig}")


if __name__ == "__main__":
    main()
