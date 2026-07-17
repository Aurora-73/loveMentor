#!/usr/bin/env python3
"""读取未标注样本（完整内容）— 用于标注。

用法:
  python read_for_label.py --batch 001 --offset 0 --count 20
"""
from __future__ import annotations
import json, sys
from pathlib import Path

BATCHES_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "ml_dataset" / "batches"
ANNOTATIONS_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "ml_dataset" / "annotations"

def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", required=True)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--count", type=int, default=20)
    args = parser.parse_args()

    batch_path = BATCHES_DIR / f"batch_{args.batch}.jsonl"
    samples = load_jsonl(batch_path)

    ann_path = ANNOTATIONS_DIR / f"annotations_{args.batch}.jsonl"
    ann_ids = {ann["sample_id"] for ann in load_jsonl(ann_path)} if ann_path.exists() else set()

    unlabeled = [s for s in samples if s["sample_id"] not in ann_ids]
    selected = unlabeled[args.offset:args.offset + args.count]

    if not selected:
        print(f"未找到未标注样本 (offset={args.offset})")
        print(f"未标注总数: {len(unlabeled)}")
        return

    print(f"=== batch_{args.batch} offset={args.offset} ({len(selected)} 个, 剩余: {len(unlabeled)}) ===\n")
    for i, s in enumerate(selected, 1):
        msgs = s["messages"]
        turns = len(msgs) // 2
        print(f"--- {i}. {s['sample_id']} ({turns}轮, {len(msgs)}条消息) ---")
        for m in msgs:
            role = "我" if m["role"] == "me" else "她"
            print(f"  [{role}] {m['content']}")
        print()

    print(f"=== 提交命令 ===")
    ids = [s["sample_id"] for s in selected]
    print(f"python ml/scripts/label_batches.py --batch {args.batch} --submit \"score1\" \"score2\" ... \"score{len(selected)}\"")
    print(f"样本ID顺序: {', '.join(ids)}")

if __name__ == "__main__":
    main()
