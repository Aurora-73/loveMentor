"""
分析 .dsr 文件的重复情况和磁盘实际状态。

用法:
  python analyze_dsr.py <文件.dsr> [--summary] [--groups N]

选项:
  --summary       打印概况（重复组数、文件数、目录分布）
  --groups N      列出最大的 N 个重复组详情
  --remaining     列出仍存在磁盘上的重复组（已考虑之前删除的文件）
  --patterns      分析残留重复组的模式（跨目录 vs 同目录）
"""

import os, sys, gzip, xml.etree.ElementTree as ET
from collections import defaultdict, Counter

def load_dsr(path):
    with gzip.open(path, 'rb') as f:
        root = ET.fromstring(f.read())
    scan_root = root.get('s', '')
    dir_list = [d.get('n', '') for d in root.find('dirs').findall('d')]

    def resolve_dir(d_idx):
        p = dir_list[d_idx]
        if p.startswith('.\\') or p.startswith('./'):
            return os.path.normpath(os.path.join(scan_root, p))
        return p

    groups = defaultdict(list)
    for f in root.find('files').findall('f'):
        d_idx = int(f.get('d'), 16) - 1
        path = os.path.join(resolve_dir(d_idx), f.get('n', ''))
        groups[f.get('sid', '')].append(path)
    return groups, dir_list


def summary(groups):
    multi = {s: ps for s, ps in groups.items() if len(ps) >= 2}
    existing = 0
    for ps in groups.values():
        existing += sum(1 for p in ps if os.path.isfile(p))

    still_dup = 0
    still_dup_files = 0
    for sid, paths in multi.items():
        exist = [p for p in paths if os.path.isfile(p)]
        if len(exist) >= 2:
            still_dup += 1
            still_dup_files += len(exist) - 1

    print(f"总重复组 (>=2): {len(multi)}")
    print(f"总文件数 (dsr): {sum(len(ps) for ps in groups.values())}")
    print(f"磁盘实际文件数: {existing}")
    print(f"磁盘仍有重复的组: {still_dup}")
    print(f"磁盘仍可删除文件: {still_dup_files}")


def top_groups(groups, n=20):
    multi = [(s, ps) for s, ps in groups.items() if len(ps) >= 2]
    multi.sort(key=lambda x: -len(x[1]))
    print(f"\n最大 {n} 个重复组:")
    for sid, paths in multi[:n]:
        exist = sum(1 for p in paths if os.path.isfile(p))
        print(f"  sid={sid}  ({len(paths)}文件, {exist}在磁盘):")
        for p in paths[:5]:
            flag = "+" if os.path.isfile(p) else "-"
            short = "\\".join(p.split("\\")[-3:])
            print(f"    [{flag}] {short}")
        if len(paths) > 5:
            print(f"    ... 及其他 {len(paths)-5} 个")


def remaining(groups):
    """列出所有仍存在磁盘上的重复组"""
    multi = [(s, ps) for s, ps in groups.items() if len(ps) >= 2]
    multi.sort(key=lambda x: -len(x[1]))

    total = 0
    for sid, paths in multi:
        exist = [(i, p) for i, p in enumerate(paths) if os.path.isfile(p)]
        if len(exist) >= 2:
            total += len(exist) - 1
            print(f"\nsid={sid} ({len(exist)}文件在磁盘):")
            for i, p in exist:
                short = "\\".join(p.split("\\")[-3:])
                print(f"  {short}")
    print(f"\n总计仍可删除: {total} 个文件")


def patterns(groups):
    """分析残留重复的模式"""
    multi = [(s, ps) for s, ps in groups.items() if len(ps) >= 2]

    same_dir = 0       # 同目录同名
    cross_dir_same_name = 0  # 跨目录同名
    cross_dir_diff_name = 0  # 跨目录不同名
    total_groups = 0

    for sid, paths in multi:
        exist = [p for p in paths if os.path.isfile(p)]
        if len(exist) < 2:
            continue
        total_groups += 1

        dirs = set(os.path.dirname(p) for p in exist)
        names = set(os.path.basename(p) for p in exist)

        if len(dirs) == 1:
            same_dir += 1
        elif len(names) == 1:
            cross_dir_same_name += 1
        else:
            cross_dir_diff_name += 1

    print(f"\n残留重复模式分析 ({total_groups} 组):")
    print(f"  同目录重复: {same_dir} 组")
    print(f"  跨目录同名: {cross_dir_same_name} 组")
    print(f"  跨目录不同名: {cross_dir_diff_name} 组")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    path = sys.argv[1]
    groups, dir_list = load_dsr(path)

    if '--summary' in sys.argv or len(sys.argv) == 2:
        summary(groups)
    if '--groups' in sys.argv:
        idx = sys.argv.index('--groups')
        n = int(sys.argv[idx+1]) if idx+1 < len(sys.argv) else 20
        top_groups(groups, n)
    if '--remaining' in sys.argv:
        remaining(groups)
    if '--patterns' in sys.argv:
        patterns(groups)


if __name__ == '__main__':
    main()
