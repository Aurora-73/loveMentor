"""解析 .dsr 文件，按文件夹分组，找出子文件完全重叠的重复文件夹（只汇报，不删除）。

用法: python dedup_dsr.py <文件.dsr> [--cleaned <清理后.dsr>]
"""

import gzip
import os
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict


def resolve_dir(d, dirs, scan_root):
    raw = dirs[d]
    if raw.startswith(".\\") or raw.startswith("./"):
        rel = raw[2:]
        return os.path.normpath(os.path.join(scan_root, rel))
    return os.path.normpath(raw)


def infer_scan_root(dirs):
    abs_dirs = [d for d in dirs if d.startswith("E:")]
    if not abs_dirs:
        return "E:\\Code\\loveMentor\\docs\\百度网盘"
    return os.path.commonpath(abs_dirs)


def parse_dsr(path):
    with gzip.open(path, 'rb') as f:
        root = ET.fromstring(f.read())

    dirs = [d.get('n') for d in root.find('dirs')]
    scan_root = infer_scan_root(dirs)

    # 每个文件: (目录全路径, 文件名, sid)
    files = []
    for f_elem in root.find('files'):
        d_idx = int(f_elem.get('d'), 16) - 1
        full_dir = os.path.normpath(os.path.join(
            resolve_dir(d_idx, dirs, scan_root), ''
        ))
        files.append({
            'dir': full_dir,
            'name': f_elem.get('n'),
            'sid': f_elem.get('sid'),
            'size': f_elem.get('s'),
        })

    return files, scan_root


def format_sig(sig):
    """把签名转成可读的摘要字符串"""
    items = []
    for name, sid in sig[:5]:
        items.append(f"{name}(sid={sid})")
    if len(sig) > 5:
        items.append(f"...共{len(sig)}个文件")
    return ", ".join(items)


def find_dup_folders(files, scan_root, cleaned_dsr=None):
    """按文件夹分组，用 (文件名, sid) 做签名检测重复文件夹"""

    # 构建 dir -> [(name, sid)] 映射
    dir_files = defaultdict(list)
    for f in files:
        dir_files[f['dir']].append((f['name'], f['sid'], f['size']))

    # 按签名分组: 签名 = 排序后的 (name, sid) 元组
    sig_groups = defaultdict(list)
    for dir_path, file_list in sorted(dir_files.items()):
        # 签名: 按 (文件名, sid) 排序后取 tuple，方便 hash
        sig = tuple(sorted((name, sid) for name, sid, _ in file_list))
        sig_groups[sig].append((dir_path, file_list))

    # 筛选出 2+ 目录的重复组
    dup_folders = [(dirs, files) for sig, (dirs, files) in
                    [(sig, zip(*group)) for sig, group in sig_groups.items()
                     if len(group) >= 2]]

    return dup_folders


def report(dup_folders, scan_root):
    """汇报重复文件夹"""
    print(f"扫描根目录: {scan_root}\n")

    if not dup_folders:
        print("未发现子文件完全重叠的重复文件夹。")
        return

    # 按文件数排序（文件多的组排前面）
    dup_folders.sort(key=lambda x: -len(x[0][0]))

    total_groups = len(dup_folders)
    total_dirs = sum(len(dirs) for dirs, _ in dup_folders)
    total_wasted = 0

    print(f"发现 {total_groups} 组重复文件夹（共 {total_dirs} 个目录）:\n")

    for i, (dirs, file_lists) in enumerate(dup_folders, 1):
        n_files = len(file_lists[0])

        print(f"── 重复文件夹 #{i} ({n_files} 个文件) ──")

        # 分析这些目录下文件是否有文件名差异
        # 检查同名文件比例
        file_names_by_dir = [set(name for name, _, _ in fl) for fl in file_lists]
        all_same_names = all(
            fn == file_names_by_dir[0] for fn in file_names_by_dir[1:]
        )

        dirs_sorted = sorted(dirs)
        for d in dirs_sorted:
            rel = os.path.relpath(d, scan_root) if scan_root in d else d
            print(f"    {rel}")

        if all_same_names:
            print(f"  文件名完全一致\n")
        else:
            # 找出文件名差异
            print(f"  文件名不完全一致（内容同但命名不同）\n")

    # 统计汇总
    total_dirs = sum(len(dirs) for dirs, _ in dup_folders)
    print(f"总计: {total_groups} 组重复文件夹, 涉及 {total_dirs} 个目录")
    for _, file_lists in dup_folders[:3]:
        print(f"  - 每组 ~{len(file_lists[0])} 个文件")
        break


def main():
    if len(sys.argv) < 2:
        print(f"用法: python {os.path.basename(sys.argv[0])} <文件.dsr>")
        sys.exit(1)

    dsr_path = sys.argv[1]
    if not os.path.exists(dsr_path):
        print(f"文件不存在: {dsr_path}")
        sys.exit(1)

    files, scan_root = parse_dsr(dsr_path)
    print(f"共 {len(files)} 个文件记录\n")

    dup_folders = find_dup_folders(files, scan_root)
    report(dup_folders, scan_root)


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    main()
