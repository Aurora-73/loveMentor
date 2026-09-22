import json
import time
from pathlib import Path

MAP_FILE = Path(__file__).resolve().parents[2] / "docs" / ".name_mapping" / "ocr_name_map.json"

def main():
    with open(MAP_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    dir_forward = data.get("dir_forward", {})
    file_forward = data.get("file_forward", {})
    dir_reverse = data.get("dir_reverse", {})
    file_reverse = data.get("file_reverse", {})
    
    bad_dir_keys = []
    for key in dir_forward:
        if key.startswith("d") or key.startswith("f"):
            bad_dir_keys.append(key)
    
    bad_file_keys = []
    for key in file_forward:
        if key.startswith("d") or key.startswith("f"):
            bad_file_keys.append(key)
    
    print(f"发现 {len(bad_dir_keys)} 个错误的目录映射（匿名→匿名）")
    for key in bad_dir_keys:
        val = dir_forward[key]
        print(f"  删除: {key} -> {val}")
        del dir_forward[key]
        if val in dir_reverse:
            del dir_reverse[val]
    
    print(f"\n发现 {len(bad_file_keys)} 个错误的文件映射（匿名→匿名）")
    for key in bad_file_keys:
        val = file_forward[key]
        print(f"  删除: {key} -> {val}")
        del file_forward[key]
        if val in file_reverse:
            del file_reverse[val]
    
    data["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    
    with open(MAP_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    print("\n修复完成！")

if __name__ == "__main__":
    main()
