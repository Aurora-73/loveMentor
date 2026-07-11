"""
文件去重数据库：将 .dsr 解析为易分析的多层索引结构。

  filedb = FileDB.from_dsr("new.dsr")
  filedb.summary()
  filedb.dup_folders()       # 完全重叠的目录
  filedb.rename_dupes()      # 路径仅差 (1) 后缀的重复
  filedb.by_sid["1E2"]       # 查某个重复组
  filedb.by_dir["E:\\foo"]   # 查某个目录下的文件

数据结构:
  .files  — 按 (目录, 文件名) 排序的列表，同目录文件连续排列
  .by_sid — sid → list[FileRec]  索引
  .by_dir — dir  → list[FileRec]  索引
  .sid_index — sid → list[int]  指向 files 中的位置
"""

import gzip
import os
import re
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass, field


# ── 核心数据类 ──────────────────────────────────────────────

@dataclass
class FileRec:
    """单个文件记录"""
    path: str          # 完整绝对路径
    dir: str           # 父目录
    name: str          # 文件名
    sid: str           # 内容分组 ID (hex)
    fl: str  = ''      # 文件角色 (1=原始, C=副本, 8=[REDACTED] 等)

    @property
    def ext(self):
        _, ext = os.path.splitext(self.name)
        return ext.lower()

    @property
    def paren_count(self):
        """路径中 (1) 后缀的层数"""
        return sum(1 for p in self.path.split('\\') if re.search(r'\s*\(\d+\)', p))

    @property
    def name_len(self):
        return len(self.name)


# ── 正则 ────────────────────────────────────────────────────

RE_RENAME = re.compile(r'\s*\(\d+\)$')
RE_PAREN = re.compile(r'\s*\(\d+\)')


def strip_rename(s):
    return RE_RENAME.sub('', s)


def normalize_path(path):
    """去掉所有路径组件中的 (1) 后缀（大小写不敏感）"""
    return '/'.join(strip_rename(p) for p in path.replace('\\', '/').split('/')).lower()


# ── 数据库 ──────────────────────────────────────────────────

class FileDB:
    """文件去重数据库"""

    def __init__(self):
        self.files: list[FileRec] = []
        self.by_sid: dict[str, list[FileRec]] = defaultdict(list)
        self.by_dir: dict[str, list[FileRec]] = defaultdict(list)
        self.scan_root: str = ''

    # ── 解析 ──

    @classmethod
    def from_dsr(cls, path: str) -> 'FileDB':
        """从 .dsr 文件解析"""
        with gzip.open(path, 'rb') as f:
            root = ET.fromstring(f.read())

        db = cls()
        dirs = [d.get('n') for d in root.find('dirs')]
        db.scan_root = cls._infer_scan_root(dirs)

        records = []
        for f_elem in root.find('files'):
            d_idx = int(f_elem.get('d'), 16) - 1
            full_dir = os.path.normpath(cls._resolve_dir(d_idx, dirs, db.scan_root))
            full_path = os.path.join(full_dir, f_elem.get('n'))

            rec = FileRec(
                path=full_path,
                dir=full_dir,
                name=f_elem.get('n'),
                sid=f_elem.get('sid'),
                fl=f_elem.get('fl', ''),
            )
            records.append(rec)

        # 按 (目录, 文件名) 排序 → 同目录文件连续排列
        records.sort(key=lambda r: (r.dir.lower(), r.name.lower()))
        db.files = records

        # 构建索引
        for rec in records:
            db.by_sid[rec.sid].append(rec)
            db.by_dir[rec.dir].append(rec)

        return db

    def to_dsr_xml(self) -> bytes:
        """将当前状态导出为 .dsr 的 XML 内容"""
        from collections import OrderedDict
        # 收集所有不重复目录并建立映射
        dir_list = sorted(set(r.dir for r in self.files))
        # 相对化目录
        scan_root_norm = os.path.normpath(self.scan_root)
        dir_map = {}
        xml_dirs = []
        for d in dir_list:
            dn = os.path.normpath(d)
            if dn.startswith(scan_root_norm):
                rel = os.path.relpath(dn, scan_root_norm)
                xml_dirs.append(rel)
            else:
                xml_dirs.append(dn)
            dir_map[d] = len(xml_dirs)  # 1-based

        root_el = ET.Element('root', {'MinimalSupportedVersion': '6.0'})
        dirs_el = ET.SubElement(root_el, 'dirs')
        for d in xml_dirs:
            ET.SubElement(dirs_el, 'd', {'n': d})

        files_el = ET.SubElement(root_el, 'files')
        for rec in self.files:
            attrs = {
                'n': rec.name,
                'd': format(dir_map[rec.dir], 'X'),  # hex
                's': '0',
                'sid': rec.sid,
                'dt': '0',
                'fl': rec.fl or '1',
            }
            ET.SubElement(files_el, 'f', attrs)

        return b'<?xml version="1.0" encoding="utf-8"?>' + ET.tostring(root_el, encoding='utf-8')

    def save_dsr(self, path: str):
        """保存为 .dsr 文件"""
        data = self.to_dsr_xml()
        with gzip.open(path, 'wb') as f:
            f.write(data)

    # ── 内部工具 ──

    @staticmethod
    def _resolve_dir(d, dirs, scan_root):
        raw = dirs[d]
        if raw.startswith(".\\") or raw.startswith("./"):
            return os.path.normpath(os.path.join(scan_root, raw[2:]))
        return os.path.normpath(raw)

    @staticmethod
    def _infer_scan_root(dirs):
        abs_dirs = [d for d in dirs if d.startswith("E:")]
        if not abs_dirs:
            return "E:\\Code\\loveMentor\\docs\\百度网盘"
        return os.path.commonpath(abs_dirs)

    # ── 基本查询 ──

    @property
    def total_files(self):
        return len(self.files)

    @property
    def total_sids(self):
        return len(self.by_sid)

    @property
    def duplicate_groups(self):
        """所有真正有重复的组（sid 出现 2+ 次）"""
        return [(sid, files) for sid, files in self.by_sid.items() if len(files) >= 2]

    @property
    def total_dupe_groups(self):
        return sum(1 for _, f in self.by_sid.items() if len(f) >= 2)

    def summary(self):
        """打印概况"""
        dupes = self.duplicate_groups
        total_dupe_files = sum(len(f) for _, f in dupes)
        unique_files = sum(1 for _, f in self.by_sid.items() if len(f) == 1)

        print(f"FileDB 概况")
        print(f"{'='*50}")
        print(f"  扫描根目录: {self.scan_root}")
        print(f"  总文件数:   {self.total_files}")
        print(f"  总 sid 数:  {self.total_sids}")
        print(f"  ├─ 唯一文件: {unique_files}")
        print(f"  └─ 重复组:   {self.total_dupe_groups}")
        print(f"      └─ 涉及: {total_dupe_files} 个文件")
        print(f"  目录数:     {len(self.by_dir)}")
        print()

        # 按文件数分布
        size_dist = defaultdict(int)
        for sid, files in self.by_sid.items():
            size_dist[len(files)] += 1
        print("重复组大小分布:")
        for n in sorted(size_dist):
            label = "唯一" if n == 1 else f"重复×{n}"
            print(f"  {label}: {size_dist[n]} 组")

    # ── 分析：仅差 (1) 后缀的重复 ──

    def rename_dupes(self):
        """返回路径仅差 Windows (1) 后缀的重复组列表。
        每组: (sid, keep: FileRec, delete: list[FileRec], n_paren: int)
        注：过滤掉路径完全一致（无任何 (1) 差异，如同一文件多 fl 记录）的组。"""
        results = []
        for sid, files in self.by_sid.items():
            if len(files) <= 1:
                continue
            norms = set(normalize_path(f.path) for f in files)
            if len(norms) != 1:
                continue
            # 确保至少有一条路径包含 (1) 后缀（排除完全一致的同路径多 fl 记录）
            has_paren = any(f.paren_count > 0 for f in files)
            if not has_paren:
                continue
            files_sorted = sorted(files, key=lambda f: (f.paren_count, f.fl != '1', f.fl))
            results.append((sid, files_sorted[0], files_sorted[1:], files_sorted[0].paren_count))
        results.sort(key=lambda x: -len(x[2]))
        return results

    # ── 分析：完全重叠的目录 ──

    def dup_folders(self, min_files=1):
        """查找子文件完全重叠的重复目录。
        返回 [(signature, [(dir, [files])])]"""
        # 对于每个目录，按 (name, sid) 做签名
        sig_map = defaultdict(list)
        for dir_path, files in self.by_dir.items():
            sig = tuple(sorted((f.name, f.sid) for f in files))
            if len(files) >= min_files:
                sig_map[sig].append((dir_path, files))

        results = []
        for sig, entries in sig_map.items():
            if len(entries) >= 2:
                results.append(entries)
        results.sort(key=lambda e: -len(e[0][1]))
        return results

    # ── 分析：按目录看重复情况 ──

    def dir_stats(self):
        """每个目录的重复统计: [(dir, total, dupe_count), ...]"""
        stats = []
        for dir_path, files in self.by_dir.items():
            sids_seen = defaultdict(list)
            for f in files:
                sids_seen[f.sid].append(f)
            dupe_count = sum(len(v) for v in sids_seen.values() if len(v) > 1)
            stats.append((dir_path, len(files), dupe_count))
        stats.sort(key=lambda x: -x[2])
        return stats

    # ── 去重：优先保留指定目录 ──

    def dedup_keep_dir(self, keep_dir: str, execute=False, dry_run=True):
        """对每个重复组，如果其中文件在 keep_dir 下，删除其他目录的副本。"""
        to_delete = []
        to_keep = []

        for sid, files in self.by_sid.items():
            if len(files) <= 1:
                continue
            keep = [f for f in files if keep_dir in f.dir.replace('\\', '/').split('/')]
            delete = [f for f in files if f not in keep]
            if not keep:
                continue
            to_keep.extend(keep)
            for f in delete:
                to_delete.append(f)
                if not dry_run and execute:
                    if os.path.exists(f.path):
                        os.remove(f.path)
                        print(f"  删 {f.path}")

        return to_delete, to_keep

    # ── 去重：同目录保留最长文件名 ──

    def dedup_samedir_longest(self, execute=False, dry_run=True):
        """对每个重复组按目录分组，同目录下保留文件名最长的。"""
        to_delete = []
        to_keep = []

        for sid, files in self.by_sid.items():
            if len(files) <= 1:
                continue
            # 按目录分组
            dir_groups = defaultdict(list)
            for f in files:
                dir_groups[f.dir].append(f)

            for dir_path, grp in dir_groups.items():
                if len(grp) <= 1:
                    to_keep.extend(grp)
                    continue
                grp.sort(key=lambda f: (f.name_len, f.name))
                keep, delete = grp[-1:], grp[:-1]
                to_keep.extend(keep)
                for f in delete:
                    to_delete.append(f)
                    if not dry_run and execute:
                        if os.path.exists(f.path):
                            os.remove(f.path)
                            print(f"  删 {f.path}")

        return to_delete, to_keep

    # ── 去重：清理 (1) 后缀副本 ──

    def clean_rename_dupes(self, execute=False):
        """清理路径仅差 (1) 后缀的重复。保留 (1) 层数最少的文件。"""
        rename_groups = self.rename_dupes()
        to_delete = []
        to_keep = []

        for sid, keep, delete_list, _ in rename_groups:
            to_keep.append(keep)
            for f in delete_list:
                if execute and os.path.exists(f.path):
                    os.remove(f.path)
                to_delete.append(f)

        if execute:
            # 清理空目录
            affected = set(os.path.dirname(f.path) for f in to_delete)
            for root_dir in sorted(affected):
                for r, dirs, files in os.walk(root_dir, topdown=False):
                    for d in dirs:
                        fp = os.path.join(r, d)
                        try:
                            if not os.listdir(fp):
                                os.rmdir(fp)
                        except OSError:
                            pass

        return to_delete, to_keep

    # ── 安全删除并清理记录 ──

    def apply(self, to_delete: list[FileRec], execute=False, dry_run=True):
        """将文件从数据库中移除。execute=True 时同时删磁盘文件。"""
        if execute:
            for f in to_delete:
                if os.path.exists(f.path):
                    os.remove(f.path)
        # 从索引中移除
        delete_set = set(to_delete)
        for f in to_delete:
            self.by_sid[f.sid].remove(f)
            if not self.by_sid[f.sid]:
                del self.by_sid[f.sid]
            self.by_dir[f.dir].remove(f)
            if not self.by_dir[f.dir]:
                del self.by_dir[f.dir]
        self.files = [f for f in self.files if f not in delete_set]


# ── CLI ─────────────────────────────────────────────────────

def main():
    cmds = {
        'summary':     '总体概况',
        'dupes':       '列出所有重复组',
        'dirs':        '目录重复统计',
        'rename':      '路径仅差(1)的重复组',
        'dup-folders': '完全重叠的重复目录',
        'clean-rename': '清理(1)后缀副本  [--execute]',
    }

    if len(sys.argv) < 3 or sys.argv[1] in ('-h', '--help'):
        print(f"用法: python {__file__} <文件.dsr> <命令> [--execute]\n")
        print("命令:")
        for cmd, desc in cmds.items():
            print(f"  {cmd:15s} {desc}")
        return

    dsr_path = sys.argv[1]
    cmd = sys.argv[2]
    execute = '--execute' in sys.argv

    db = FileDB.from_dsr(dsr_path)

    if cmd == 'summary':
        db.summary()

    elif cmd == 'dupes':
        for sid, files in sorted(db.duplicate_groups, key=lambda x: -len(x[1])):
            print(f"sid={sid} ({len(files)} 个文件)")
            for f in files:
                print(f"  {f.path}")
            print()

    elif cmd == 'dirs':
        stats = db.dir_stats()
        print(f"{'目录':<50s} {'文件':>5s} {'重复':>5s}")
        print('-' * 65)
        for d, total, dupe in stats[:30]:
            dshort = d[-48:] if len(d) > 48 else d
            print(f"{dshort:<50s} {total:5d} {dupe:5d}")
        if len(stats) > 30:
            print(f"... 还有 {len(stats)-30} 个目录")

    elif cmd == 'rename':
        results = db.rename_dupes()
        print(f"路径仅差 (1) 后缀的重复组: {len(results)}\n")
        for sid, keep, delete_list, _ in results:
            print(f"sid={sid} ({1+len(delete_list)} 个)")
            print(f"  [保] {keep.path}")
            for f in delete_list:
                print(f"  [删] {f.path}")
            print()
        if not execute:
            total = sum(len(d) for _, _, d, _ in results)
            print(f"可删除 {total} 个文件，加 --execute 执行")

    elif cmd == 'dup-folders':
        results = db.dup_folders()
        print(f"完全重叠的目录: {len(results)} 组\n")
        for entries in results:
            n_files = len(entries[0][1])
            print(f"({n_files} 个文件):")
            for dir_path, _ in entries:
                print(f"  {dir_path}")
            print()

    elif cmd == 'clean-rename':
        to_delete, to_keep = db.clean_rename_dupes(execute=execute)
        if execute:
            db.apply(to_delete, execute=True)
            db.save_dsr(dsr_path.replace('.dsr', '_cleaned.dsr'))
            print(f"已删除 {len(to_delete)} 个文件，已保存清理后 dsr")
        else:
            print(f"将删除 {len(to_delete)} 个文件，加 --execute 执行")

    else:
        print(f"未知命令: {cmd}")
        sys.exit(1)


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    main()
