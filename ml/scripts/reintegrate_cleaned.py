#!/usr/bin/env python3
"""将清洗后的样本写回原 batch 文件，并删除对应的放弃标注。

用法:
  python ml/scripts/reintegrate_cleaned.py

流程:
  1. 从 rerun/cleaned/ 读取清洗后的样本
  2. 按 sample_id 匹配到原 batch 文件中的对应样本，替换 messages
  3. 从 annotations_XXX.jsonl 中删除该 sample_id 的放弃记录
  4. 写回 batch 文件和 annotations 文件
"""
from __future__ import annotations

import json
from pathlib import Path

BATCHES_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "ml_dataset" / "batches"
CLEANED_DIR = BATCHES_DIR / "rerun" / "cleaned"
ANNOTATIONS_BASE = Path(__file__).resolve().parent.parent.parent / "data" / "ml_dataset"


def main() -> None:
    # 收集所有清洗后样本（按 batch 文件名分组）
    cleaned_files = sorted(CLEANED_DIR.glob("batch_*.jsonl"))
    total_replaced = 0
    total_annotations_removed = 0

    for cf in cleaned_files:
        batch_name = cf.name  # batch_001.jsonl
        batch_path = BATCHES_DIR / batch_name

        # 读取清洗后样本
        with open(cf, "r", encoding="utf-8") as f:
            cleaned_samples = {s["sample_id"]: s for s in
                               (json.loads(line) for line in f if line.strip())}

        if not cleaned_samples:
            continue

        # 读取原 batch 文件并替换
        with open(batch_path, "r", encoding="utf-8") as f:
            original_samples = [json.loads(line) for line in f if line.strip()]

        replaced = 0
        for i, s in enumerate(original_samples):
            sid = s["sample_id"]
            if sid in cleaned_samples:
                cleaned = cleaned_samples[sid]
                # 替换 messages（保留原始顶层字段，替换 messages 和 turn_count）
                original_samples[i]["messages"] = cleaned["messages"]
                original_samples[i]["turn_count"] = cleaned["turn_count"]
                replaced += 1

        # 写回 batch 文件
        with open(batch_path, "w", encoding="utf-8") as f:
            for s in original_samples:
                f.write(json.dumps(s, ensure_ascii=False) + "\n")

        print(f"  {batch_name}: {replaced} 条已替换")
        total_replaced += replaced

        # ── 处理对应的 annotations 文件 ──
        batch_num = batch_name.replace("batch_", "").replace(".jsonl", "")
        ann_path = ANNOTATIONS_BASE / f"annotations_{batch_num}.jsonl"

        if not ann_path.exists():
            continue

        with open(ann_path, "r", encoding="utf-8") as f:
            annotations = [json.loads(line) for line in f if line.strip()]

        before = len(annotations)
        # 删除这些 sample_id 的标注记录（无论 discard 还是正常标注都删）
        cleaned_ids = set(cleaned_samples.keys())
        annotations = [a for a in annotations if a["sample_id"] not in cleaned_ids]
        removed = before - len(annotations)

        if removed > 0:
            with open(ann_path, "w", encoding="utf-8") as f:
                for a in annotations:
                    f.write(json.dumps(a, ensure_ascii=False) + "\n")
            print(f"  annotations_{batch_num}.jsonl: 移除 {removed} 条放弃记录")

        total_annotations_removed += removed

    print(f"\n总计: {total_replaced} 条清洗样本写回, {total_annotations_removed} 条放弃标注已删除")


if __name__ == "__main__":
    main()
