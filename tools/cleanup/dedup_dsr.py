"""解析 .dsr 文件并执行两级去重：

第一级（[REDACTED]优先）：
  对每个重复组，如果任一文件在[REDACTED]目录下，删除该组所有不在[REDACTED]的文件。
第二级（同目录留长名）：
  对第一级未处理的重复组，按父目录分组。同目录下文件名不同时，保留文件名最长的。

用法:
  python dedup_dsr.py <文件.dsr>                         # 预览
  python dedup_dsr.py <文件.dsr> --execute                # 执行
  python dedup_dsr.py <文件.dsr> --execute --trash        # 删除到回收站
"""

import gzip
import os
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict

KEEP_DIR = "[REDACTED]"


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

    groups = defaultdict(list)
    for f_elem in root.find('files'):
        d_idx = int(f_elem.get('d'), 16) - 1
        full_path = os.path.normpath(os.path.join(
            resolve_dir(d_idx, dirs, scan_root), f_elem.get('n')
        ))
        groups[f_elem.get('sid')].append({
            'path': full_path,
            'sid': f_elem.get('sid'),
            'fl': f_elem.get('fl', ''),
            'hash': f_elem.get('s'),
            'elem': f_elem,
        })

    return groups, scan_root, root


def in_keep_dir(filepath):
    """检查文件路径是否在[REDACTED]目录下"""
    parts = filepath.replace('\\', os.sep).split(os.sep)
    return KEEP_DIR in parts


def _delete_file(f, execute, use_trash):
    if not execute:
        return True
    if not os.path.exists(f['path']):
        print(f"        → 文件不存在，跳过")
        return False
    try:
        if use_trash:
            import send2trash
            send2trash.send2trash(f['path'])
        else:
            os.remove(f['path'])
        return True
    except Exception as e:
        print(f"        → 删除失败: {e}")
        return False


def pass1_qixi(groups, execute, use_trash):
    """第一级：[REDACTED] 优先，删除外部冗余"""
    deleted_files = set()
    groups_affected = 0
    file_count = 0

    for sid, files in sorted(groups.items(), key=lambda x: -len(x[1])):
        if len(files) <= 1:
            continue

        keep = [f for f in files if in_keep_dir(f['path'])]
        delete = [f for f in files if not in_keep_dir(f['path'])]
        if not keep:
            continue

        groups_affected += 1

        print(f"\n[第一级] sid={sid} ({len(files)}个, 保留{len(keep)}个在{KEEP_DIR}):")
        for f in keep:
            print(f"  [保] {f['path']}")
        for f in delete:
            print(f"  [删] {f['path']}")
            if _delete_file(f, execute, use_trash):
                deleted_files.add(f['elem'])
                file_count += 1

    return deleted_files, groups_affected, file_count


def pass2_samedir(groups, deleted_files, execute, use_trash):
    """第二级：同目录留最长文件名"""
    new_deleted = set()
    groups_affected = 0
    file_count = 0

    for sid, files in sorted(groups.items(), key=lambda x: -len(x[1])):
        if len(files) <= 1:
            continue

        # 跳过第一级处理过的组（有文件被删过）
        remaining = [f for f in files if f['elem'] not in deleted_files]
        if len(remaining) <= 1:
            continue

        # 按父目录分组
        dir_groups = defaultdict(list)
        for f in remaining:
            dir_groups[os.path.dirname(f['path'])].append(f)

        group_dirty = False
        for parent, dir_files in sorted(dir_groups.items()):
            if len(dir_files) <= 1:
                continue

            # 按文件名长度排序，最长保留
            dir_files.sort(key=lambda f: len(os.path.basename(f['path'])))
            keep = [dir_files[-1]]
            delete = dir_files[:-1]
            # 如果有多个文件最长且同名，只删明确短的
            # 如果有文件名长度相同但内容不同（同一 sid 说明内容相同），保留一个即可
            same_len = [f for f in delete
                        if len(os.path.basename(f['path'])) == len(os.path.basename(keep[0]['path']))]
            if same_len:
                # 长度一样时保留一个，其他丢弃
                keep = [keep[0]]
                delete = [f for f in dir_files if f is not keep[0]]

            if not delete:
                continue

            if not group_dirty:
                print(f"\n[第二级] sid={sid} ({len(remaining)}个文件):")
                group_dirty = True
                groups_affected += 1

            for f in delete:
                print(f"  [删] {f['path']}  (短于 {os.path.basename(keep[0]['path'])})")
                if _delete_file(f, execute, use_trash):
                    new_deleted.add(f['elem'])
                    file_count += 1

    return new_deleted, groups_affected, file_count


def save_cleaned(dsr_path, root, all_deleted):
    """保存清理后的 dsr 文件"""
    files_parent = root.find('files')
    for elem in all_deleted:
        files_parent.remove(elem)

    cleaned_path = dsr_path.replace('.dsr', '_cleaned.dsr')
    with gzip.open(cleaned_path, 'wb') as f:
        f.write(b'<?xml version="1.0" encoding="utf-8"?>')
        f.write(ET.tostring(root, encoding='utf-8'))
    print(f"已保存清理后 dsr: {cleaned_path}")


def main():
    if len(sys.argv) < 2:
        print(f"用法: python {os.path.basename(sys.argv[0])} <文件.dsr> [--execute] [--trash]")
        sys.exit(1)

    dsr_path = sys.argv[1]
    execute = '--execute' in sys.argv
    use_trash = '--trash' in sys.argv

    if not os.path.exists(dsr_path):
        print(f"文件不存在: {dsr_path}")
        sys.exit(1)

    groups, scan_root, root = parse_dsr(dsr_path)
    print(f"扫描根目录: {scan_root}")
    print(f"共 {len(groups)} 个重复组")

    d1, g1, c1 = pass1_qixi(groups, execute, use_trash)
    all_deleted = set(d1)

    d2, g2, c2 = pass2_samedir(groups, all_deleted, execute, use_trash)
    all_deleted |= d2

    print(f"\n{'='*60}")
    print(f"第一级 ([REDACTED]优先): 涉及 {g1} 组，{'删除' if execute else '待删'} {c1} 个文件")
    print(f"第二级 (同目录留长名): 涉及 {g2} 组，{'删除' if execute else '待删'} {c2} 个文件")
    if not execute:
        print(f"预览模式，未实际删除。加 --execute 执行，加 --trash 删除到回收站")
    elif all_deleted:
        save_cleaned(dsr_path, root, all_deleted)


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    main()
