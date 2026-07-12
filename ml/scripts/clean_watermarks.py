#!/usr/bin/env python3
"""全局水印清洗 — 对 batch 文件中所有样本（含已标注）去除导出水印。

用法:
  # 预览影响（Dry-run）
  python ml/scripts/clean_watermarks.py --dry-run

  # 清洗所有 batch
  python ml/scripts/clean_watermarks.py

  # 只清洗单个 batch
  python ml/scripts/clean_watermarks.py --batch 001

说明:
  - 原地修改 batch 文件（建议先 git commit）
  - 只去除明确的导出水印，不碰疑似正常聊天内容
  - 被修改的样本会打印修改前后的 diff
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

BATCHES_DIR = Path(__file__).resolve().parent.parent / "dataset" / "batches"

# ── 水印正则（逐个按序清除）──

WATERMARK_PATTERNS = [
    # 1. 瑞恩情感RYAN PUA 广告水印（各种截断变体）
    (r"瑞恩情感RYAN\s*PUA?", ""),
    (r"瑞恩情感", ""),
    (r"恩情感JA", ""),
    (r"RYAN\s*PUA", ""),

    # 2. 时间戳水印 — 合并文本变体（如 "January0018at9:3M"）
    (
        r"(?:January|February|March|April|May|June|"
        r"July|August|September|October|November|December)"
        r"\s*\d{1,4}\s*(?:at)?\s*\d{1,2}[:.]\d{1,2}\s*(?:AM|PM|PN)?[A-Z]?",
        "",
    ),
    # 3. 时间戳水印 — 标准格式（如 "January 8,2018 at 10:10"）
    (
        r"(?:January|February|March|April|May|June|"
        r"July|August|September|October|November|December)"
        r"\s+\d{1,2},?\s+\d{4}\s+at\s+\d{1,2}:\d{1,2}",
        "",
    ),
    # 4. 截断/合并日期水印（如 "March 12019atYA"、"May 19,2018 at恩情感"）
    (
        r"(?:January|February|March|April|May|June|"
        r"July|August|September|October|November|December)"
        r"\s*\d{1,2}[,\s]*\d{4}\s*(?:at\s*\w{1,15})?",
        "",
    ),
    # 5. 截断的月份碎片 + 数字（如 "nuary30018a4M"）
    (r"(?:nuary|ebruary|pril|une|uly|ugust|ovember|ecember)\s*\d+[a-zA-Z0-9]*", ""),

    # 6. 残留 standalone 时间标记（如 "7:44 PM@" 在消息中的部分）
    (r"\d{1,2}:\d{2}(?:AM|PM|PN)(?=[^\w]|$)", ""),

    # 7. Type a message 占位符
    (r"Type\s*a\s*message", "", re.IGNORECASE),

    # 8. 行首的截断 @ 提及（非单词中间）
    (r"^@[\s]*\n", "", re.MULTILINE),

    # 9. WCD 元数据叠加 — 距离+时间+已读 组合（安全识别）
    #    "1133km 8分钟前 已读 消息内容" → 去掉前缀
    (r"^\d+\.?\d*\s*km\s+\d+\s*(?:分钟|小时)前\s+已读[\s　]?", "", re.MULTILINE),
    #    整行纯时间+距离: "06-11 04:28 1.50km" 或 "0.82km 1小时前"
    (r"^\d{2}-\d{2}\s*\d{2}:\d{2}\s*\d+\.?\d*\s*km\s*$", "", re.MULTILINE),
    (r"^\d+\.?\d*\s*km\s+\d+\s*(?:分钟|小时)前\s*$", "", re.MULTILINE),
    #    行首"已读 "前缀（WCD 已读回执叠加）
    (r"^已读[\s　]", "", re.MULTILINE),

    # 10. OCR 水印 — "按住说话" 语音按钮叠加
    (r"^按住说话[^\n]*", "", re.MULTILINE),   # 行首整行删除
    (r"^安住说话[^\n]*", "", re.MULTILINE),   # OCR 误识别变体
    (r"按住说话", ""),                          # 行内/句尾叠加（安全移除子串）

    # 11. 截断的时间戳 + @ 提及（如 "04:10 @"）
    (r"^\d{1,2}:\d{2}\s*@[^\n]*", "", re.MULTILINE),

    # 12. 百度云/PUA 教程广告块
    (r"^帐号主体\s+京口区[^\n]*", "", re.MULTILINE),
    (r"京口区文才服装经营部[^\n]*", ""),  # 含倒序变体
    (r"^\d*百度云管家[^\n]*", "", re.MULTILINE),
    (r"^导\s+国内经典[^\n]*", "", re.MULTILINE),

    # 13. 微信号/PUA 广告
    (r"^微信号[：:]\s*(?:kaiyuanpua)?[^\n]*", "", re.MULTILINE),
    (r"开源pua[^\n]*", "", re.IGNORECASE),  # 非行首也可（完整短语，不可能出现于正常聊天）
    (r"^RYAN\s*PUA[^\n]*", "", re.MULTILINE),
    (r"^瑞恩[^\n]*", "", re.MULTILINE),

    # 14. WCD 联系人信息叠加（如 "<微艾+Y"、"微信+Y" 等行首结构）
    (r"^<微艾[^\n]*", "", re.MULTILINE),
    (r"^微信\+Y[^\n]*", "", re.MULTILINE),
]


def clean_text(text: str) -> str:
    """对单条消息内容去除所有水印。"""
    for pattern, repl, *flags in WATERMARK_PATTERNS:
        flag = flags[0] if flags else 0
        text = re.sub(pattern, repl, text, flags=flag)
    # 清理多余空白
    text = re.sub(r"\n{3,}", "\n\n", text)  # 多个连续空行缩为最多2个
    text = re.sub(r" +\n", "\n", text)  # 行尾空格
    text = re.sub(r"\n +", "\n", text)  # 行首空格
    text = text.strip()
    return text


def load_jsonl(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def save_jsonl(path: Path, records: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def diff_text(before: str, after: str) -> str:
    """生成可读的文本差异摘要。"""
    if before == after:
        return ""
    # 用行级 diff 简化展示
    b_lines = before.split("\n")
    a_lines = after.split("\n")
    parts = []
    i = 0
    while i < len(b_lines) or i < len(a_lines):
        b_line = b_lines[i] if i < len(b_lines) else ""
        a_line = a_lines[i] if i < len(a_lines) else ""
        if b_line != a_line:
            if b_line and a_line:
                parts.append(f"  - {b_line[:80]}")
                parts.append(f"  + {a_line[:80]}")
            elif b_line and not a_line:
                parts.append(f"  - {b_line[:80]}")
                parts.append(f"  + (removed)")
            elif not b_line and a_line:
                parts.append(f"  + {a_line[:80]}")
        i += 1
    return "\n".join(parts[:20])  # 最多显示 20 行差异


def process_batch(
    batch_num: str, dry_run: bool = False
) -> dict:
    """处理单个 batch 文件，返回修改统计。"""
    bpath = BATCHES_DIR / f"batch_{batch_num}.jsonl"
    if not bpath.exists():
        print(f"  [SKIP] batch_{batch_num}: 文件不存在")
        return {"total": 0, "modified": 0}

    samples = load_jsonl(bpath)
    total_modified = 0
    modifications = []

    for s in samples:
        sample_modified = False
        for m in s["messages"]:
            before = m["content"]
            after = clean_text(before)
            if before != after:
                m["content"] = after
                sample_modified = True

        # 清除水印删除后残留的空消息
        before_filter = len(s["messages"])
        s["messages"] = [m for m in s["messages"] if m["content"].strip()]
        if len(s["messages"]) != before_filter:
            s["turn_count"] = len(s["messages"]) // 2
            sample_modified = True

        if sample_modified:
            total_modified += 1
            modifications.append({
                "sample_id": s["sample_id"],
                "turn_count": s.get("turn_count", len(s["messages"])),
            })

    if dry_run:
        print(f"\n  batch_{batch_num}: {len(samples)} 样本, {total_modified} 条会被修改")
        for mod in modifications:
            print(f"    {mod['sample_id']} ({mod['turn_count']} 轮)")
    else:
        save_jsonl(bpath, samples)
        print(f"  batch_{batch_num}: {len(samples)} 样本, {total_modified} 条已修改")

    return {"total": len(samples), "modified": total_modified}


def show_diffs(batch_num: str) -> None:
    """dry-run 并显示具体的文本差异。"""
    bpath = BATCHES_DIR / f"batch_{batch_num}.jsonl"
    if not bpath.exists():
        return

    samples = load_jsonl(bpath)
    print(f"\n{'=' * 70}")
    print(f"batch_{batch_num} — 水印清理预览")
    print(f"{'=' * 70}")

    diffs_shown = 0
    for s in samples:
        sample_diff = False
        for m in s["messages"]:
            before = m["content"]
            after = clean_text(before)
            if before != after:
                if not sample_diff:
                    print(f"\n  [{s['sample_id']}] ({s.get('turn_count', '?')} 轮):")
                    sample_diff = True
                print(f"    message #{s['messages'].index(m) + 1}:")
                d = diff_text(before, after)
                if d:
                    print(d)
                diffs_shown += 1
                if diffs_shown >= 30:
                    print(f"\n  ... 还有更多差异，用 --dry-run 看总数")
                    return


def main():
    import argparse
    parser = argparse.ArgumentParser(description="全局水印清洗")
    parser.add_argument("--batch", help="只处理单个批次（如 001）")
    parser.add_argument("--dry-run", action="store_true", help="预览模式（不修改文件）")
    parser.add_argument("--diff", action="store_true", help="显示具体文本差异（默认只显示统计）")
    args = parser.parse_args()

    if args.batch:
        batches = [args.batch]
    else:
        batches = sorted(
            p.stem.replace("batch_", "")
            for p in BATCHES_DIR.glob("batch_*.jsonl")
        )

    if args.diff:
        for bnum in batches:
            show_diffs(bnum)
        return

    total_modified = 0
    for bnum in batches:
        result = process_batch(bnum, dry_run=args.dry_run)
        total_modified += result["modified"]

    mode = "[DRY RUN] " if args.dry_run else ""
    print(f"\n{mode}总计: {len(batches)} 个 batch, {total_modified} 条样本被修改")

    if args.dry_run:
        print("确认无误后去掉 --dry-run 执行实际清洗。")
        print("建议先用 --diff 查看具体修改内容。")


if __name__ == "__main__":
    main()
