#!/usr/bin/env python3
"""读取未标注样本 — Trae 运行，查看需要清洗的 50 条对话。

用法:
  python ml/scripts/read_unlabeled.py --batch 001 --offset 0
  python ml/scripts/read_unlabeled.py --batch 001 --offset 0 --count 20

参数:
  --batch BATCH   批次号，如 001
  --offset N      从未标注样本起始的偏移（0 = 第一个未标注样本）
  --count N       读取数量（默认 50）

说明:
  - 未标注样本 = annotations 文件中没有记录的样本（即之前被丢弃的-1，已移到文件末尾）
  - offset 从第一个未标注样本开始计算
  - 样本同时保存到 _work/ 目录，供 clean_subset.py 使用
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BATCHES_DIR = Path(__file__).resolve().parent.parent / "dataset" / "batches"
ANNOTATIONS_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "ml_dataset"
WORK_DIR = BATCHES_DIR / "_work"


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def get_annotated_ids(batch_num: str) -> set[str]:
    ann_path = ANNOTATIONS_DIR / f"annotations_{batch_num}.jsonl"
    return {ann["sample_id"] for ann in load_jsonl(ann_path)}


def display_samples(samples: list[dict], batch_num: str, offset: int) -> None:
    print(f"=== batch_{batch_num} offset={offset} ({len(samples)} 个样本) ===")
    print()
    for i, s in enumerate(samples, 1):
        print(f"--- {i}. {s['sample_id']} ({len(s['messages'])} 轮) ---")
        for m in s["messages"]:
            role = "我" if m["role"] == "me" else "她"
            content = m["content"].replace("\n", " ")[:120]
            print(f"  [{role}] {content}")
        print()


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="读取未标注样本")
    parser.add_argument("--batch", required=True, help="批次号，如 001")
    parser.add_argument("--offset", type=int, default=0, help="从未标注列表起始的偏移")
    parser.add_argument("--count", type=int, default=50, help="读取数量")
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

    # 保存参考文件供清洗脚本使用
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    ref_path = WORK_DIR / f"batch_{args.batch}_offset_{args.offset}.jsonl"
    with open(ref_path, "w", encoding="utf-8") as f:
        for s in selected:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")

    print(f"参考文件: {ref_path}")
    print()
    display_samples(selected, args.batch, args.offset)
    print(f"参考文件: {ref_path}")
    print(f"下一步: python ml/scripts/clean_subset.py --ref {ref_path} --out {WORK_DIR / f'batch_{args.batch}_offset_{args.offset}_clean.jsonl'} --remove \"...\"")


if __name__ == "__main__":
    main()
