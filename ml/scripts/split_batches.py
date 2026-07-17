#!/usr/bin/env python3
"""将 samples_chat_records.jsonl 拆分为 1000 条一批的文件。

输出到 data/ml_dataset/batches/batch_XXX.jsonl

用法:
  python ml/scripts/split_batches.py
"""
from __future__ import annotations

import json
from pathlib import Path

BATCH_SIZE = 1000
INPUT = Path(__file__).resolve().parent.parent.parent / "data" / "ml_dataset" / "samples_chat_records.jsonl"
OUTPUT_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "ml_dataset" / "batches"


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with open(INPUT, "r", encoding="utf-8") as f:
        samples = [json.loads(line) for line in f if line.strip()]

    total = len(samples)
    n_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE

    print(f"总样本: {total}")
    print(f"批次大小: {BATCH_SIZE}")
    print(f"批次数: {n_batches}")
    print(f"输出目录: {OUTPUT_DIR}")
    print()

    for i in range(n_batches):
        start = i * BATCH_SIZE
        end = min(start + BATCH_SIZE, total)
        batch = samples[start:end]
        out_path = OUTPUT_DIR / f"batch_{i+1:03d}.jsonl"
        with open(out_path, "w", encoding="utf-8") as f:
            for s in batch:
                f.write(json.dumps(s, ensure_ascii=False) + "\n")
        print(f"  batch_{i+1:03d}.jsonl: {len(batch)} 条 ({start+1}-{end})")

    print(f"\n完成。共 {n_batches} 个批次文件。")

    # 写入一份 README 说明
    readme = OUTPUT_DIR / "README.md"
    readme.write_text(
        f"# 标注批次\n\n将 `samples_chat_records.jsonl` 拆分为 {n_batches} 批，每批 {BATCH_SIZE} 条"
        f"（最后一批 {total - (n_batches-1)*BATCH_SIZE} 条）。\n\n"
        f"标注说明见 `ml/ANNOTATION_PROMPT.md`。\n\n"
        f"| 批次 | 文件 | 条数 |\n|------|------|------|\n"
        + "\n".join(
            f"| {i+1:03d} | batch_{i+1:03d}.jsonl | "
            f"{min((i+1)*BATCH_SIZE, total) - i*BATCH_SIZE} |"
            for i in range(n_batches)
        ),
        encoding="utf-8",
    )
    print(f"  README.md 已生成")


if __name__ == "__main__":
    main()
