"""将每个 batch 中 -1 的样本移到末尾，并从标注文件中移除标记。"""
from __future__ import annotations

import json
from pathlib import Path

BATCHES_DIR = Path("ml/dataset/batches")
ANNOT_DIR = Path("data/ml_dataset")


def load_jsonl(path):
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_jsonl(path, data):
    with open(path, "w", encoding="utf-8") as f:
        for item in data:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


total_moved = 0

for path in sorted(BATCHES_DIR.glob("batch_*.jsonl")):
    batch = path.name.replace("batch_", "").replace(".jsonl", "")
    samples = load_jsonl(path)
    anns = load_jsonl(ANNOT_DIR / f"annotations_{batch}.jsonl")

    # 找出被标记为 discard 的 sample_id
    discard_ids = {a["sample_id"] for a in anns if a.get("discard")}

    if not discard_ids:
        continue

    # 分离非 discard 和 discard 样本
    keep = []
    move = []
    for s in samples:
        if s["sample_id"] in discard_ids:
            move.append(s)
        else:
            keep.append(s)

    # 写出重排序的 batch 文件
    write_jsonl(path, keep + move)

    # 从标注文件中删除 discard 条目（只保留非 discard 的标注）
    keep_anns = [a for a in anns if not a.get("discard")]
    write_jsonl(ANNOT_DIR / f"annotations_{batch}.jsonl", keep_anns)

    print(f"batch_{batch}: {len(samples)} 样本, {len(move)} 个 -1 移到末尾, 标注保留 {len(keep_anns)} 条")
    total_moved += len(move)

print(f"\n总计移动了 {total_moved} 个 -1 样本到各 batch 末尾")
