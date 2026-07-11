import os
import shutil
from pathlib import Path

NEED_DIR = Path(r"<external_path>")

def main():
    print("清理 <external_path> 目录...")
    
    for item in NEED_DIR.iterdir():
        if item.is_file():
            item.unlink()
            print(f"删除文件: {item.name}")
        elif item.is_dir():
            shutil.rmtree(item)
            print(f"删除目录: {item.name}")
    
    print("\n清理完成！请重新上传原始文件到 <external_path>")

if __name__ == "__main__":
    main()