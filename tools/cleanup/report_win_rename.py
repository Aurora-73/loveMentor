"""检查 .dsr 中重复组的文件路径是否仅差 Windows 自动重命名的 (1) 后缀。
适用于文件本体和目录路径中所有层级的 (1) 后缀。
加 --execute 执行删除，否则仅报告。
"""

import gzip
import os
import re
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict

RE_RENAME = re.compile(r'\s*\(\d+\)$')
RE_PAREN_NUM = re.compile(r'\s*\(\d+\)')


def count_paren(path):
    """统计路径中有多少层带 (1) 后缀的组件"""
    return sum(1 for p in path.split('\\') if RE_PAREN_NUM.search(p))


def strip_rename(s):
    return RE_RENAME.sub('', s)


def normalize_path(path):
    parts = path.replace('\\', '/').split('/')
    normalized = '/'.join(strip_rename(p) for p in parts)
    return normalized.lower()


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
            'elem': f_elem,
        })

    return groups, scan_root, root


def delete_file(path, use_trash):
    if not os.path.exists(path):
        return False
    try:
        if use_trash:
            import send2trash
            send2trash.send2trash(path)
        else:
            os.remove(path)
        return True
    except Exception as e:
        print(f"    → 删除失败: {e}")
        return False


def clean_empty_dirs(root_path):
    """自底向上清理空目录"""
    removed = 0
    for r, dirs, files in os.walk(root_path, topdown=False):
        for d in dirs:
            fp = os.path.join(r, d)
            try:
                if not os.listdir(fp):
                    os.rmdir(fp)
                    print(f"  [空目录] {os.path.relpath(fp, root_path)}")
                    removed += 1
            except OSError:
                pass
    return removed


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
    print(f"总重复组: {len(groups)}")
    print()

    # 筛选路径仅差 (1) 后缀的组
    rename_groups = []
    for sid, files in groups.items():
        if len(files) <= 1:
            continue
        for f in files:
            f['norm'] = normalize_path(f['path'])
            f['paren_count'] = count_paren(f['path'])
        if len(set(f['norm'] for f in files)) == 1:
            rename_groups.append((sid, files))

    rename_groups.sort(key=lambda x: -len(x[1]))

    total_dupes = sum(len(files) for _, files in rename_groups)
    total_keep = len(rename_groups)
    total_redundant = total_dupes - total_keep

    print(f"路径仅差 (1) 后缀的重复组: {len(rename_groups)} 组\n")

    if execute:
        deleted_count = 0
        for sid, files in rename_groups:
            # 选 (1) 层数最少的保留，同层时优先 fl=1（原始）
            files.sort(key=lambda f: (f['paren_count'], f['fl'] != '1', f['fl']))
            keep = files[0]
            delete_list = files[1:]

            print(f"── sid={sid} ({len(files)}个) ──")
            print(f"  [保] {keep['path']}")
            for f in delete_list:
                if delete_file(f['path'], use_trash):
                    print(f"  [删] {f['path']}")
                    deleted_count += 1
                    # 标记 XML 元素待移除
                    f['deleted'] = True
                else:
                    print(f"  [缺] {f['path']} (不存在)")
            print()

        # 清理空目录（只扫受影响的文件夹）
        affected_roots = set()
        for _, files in rename_groups:
            for f in files:
                if f.get('deleted'):
                    p = f['path']
                    # D:\baidu—download\... or E:\Code\...\百度网盘
                    parts = p.split('\\')
                    if p.startswith('D:') and len(parts) > 2:
                        affected_roots.add('\\'.join(parts[:3]))
                    elif p.startswith('E:') and len(parts) > 5 and '百度网盘' in parts:
                        idx = parts.index('百度网盘')
                        affected_roots.add('\\'.join(parts[:idx + 2]))

        for root_path in sorted(affected_roots):
            if os.path.isdir(root_path):
                n = clean_empty_dirs(root_path)
                if n:
                    print(f"  清理 {os.path.basename(root_path)} 下 {n} 个空目录")

        # 保存清理后 dsr
        files_parent = root.find('files')
        removed_elems = 0
        for _, files in rename_groups:
            for f in files:
                if f.get('deleted'):
                    files_parent.remove(f['elem'])
                    removed_elems += 1
        if removed_elems:
            cleaned_path = dsr_path.replace('.dsr', '_cleaned.dsr')
            with gzip.open(cleaned_path, 'wb') as f:
                f.write(b'<?xml version="1.0" encoding="utf-8"?>')
                f.write(ET.tostring(root, encoding='utf-8'))
            print(f"\n已保存清理后 dsr: {cleaned_path}")

        print(f"\n{'='*60}")
        print(f"已删除 {deleted_count} 个文件")

    else:
        for sid, files in rename_groups:
            files.sort(key=lambda f: (f['paren_count'], f['fl'] != '1', f['fl']))
            print(f"── sid={sid} ({len(files)} 个文件) ──")
            for i, f in enumerate(files):
                tag = " [保留]" if i == 0 else ""
                print(f"  {f['path']}{tag}")
            print()

        print(f"{'='*60}")
        print(f"共 {len(rename_groups)} 组，{total_dupes} 个文件")
        print(f"每组保留 1 个，可删除 {total_redundant} 个冗余文件")
        print(f"加 --execute 执行删除，加 --trash 删除到回收站")


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    main()
