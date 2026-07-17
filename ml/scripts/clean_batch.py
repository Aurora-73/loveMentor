#!/usr/bin/env python3
"""清洗 batch 中的指定窗口 — Trae 标注前调用，清洗后写回原文件。

工作流:
  1. label_batches.py --view --count 20 --offset N     ← 看到脏数据
  2. clean_batch.py  --count 20 --offset N --inplace    ← 清洗并写回
  3. label_batches.py --view --count 20 --offset N     ← 确认干净
  4. label_batches.py --submit "分数1" "分数2" ...     ← 标分

用法:
  python ml/scripts/clean_batch.py --batch 007 --count 20 --offset 480 --inplace
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# 确保 ml/ 在导入路径中
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from ml.cleaning_patterns import clean_message

BATCHES_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "ml_dataset" / "batches"
CLEANED_DIR = BATCHES_DIR / "rerun" / "cleaned"


def prune_message(content: str, phrases: list[str]) -> str:
    """删除包含指定短语的行，或在行内删除短语（特化清洗）。"""
    if not phrases:
        return content
    lines = content.split("\n")
    kept = []
    for line in lines:
        if any(p in line for p in phrases):
            cleaned_line = line
            for p in phrases:
                cleaned_line = cleaned_line.replace(p, "")
            cleaned_line = cleaned_line.strip()
            if cleaned_line:
                kept.append(cleaned_line)
        else:
            kept.append(line)
    return "\n".join(kept)


def clean_sample(sample: dict, prune_phrases: list[str] | None = None) -> dict | None:
    prune_phrases = prune_phrases or []
    valid = []
    for m in sample.get("messages", []):
        content = m.get("content", "")
        if prune_phrases:
            content = prune_message(content, prune_phrases)
        c = clean_message(content)
        if c:
            valid.append({
                "role": m["role"],
                "content": c,
                "timestamp": m.get("timestamp", 0),
            })
    if len(valid) < 6:
        return None
    return {
        "sample_id": sample.get("sample_id"),
        "contact_wxid": sample.get("contact_wxid"),
        "contact_remark": sample.get("contact_remark"),
        "turn_count": len(valid),
        "messages": valid,
    }


def display_sample(sample: dict, index: int) -> None:
    print(f"--- {index}. {sample['sample_id']} ({sample['turn_count']}轮) ---")
    for msg in sample["messages"]:
        role = "我" if msg["role"] == "me" else "她"
        content = msg["content"].replace("\n", " | ")[:120]
        print(f"[{role}] {content}")
    print()


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="清洗 batch 窗口并预览")
    parser.add_argument("--batch", required=True, help="batch 编号，如 007")
    parser.add_argument("--count", type=int, default=10, help="显示条数")
    parser.add_argument("--offset", type=int, default=0, help="起始偏移")
    parser.add_argument("--summary", action="store_true", help="只输出摘要")
    parser.add_argument("--output", help="输出到 JSONL 文件")
    parser.add_argument("--source", default="original",
                        choices=["original", "cleaned"],
                        help="数据源: original(默认) | cleaned(=rerun/cleaned/)")
    parser.add_argument("--inplace", action="store_true",
                        help="将清洗结果写回原 batch 文件（覆盖指定窗口）")
    parser.add_argument("--prune",
                        help="特化清洗：逗号分隔的短语列表，包含这些短语的行将被删除")
    args = parser.parse_args()

    prune_phrases = [p.strip() for p in args.prune.split(",")] if args.prune else []

    source_dir = CLEANED_DIR if args.source == "cleaned" else BATCHES_DIR
    batch_path = source_dir / f"batch_{args.batch}.jsonl"
    if not batch_path.exists():
        print(f"错误：找不到 {batch_path}", file=sys.stderr)
        sys.exit(1)

    with open(batch_path, "r", encoding="utf-8") as f:
        samples = [json.loads(line) for line in f if line.strip()]

    window = samples[args.offset:args.offset + args.count]
    if not window:
        print(f"batch_{args.batch}: offset={args.offset} 超出范围 ({len(samples)} 条)", file=sys.stderr)
        sys.exit(1)

    cleaned_list = []
    summary = {"before": 0, "after": 0, "chars_before": 0, "chars_after": 0, "discarded": 0}

    for sample in window:
        before_chars = sum(len(m["content"]) for m in sample["messages"])
        summary["before"] += len(sample["messages"])
        summary["chars_before"] += before_chars

        cleaned = clean_sample(sample, prune_phrases)
        if not cleaned:
            summary["discarded"] += 1
            continue

        after_chars = sum(len(m["content"]) for m in cleaned["messages"])
        summary["after"] += cleaned["turn_count"]
        summary["chars_after"] += after_chars
        cleaned_list.append(cleaned)

    # 输出结果
    if args.output:
        out_path = Path(args.output)
        with open(out_path, "w", encoding="utf-8") as f:
            for c in cleaned_list:
                f.write(json.dumps(c, ensure_ascii=False) + "\n")
        print(f"已写入 {out_path} ({len(cleaned_list)} 条)", file=sys.stderr)

    # --inplace：写回原 batch 文件
    if args.inplace:
        replaced = 0
        kept_original = 0
        for i, sample in enumerate(window):
            idx = args.offset + i
            if i < len(cleaned_list):
                samples[idx] = cleaned_list[i]
                replaced += 1
            # 清洗失败（不足6轮）保留原始样本不变
            else:
                kept_original += 1

        with open(batch_path, "w", encoding="utf-8") as f:
            for s in samples:
                f.write(json.dumps(s, ensure_ascii=False) + "\n")

        print(f"[inplace] batch_{args.batch} ({args.source}): {replaced} 条已清洗, {kept_original} 条保留原样", file=sys.stderr)
        # --inplace 时也显示摘要
        args.summary = True

    if not args.summary:
        for i, c in enumerate(cleaned_list):
            display_sample(c, i + 1)
        if not cleaned_list:
            print("清洗后全部不足 6 轮，无可用样本。")
    else:
        print(f"batch_{args.batch}[{args.offset}:{args.offset + args.count}]:")
        print(f"  原始: {summary['before']} 条消息 / {summary['chars_before']} 字符")
        print(f"  清洗: {summary['after']} 条消息 / {summary['chars_after']} 字符")
        print(f"  放弃: {summary['discarded']} 条 (不足 6 轮)")
        print(f"  可用: {len(cleaned_list)} 条")


if __name__ == "__main__":
    main()
