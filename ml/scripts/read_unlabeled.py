#!/usr/bin/env python3
"""读取未标注样本 — Trae 运行，查看需要清洗的对话。

用法:
  python ml/scripts/read_unlabeled.py --batch 001 --offset 0
  python ml/scripts/read_unlabeled.py --batch 001 --offset 0 --count 20

参数:
  --batch BATCH   批次号，如 001
  --offset N      从未标注样本起始的偏移（0 = 第一个未标注样本）
  --count N       读取数量（默认 50）

说明:
  - 未标注样本 = annotations 文件中没有记录的样本（之前被丢弃的-1，已移到文件末尾）
  - offset 从第一个未标注样本开始计算
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BATCHES_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "ml_dataset" / "batches"
ANNOTATIONS_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "ml_dataset" / "annotations"


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def get_annotated_ids(batch_num: str) -> set[str]:
    ann_path = ANNOTATIONS_DIR / f"annotations_{batch_num}.jsonl"
    return {ann["sample_id"] for ann in load_jsonl(ann_path)}


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="读取未标注样本")
    parser.add_argument("--batch", required=True, help="批次号，如 001")
    parser.add_argument("--offset", type=int, default=0, help="从未标注列表起始的偏移")
    parser.add_argument("--count", type=int, default=20, help="读取数量")
    args = parser.parse_args()

    batch_path = BATCHES_DIR / f"batch_{args.batch}.jsonl"
    if not batch_path.exists():
        print(f"错误：找不到批次文件 {batch_path}")
        sys.exit(1)

    samples = load_jsonl(batch_path)
    annotated_ids = get_annotated_ids(args.batch)

    unlabeled = [s for s in samples if s["sample_id"] not in annotated_ids]
    selected = unlabeled[args.offset:args.offset + args.count]

    if not selected:
        print(f"未找到未标注样本 (offset={args.offset}, count={args.count})")
        print(f"未标注样本总数: {len(unlabeled)}")
        sys.exit(1)

    print(f"=== batch_{args.batch} offset={args.offset} ({len(selected)} 个样本) ===")
    print()
    for i, s in enumerate(selected, 1):
        print(f"--- {i}. {s['sample_id']} ({len(s['messages'])} 轮) ---")
        for m in s["messages"]:
            role = "我" if m["role"] == "me" else "她"
            content = m["content"].replace("\n", " ")[:120]
            print(f"  [{role}] {content}")
        print()

    print(f"=== 清洗这 {len(selected)} 条 ===")
    print(f"python ml/scripts/clean_subset.py --batch {args.batch} --offset {args.offset} --count {args.count} --remove \"...\"")


if __name__ == "__main__":
    main()
