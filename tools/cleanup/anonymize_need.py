import json
import os
import shutil
import time
from pathlib import Path

NEED_DIR = Path(r"<external_path>")
PROJECT_ROOT = Path(__file__).resolve().parents[2]
MAP_FILE = PROJECT_ROOT / "docs" / ".name_mapping" / "ocr_name_map.json"

def load_mapping():
    with open(MAP_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_mapping(data):
    data["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    with open(MAP_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def next_id(existing_ids, prefix):
    max_num = 0
    for id_val in existing_ids.values():
        if id_val.startswith(prefix):
            try:
                num = int(id_val[len(prefix):])
                max_num = max(max_num, num)
            except ValueError:
                pass
    return max_num + 1

def map_dir(rel_dir_str: str, dir_forward: dict) -> str:
    if rel_dir_str == ".":
        return "."
    
    parts = rel_dir_str.split("/")
    current = ""
    mapped_parts = []
    
    for part in parts:
        if current:
            current += "/" + part
        else:
            current = part
        
        if current in dir_forward:
            mapped_parts.append(dir_forward[current])
        else:
            mapped_parts.append(part)
    
    return "/".join(mapped_parts)

def map_file(rel_file_str: str, dir_forward: dict, file_forward: dict) -> str:
    rel_path = Path(rel_file_str)
    parent_str = rel_path.parent.as_posix() if rel_path.parent != Path(".") else ""
    suffix = rel_path.suffix
    
    mapped_parent = map_dir(parent_str, dir_forward) if parent_str else ""
    
    if rel_file_str in file_forward:
        mapped_stem = file_forward[rel_file_str]
    else:
        mapped_stem = rel_path.stem
    
    if mapped_parent:
        return f"{mapped_parent}/{mapped_stem}{suffix}"
    else:
        return f"{mapped_stem}{suffix}"

def collect_paths(root: Path):
    dirs = []
    files = []
    
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        rel_str = rel.as_posix()
        if path.is_dir():
            dirs.append(rel_str)
        elif path.is_file():
            files.append(rel_str)
    
    return dirs, files

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    
    print("加载映射文件...")
    mapping = load_mapping()
    dir_forward = mapping.get("dir_forward", {})
    file_forward = mapping.get("file_forward", {})
    dir_reverse = mapping.get("dir_reverse", {})
    file_reverse = mapping.get("file_reverse", {})
    
    print("收集当前路径...")
    dirs, files = collect_paths(NEED_DIR)
    print(f"发现 {len(dirs)} 个目录, {len(files)} 个文件")
    
    new_dirs = []
    new_files = []
    
    for d in dirs:
        if d not in dir_forward:
            new_dirs.append(d)
    
    for f in files:
        if f not in file_forward:
            new_files.append(f)
    
    print(f"\n未映射的目录: {len(new_dirs)} 个")
    for d in new_dirs:
        print(f"  {d}")
    
    print(f"\n未映射的文件: {len(new_files)} 个")
    for f in new_files:
        print(f"  {f}")
    
    if new_dirs or new_files:
        print("\n扩展映射库...")
        next_d = next_id(dir_forward, "d")
        next_f = next_id(file_forward, "f")
        
        for d in sorted(new_dirs):
            mapped = f"d{next_d:06d}"
            dir_forward[d] = mapped
            dir_reverse[mapped] = d
            print(f"  目录: {d} -> {mapped}")
            next_d += 1
        
        for f in sorted(new_files):
            mapped = f"f{next_f:06d}"
            file_forward[f] = mapped
            file_reverse[mapped] = f
            print(f"  文件: {f} -> {mapped}")
            next_f += 1
        
        if not args.dry_run:
            save_mapping(mapping)
            print("\n映射文件已更新")
    
    print("\n文件映射预览:")
    for rel_file in files[:10]:
        mapped = map_file(rel_file, dir_forward, file_forward)
        print(f"  {rel_file}")
        print(f"    -> {mapped}")
    
    if len(files) > 10:
        print(f"    ... 还有 {len(files) - 10} 个文件")
    
    if args.dry_run:
        print("\n【DRY RUN】未执行任何实际操作")
        return
    
    print("\n映射文件...")
    for rel_file in files:
        mapped = map_file(rel_file, dir_forward, file_forward)
        src = NEED_DIR / rel_file
        dst = NEED_DIR / mapped
        
        if src.exists():
            print(f"MOVE {rel_file} -> {mapped}")
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
        else:
            print(f"SKIP (不存在): {rel_file}")
    
    print("\n删除旧目录...")
    for rel_dir in sorted(dirs, key=lambda s: len(s.split("/")), reverse=True):
        old_dir = NEED_DIR / rel_dir
        if old_dir.exists() and old_dir.is_dir():
            try:
                old_dir.rmdir()
                print(f"RMDIR {rel_dir}")
            except OSError:
                pass
    
    print("\n完成！")

if __name__ == "__main__":
    main()
