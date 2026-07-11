"""
将 .dsr (gzip XML) 转为易读易分析的 JSON。

用法:
  python dsr2json.py new_cleaned.dsr                         # 输出到 stdout
  python dsr2json.py new_cleaned.dsr -o data.json            # 保存到文件
  python dsr2json.py new_cleaned.dsr -o data.json --compact  # 压缩（省空间）
"""

import gzip, json, os, re, sys, xml.etree.ElementTree as ET
from collections import defaultdict

RE_RENAME = re.compile(r'\s*\(\d+\)')


def resolve_dir(d, dirs, scan_root):
    raw = dirs[d]
    if raw.startswith(".\\") or raw.startswith("./"):
        return os.path.normpath(os.path.join(scan_root, raw[2:]))
    return os.path.normpath(raw)


def infer_scan_root(dirs):
    abs_dirs = [d for d in dirs if d.startswith("E:")]
    return os.path.commonpath(abs_dirs) if abs_dirs else ""


def main():
    if len(sys.argv) < 2:
        print(f"用法: python {__file__} <文件.dsr> [-o 输出.json] [--compact]")
        sys.exit(1)

    dsr_path = sys.argv[1]
    out_path = None
    compact = False
    if '-o' in sys.argv:
        idx = sys.argv.index('-o')
        if idx + 1 < len(sys.argv):
            out_path = sys.argv[idx + 1]
    if '--compact' in sys.argv:
        compact = True

    # ── 解析 ──
    with gzip.open(dsr_path, 'rb') as f:
        root = ET.fromstring(f.read())

    dirs = [d.get('n') for d in root.find('dirs')]
    scan_root = infer_scan_root(dirs)

    # 构建输出
    out = {
        "source": os.path.basename(dsr_path),
        "scan_root": scan_root,
        "total_files": 0,
        "total_groups": 0,
        "groups": [],
        "files": [],
    }

    # 按 sid 分组
    sid_groups = defaultdict(list)
    for f_elem in root.find('files'):
        d_idx = int(f_elem.get('d'), 16) - 1
        full_path = os.path.normpath(os.path.join(
            resolve_dir(d_idx, dirs, scan_root), f_elem.get('n')
        ))
        sid_groups[f_elem.get('sid')].append({
            "path": full_path,
            "name": f_elem.get('n'),
            "fl": f_elem.get('fl', ''),
        })

    out["total_groups"] = len(sid_groups)

    # 构建 groups 和 files
    all_files = []
    groups_output = []

    for sid, files in sorted(sid_groups.items(), key=lambda x: -len(x[1])):
        # 统计 (1) 后缀
        paren_counts = [sum(1 for p in f["path"].split("\\") if RE_RENAME.search(p)) for f in files]
        has_rename = any(p > 0 for p in paren_counts)

        group = {
            "sid": sid,
            "count": len(files),
            "has_rename": has_rename,
            "files": [f["path"] for f in files],
            "fl": [f["fl"] for f in files],
        }
        groups_output.append(group)

        for f in files:
            all_files.append({
                "sid": sid,
                "path": f["path"],
                "fl": f["fl"],
            })

    out["groups"] = groups_output
    out["files"] = all_files
    out["total_files"] = len(all_files)

    # 额外索引：按目录分组
    out["dirs"] = {}
    for f in all_files:
        d = os.path.dirname(f["path"])
        if d not in out["dirs"]:
            out["dirs"][d] = {"files": [], "count": 0}
        out["dirs"][d]["files"].append(f["path"])
        out["dirs"][d]["count"] += 1

    # ── 输出 ──
    json_str = json.dumps(out, ensure_ascii=False, indent=None if compact else 2)

    if out_path:
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(json_str)
        print(f"已保存: {out_path}  ({os.path.getsize(out_path)/1024:.0f} KB)")
    else:
        print(json_str)


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    main()
