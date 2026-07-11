"""
跨目录重复组去重：按目录优先级评分，每组只保留一个最优目录。

评分规则（低分优先保留）:
  - (1) 路径:         +200
  - 整理大集合/合集:   -100
  - 高价值/高端展示面: -50
  - 可复制展示面:     +80
  - 等多个文件:       +50
  - 路径深度:         +depth*2
  - E 盘:             -20

决胜规则（分数相同时）:
  1. 目录内文件更多者优先（ consolidate ）
  2. 目录名更短者优先
  3. 字典序优先

用法:
  python cross_dir_dedup.py <文件.dsr> [--execute]
"""
import os, sys, gzip, xml.etree.ElementTree as ET
from collections import defaultdict

def dir_score(d):
    s = 0
    if '(1)' in d: s += 200
    if '整理大集合' in d or '整理合集' in d: s -= 100
    if '高价值展示面' in d or '高端展示面全' in d: s -= 50
    if '可复制展示面' in d: s += 80
    if '等多个文件' in d: s += 50
    s += d.count(os.sep) * 2
    if d.startswith('E:'): s -= 20
    return s

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

    records = []
    for f in root.find('files').findall('f'):
        d_idx = int(f.get('d'), 16) - 1
        dir_path = resolve_dir(d_idx)
        name = f.get('n', '')
        sid = f.get('sid', '')
        records.append({
            'sid': sid, 'path': os.path.join(dir_path, name),
            'dir': dir_path, 'name': name,
        })
    return records

def main():
    if len(sys.argv) < 2:
        print('用法: python cross_dir_dedup.py <文件.dsr> [--execute]')
        sys.exit(1)

    dsr_path = sys.argv[1]
    execute = '--execute' in sys.argv

    records = load_dsr(dsr_path)

    # 按 sid 分组
    groups = defaultdict(list)
    for r in records:
        groups[r['sid']].append(r)

    multi = {s: rs for s, rs in groups.items() if len(rs) >= 2}

    # 只考虑磁盘上实际存在的文件
    for sid in list(multi.keys()):
        recs = [r for r in multi[sid] if os.path.isfile(r['path'])]
        if len(recs) < 2:
            del multi[sid]
        else:
            multi[sid] = recs

    # 按目录分组并评分
    grouped_by_dir = {}
    for sid, recs in multi.items():
        dirs = defaultdict(list)
        for r in recs:
            dirs[r['dir']].append(r)
        # 对每个目录计算评分
        scored = [(d, dir_score(d), len(files), files) for d, files in dirs.items()]
        # 排序：分低优先，同分文件多优先，同分同文件目录名短优先，字典序
        scored.sort(key=lambda x: (x[1], -x[2], len(x[0]), x[0]))
        grouped_by_dir[sid] = scored

    total_delete = 0
    for sid, scored in sorted(grouped_by_dir.items()):
        if len(scored) <= 1:
            continue
        best_dir, best_score, best_count, best_files = scored[0]
        rest = scored[1:]

        delete_paths = []
        for d, score, cnt, files in rest:
            for f in files:
                delete_paths.append(f)

        if not delete_paths:
            continue

        for f in delete_paths:
            total_delete += 1
            if execute:
                os.remove(f['path'])

        short = lambda d: d[-60:]
        print(f'sid={sid} ({len(scored)}目录, {sum(x[2] for x in scored)}文件):')
        print(f'  [保] score={best_score:4d}  ...{short(best_dir)}  ({best_count}文件)')
        for d, score, cnt, files in rest:
            status = '[删]'
            existing = sum(1 for f in files if os.path.isfile(f['path']))
            if existing == 0:
                status = '[缺]'
            print(f'  {status} score={score:4d}  ...{short(d)}  ({cnt}文件)')

    print(f'\n待删除: {total_delete} 个文件')
    if execute:
        print('已执行删除')
    else:
        print('预览模式，加 --execute 执行')

if __name__ == '__main__':
    main()
