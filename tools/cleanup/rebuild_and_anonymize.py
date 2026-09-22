import json
import os
import shutil
import time
from pathlib import Path

NEED_DIR = Path(r"<external_path>")
PROJECT_ROOT = Path(__file__).resolve().parents[2]
MAP_FILE = PROJECT_ROOT / "docs" / ".name_mapping" / "ocr_name_map.json"
FILE_PATHS = PROJECT_ROOT / "file_paths.txt"

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

def collect_paths(root: Path):
    dir_keys = set()
    file_keys = set()
    dirs = []
    files = []

    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        rel_str = rel.as_posix()
        if path.is_dir():
            dirs.append(rel_str)
            dir_keys.add(rel_str)
        elif path.is_file():
            files.append(rel_str)
            file_keys.add(rel_str)

    return dirs, files, dir_keys, file_keys

def main():
    print("=== 步骤1: 读取文件路径列表 ===")
    with open(FILE_PATHS, "r", encoding="utf-8") as f:
        paths = [line.strip() for line in f if line.strip()]
    
    print(f"读取到 {len(paths)} 个文件路径")
    
    print("\n=== 步骤2: 重建文件夹结构 ===")
    for rel_path in paths:
        full_path = NEED_DIR / rel_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        print(f"创建目录: {full_path.parent}")
    
    print("\n=== 步骤3: 移动文件到正确位置 ===")
    for rel_path in paths:
        filename = Path(rel_path).name
        src = NEED_DIR / filename
        dst = NEED_DIR / rel_path
        
        if src.exists():
            print(f"移动: {filename} -> {rel_path}")
            shutil.move(str(src), str(dst))
        else:
            print(f"跳过: {filename} (不存在)")
    
    print("\n=== 步骤4: 解压298课程资料.zip ===")
    zip_path = NEED_DIR / r"【A07】几百套聊天案例合集/聊天记录新整理80套/聊天记录8/聊天案例/298课程资料.zip"
    if zip_path.exists():
        extract_dir = zip_path.parent / "298课程资料"
        if not extract_dir.exists():
            extract_dir.mkdir(parents=True, exist_ok=True)
        shutil.unpack_archive(str(zip_path), str(extract_dir))
        print(f"解压成功: {zip_path}")
    else:
        print(f"未找到: {zip_path}")
    
    print("\n=== 步骤5: 加载映射文件 ===")
    mapping = load_mapping()
    dir_forward = mapping.get("dir_forward", {})
    file_forward = mapping.get("file_forward", {})
    dir_reverse = mapping.get("dir_reverse", {})
    file_reverse = mapping.get("file_reverse", {})
    
    print("\n=== 步骤6: 收集当前路径并扩展映射库 ===")
    dirs, files, dir_keys, file_keys = collect_paths(NEED_DIR)
    print(f"发现 {len(dirs)} 个目录, {len(files)} 个文件")
    
    new_dirs = []
    new_files = []
    
    for d in sorted(dir_keys):
        if d not in dir_forward:
            new_dirs.append(d)
    
    for f in sorted(file_keys):
        if f not in file_forward:
            new_files.append(f)
    
    print(f"新目录: {len(new_dirs)} 个")
    print(f"新文件: {len(new_files)} 个")
    
    if new_dirs or new_files:
        next_d = next_id(dir_forward, "d")
        next_f = next_id(file_forward, "f")
        
        for d in sorted(new_dirs):
            mapped = f"d{next_d:06d}"
            dir_forward[d] = mapped
            dir_reverse[mapped] = d
            next_d += 1
        
        for f in sorted(new_files):
            mapped = f"f{next_f:06d}"
            file_forward[f] = mapped
            file_reverse[mapped] = f
            next_f += 1
        
        save_mapping(mapping)
        print("映射文件已更新")
    
    print("\n=== 步骤7: 创建匿名化目录结构 ===")
    for rel_dir in sorted(dirs, key=lambda s: (len(s.split("/")), s)):
        parts = rel_dir.split("/")
        current = ""
        mapped_parts = []
        
        for part in parts:
            if current:
                current += "/" + part
            else:
                current = part
            mapped_parts.append(dir_forward[current])
        
        mapped_dir = NEED_DIR / "/".join(mapped_parts)
        if not mapped_dir.exists():
            mapped_dir.mkdir(parents=True, exist_ok=True)
            print(f"MKDIR {mapped_dir}")
    
    print("\n=== 步骤8: 移动文件到匿名化位置 ===")
    for rel_file in files:
        rel_path = Path(rel_file)
        parent_str = rel_path.parent.as_posix() if rel_path.parent != Path(".") else ""
        suffix = rel_path.suffix
        
        if parent_str:
            parts = parent_str.split("/")
            current = ""
            mapped_parts = []
            for part in parts:
                if current:
                    current += "/" + part
                else:
                    current = part
                mapped_parts.append(dir_forward[current])
            mapped_parent = "/".join(mapped_parts)
        else:
            mapped_parent = ""
        
        mapped_stem = file_forward[rel_file]
        
        if mapped_parent:
            mapped_path = f"{mapped_parent}/{mapped_stem}{suffix}"
        else:
            mapped_path = f"{mapped_stem}{suffix}"
        
        src = NEED_DIR / rel_file
        dst = NEED_DIR / mapped_path
        
        if src.exists():
            print(f"MOVE {rel_file} -> {mapped_path}")
            shutil.move(str(src), str(dst))
        else:
            print(f"SKIP (不存在): {rel_file}")
    
    print("\n=== 步骤9: 删除旧目录 ===")
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
