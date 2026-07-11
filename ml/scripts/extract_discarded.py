#!/usr/bin/env python3
"""从已标注批次中提取放弃样本到 rerun/ 目录。

用法:
  python ml/scripts/extract_discarded.py
"""
from __future__ import annotations

import json
from pathlib import Path

BATCHES_DIR = Path(__file__).resolve().parent.parent / "dataset" / "batches"
RERUN_DIR = BATCHES_DIR / "rerun"
ANNOTATIONS_BASE = Path(__file__).resolve().parent.parent.parent / "data" / "ml_dataset"


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def main():
    batches = sorted(f.name for f in BATCHES_DIR.glob("batch_*.jsonl"))
    total_extracted = 0

    for batch_file in batches:
        batch_num = batch_file.replace("batch_", "").replace(".jsonl", "")
        batch_path = BATCHES_DIR / batch_file
        ann_path = ANNOTATIONS_BASE / f"annotations_{batch_num}.jsonl"

        if not ann_path.exists():
            continue

        samples = {s["sample_id"]: s for s in load_jsonl(batch_path)}
        annotations = load_jsonl(ann_path)

        discarded = [a for a in annotations if a.get("discard")]
        if not discarded:
            continue

        RERUN_DIR.mkdir(parents=True, exist_ok=True)
        out_path = RERUN_DIR / batch_file

        count = 0
        with open(out_path, "w", encoding="utf-8") as f:
            for ann in discarded:
                sid = ann["sample_id"]
                if sid in samples:
                    f.write(json.dumps(samples[sid], ensure_ascii=False) + "\n")
                    count += 1

        print(f"  {batch_file}: {count} 条放弃样本 → {out_path}")
        total_extracted += count

    print(f"\n总计: {total_extracted} 条放弃样本已提取到 {RERUN_DIR}/")
    print()

    # 汇总统计
    total_in_rerun = sum(1 for f in RERUN_DIR.glob("batch_*.jsonl") for _ in open(f, encoding="utf-8") if f)
    print(f"rerun 目录共 {total_in_rerun} 条待清洗样本")


if __name__ == "__main__":
    main()
