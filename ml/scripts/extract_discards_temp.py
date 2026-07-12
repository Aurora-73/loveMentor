"""从原始标注中提取 -1 (discard) 标记到 rerun 标注文件。"""
from __future__ import annotations

import json
from pathlib import Path

CLEANED = Path("ml/dataset/batches/rerun/cleaned")
ANNOT_DIR = Path("data/ml_dataset")


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def load_annotations(batch: str) -> dict[str, bool]:
    """返回 {sample_id: is_discard}"""
    anns = load_jsonl(ANNOT_DIR / f"annotations_{batch}.jsonl")
    return {a["sample_id"]: a.get("discard", False) for a in anns}


def main():
    total_discard = 0
    total_clean = 0

    for path in sorted(CLEANED.glob("batch_*.jsonl")):
        batch = path.name.replace("batch_", "").replace(".jsonl", "")
        samples = load_jsonl(path)
        orig_ann = load_annotations(batch)

        rerun_path = ANNOT_DIR / f"annotations_{batch}_rerun.jsonl"
        existing = {a["sample_id"] for a in load_jsonl(rerun_path)}

        discard_count = 0
        for s in samples:
            sid = s["sample_id"]
            if sid in existing:
                continue
            if sid in orig_ann and orig_ann[sid]:
                # 原始标注为 discard，写入 rerun
                record = {
                    "sample_id": sid,
                    "contact_wxid": s.get("contact_wxid", ""),
                    "discard": True,
                    "labels": {},
                }
                with open(rerun_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
                discard_count += 1

        total_discard += discard_count
        total_clean += len(samples)
        print(f"batch_{batch}: {len(samples)} 个样本, 提取 {discard_count} 个 -1")

    print(f"\n总计: {total_clean} 个 cleaned 样本, {total_discard} 个标记为 discard")


if __name__ == "__main__":
    main()
