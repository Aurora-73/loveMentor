"""找出 docs/文档 里非 .txt/.md 的文件，输出相对路径。"""

import io
import sys
from pathlib import Path

# 修复 Windows 终端 GBK 编码问题
if sys.stdout.encoding and sys.stdout.encoding.upper() != "UTF-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

SOURCE = r"./docs/文档"
SKIP_EXTS = {".txt", ".md", ".json"}


def main():
    src = Path(SOURCE)
    if not src.is_dir():
        print(f"目录不存在: {SOURCE}", file=sys.stderr)
        return

    count = 0
    for fpath in sorted(src.rglob("*")):
        if not fpath.is_file():
            continue
        if fpath.suffix.lower() in SKIP_EXTS:
            continue
        rel = fpath.relative_to(src)
        print(rel)
        count += 1

    print(f"\n共 {count} 个文件")


if __name__ == "__main__":
    main()
