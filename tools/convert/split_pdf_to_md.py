"""将山海鲸可视化产品白皮书 PDF 按章节拆分为多个 Markdown 文件。

目录：
  ─ 前言/封面/目录
  ─ 产品概述
  ─ 产品架构和配置要求
  ─ 产品功能
    ├─ 1、大屏管理 (含 1.1-1.10 各子节)
    ├─ 2、组件介绍 (含 2.1-2.6 各子节)
    └─ 3、数据源管理 (含 3.1-3.4 各子节)
  ─ 关于多算

用法:
    python tools/convert/split_pdf_to_md.py [--out <输出目录>]
"""

import os
import re
import sys
import argparse

import pymupdf4llm
from pymupdf4llm.helpers.document_layout import OCRMode

PDF_PATH = r"C:\Users\[REDACTED]\Desktop\山海鲸可视化产品白皮书.pdf"
PDF_NAME = "山海鲸可视化产品白皮书"

# ── 一级章节分割标记 ──
TOP_SPLIT = [
    (r"^##\s*二[、.．]\s*产品概述",      "二、产品概述"),
    (r"^##\s*三[、.．]\s*产品架构",      "三、产品架构和配置要求"),
    (r"^##\s*四[、.．]\s*产品功能",      "四、产品功能"),
    (r"^##\s*五[、.．]\s*关于多算",      "五、关于多算"),
]

# ── 四产品功能 内部的二级/三级分割标记 ──
# 只匹配加粗标题 `## **N** 、标题` 或 `## **N.N** 标题`
# 排除不加粗的编号（如 `2、添加数据` 只是步骤编号，不是章节）
SUB_SPLIT = re.compile(r"^##\s*\*\*(\d+(?:\.\d+)?)\*\*\s*[、,.]?\s*\S")


def find_split_positions(
    lines: list[str], marks: list[tuple[str, str]]
) -> list[tuple[int, str]]:
    """在 lines 中查找分割标记位置。
    返回: [(行号, 章节名), ...]
    """
    result: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        for pattern, name in marks:
            if re.match(pattern, line.strip()):
                result.append((i, name))
                break
    return result


def split_at_positions(
    lines: list[str], positions: list[tuple[int, str]], first_name: str = "一、前言",
    min_chars: int = 50,
) -> list[tuple[str, str]]:
    """按行号位置切分文本，跳过空段和仅含标题的段。
    返回: [(章节名, 文本), ...]
    """
    if not positions:
        text = "\n".join(lines).strip()
        return [(first_name, text)] if text else []

    sections: list[tuple[str, str]] = []

    # 第一段：开头到第一个标记前
    first_text = "\n".join(lines[: positions[0][0]]).strip()
    if len(first_text) >= min_chars:
        sections.append((first_name, first_text))

    # 中间段
    for j in range(len(positions)):
        start = positions[j][0]
        name = positions[j][1]
        end = positions[j + 1][0] if j + 1 < len(positions) else len(lines)
        text = "\n".join(lines[start:end]).strip()
        if len(text) >= min_chars:
            sections.append((name, text))

    return sections


def split_sub_sections(text: str, parent_name: str = "四、产品功能") -> list[tuple[str, str]]:
    """将四、产品功能的文本进一步拆为子章节。

    按 `## **N** 、` 和 `## **N.N** ` 分割。
    返回: [(章节名, 文本), ...]  章节名如 "1.1_软件界面"
    """
    lines = text.split("\n")
    positions: list[tuple[int, str]] = []

    for i, line in enumerate(lines):
        m = SUB_SPLIT.match(line.strip())
        if m:
            num = m.group(1)
            title = re.sub(r"^##\s*\*\*\d+(?:\.\d+)?\*\*\s*[、,.]?\s*", "", line.strip())
            title = title.strip()
            section_name = f"{num}_{title}" if title else num
            positions.append((i, section_name))

    return split_at_positions(lines, positions, first_name=parent_name)


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="将山海鲸可视化产品白皮书 PDF 按章节拆分"
    )
    default_out = os.path.join(os.path.dirname(PDF_PATH), f"{PDF_NAME}_分章")
    parser.add_argument("--out", default=default_out, help=f"输出目录（默认: {default_out}）")
    args = parser.parse_args()

    # 1. PDF → 完整 Markdown
    print("正在转换 PDF → Markdown ...", end=" ", flush=True)
    full_md = pymupdf4llm.to_markdown(
        PDF_PATH,
        write_images=False,
        image_path=None,
        page_chunks=False,
        use_ocr=OCRMode.NEVER,
    )
    total_kb = len(full_md.encode("utf-8")) // 1024
    print(f"OK ({total_kb} KB)")

    lines = full_md.split("\n")

    # 2. 一级分割
    top_pos = find_split_positions(lines, TOP_SPLIT)
    top_sections = split_at_positions(lines, top_pos)

    # 3. 处理 四、产品功能 — 拆为子章节
    out_dir = args.out
    os.makedirs(out_dir, exist_ok=True)

    file_index = 0
    total_files = 0

    # 先算总文件数（用于进度显示）
    for name, text in top_sections:
        if "四、产品功能" in name:
            subs = split_sub_sections(text)
            total_files += len(subs)
        else:
            total_files += 1

    print(f"\n共 {total_files} 个文件\n")

    for name, text in top_sections:
        if "四、产品功能" in name:
            # 拆子章节
            subs = split_sub_sections(text)
            for sub_name, sub_text in subs:
                file_index += 1
                # 文件名： 04_1.1_软件界面.md
                # 提取子章节编号前缀
                sub_num = sub_name.split("_")[0] if "_" in sub_name else sub_name
                # 避免重复的 "四" 前缀
                safe = re.sub(r"[、，.．/\\:]", "_", sub_name).rstrip("_")
                filename = f"{file_index:02d}_{safe}.md"
                filepath = os.path.join(out_dir, filename)
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(sub_text + "\n")
                kb = len(sub_text.encode("utf-8")) // 1024
                lines_n = sub_text.count("\n")
                print(f"  [{file_index:02d}/{total_files}] 四/{sub_name} ({lines_n} 行, {kb} KB) → {filename}")
        else:
            file_index += 1
            safe = re.sub(r"[、，.．/\\:]", "_", name).rstrip("_")
            filename = f"{file_index:02d}_{safe}.md"
            filepath = os.path.join(out_dir, filename)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(text + "\n")
            kb = len(text.encode("utf-8")) // 1024
            lines_n = text.count("\n")
            print(f"  [{file_index:02d}/{total_files}] {name} ({lines_n} 行, {kb} KB) → {filename}")

    print(f"\n完成！共 {file_index} 个文件")
    print(f"输出目录: {out_dir}")


if __name__ == "__main__":
    main()
