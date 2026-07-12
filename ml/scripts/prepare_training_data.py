#!/usr/bin/env python3
"""合并所有 batch 的样本和标注为统一训练集。
输出到 ml/dataset/ 目录，A100 训练时通过 samba 直接读取。

用法:
  # 输出到默认位置（ml/dataset/）
  python ml/scripts/prepare_training_data.py

  # 输出到指定目录（如 data/ml_dataset/ 兼容旧流程）
  python ml/scripts/prepare_training_data.py --output-dir data/ml_dataset
"""
from __future__ import annotations

import json
import argparse
from pathlib import Path
from collections import Counter

LABELS = [
    "information_exchange", "opinion_expression", "emotion_positive",
    "emotion_negative", "flirt", "question_asking", "self_disclosure",
    "invitation", "framing_boundary", "perfunctory",
]

BATCHES_DIR = Path(__file__).resolve().parent.parent / "dataset" / "batches"
ANN_DIR = Path(__file__).resolve().parent.parent.parent / "ml" / "dataset" / "annotations"


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def get_batch_paths() -> list[Path]:
    return sorted(BATCHES_DIR.glob("batch_*.jsonl"))


def batch_num_from_path(path: Path) -> str:
    return path.name.replace("batch_", "").replace(".jsonl", "")


def main():
    parser = argparse.ArgumentParser(description="合并 batch 数据为训练集")
    parser.add_argument("--output-dir", default=None,
                        help="输出目录（默认 ml/dataset/）")
    parser.add_argument("--stats", action="store_true",
                        help="只输出统计信息，不生成文件")
    args = parser.parse_args()

    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        output_dir = Path(__file__).resolve().parent.parent / "dataset"

    output_dir.mkdir(parents=True, exist_ok=True)

    # ── 加载所有样本 ──
    all_samples: dict[str, dict] = {}
    sample_to_batch: dict[str, str] = {}
    for bpath in get_batch_paths():
        bnum = batch_num_from_path(bpath)
        for s in load_jsonl(bpath):
            all_samples[s["sample_id"]] = s
            sample_to_batch[s["sample_id"]] = bnum

    # ── 加载所有标注（排除 discard）──
    all_annotations: list[dict] = []
    ann_count = Counter()
    discard_count = Counter()
    for bpath in get_batch_paths():
        bnum = batch_num_from_path(bpath)
        apath = ANN_DIR / f"annotations_{bnum}.jsonl"
        for a in load_jsonl(apath):
            if a.get("discard") or not a.get("labels"):
                discard_count[bnum] += 1
                continue
            all_annotations.append(a)
            ann_count[bnum] += 1

    # ── 统计 ──
    unique_contacts = set()
    for s in all_samples.values():
        if s["sample_id"] in {a["sample_id"] for a in all_annotations}:
            unique_contacts.add(s.get("contact_wxid", ""))

    if args.stats:
        print(f"样本总数: {len(all_samples)}")
        print(f"有效标注: {len(all_annotations)}")
        print(f"丢弃: {sum(discard_count.values())}")
        print(f"联系人: {len(unique_contacts)}")
        print()
        print("按 batch:")
        for bnum in sorted(set(sample_to_batch.values())):
            print(f"  batch_{bnum}: {ann_count[bnum]} 有效 / {discard_count[bnum]} 丢弃")
        return

    # ── 生成训练样本文件 ──
    samples_out = output_dir / "training_samples.jsonl"
    with open(samples_out, "w", encoding="utf-8") as f:
        for a in all_annotations:
            s = all_samples[a["sample_id"]]
            record = {
                "sample_id": a["sample_id"],
                "contact_wxid": s.get("contact_wxid", ""),
                "messages": s["messages"],
                "turn_count": s.get("turn_count", len(s["messages"]) // 2),
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"样本文件: {samples_out} ({len(all_annotations)} 条)")

    # ── 生成标注文件 ──
    ann_out = output_dir / "training_annotations.jsonl"
    with open(ann_out, "w", encoding="utf-8") as f:
        for a in all_annotations:
            record = {
                "sample_id": a["sample_id"],
                "labels": {l: a["labels"].get(l, 0) for l in LABELS},
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"标注文件: {ann_out} ({len(all_annotations)} 条)")

    # ── 生成标签配置文件 ──
    config = {
        "labels": LABELS,
        "num_labels": len(LABELS),
        "score_range": [0, 9],
        "normalize": True,
        "total_samples": len(all_annotations),
        "total_contacts": len(unique_contacts),
    }
    config_out = output_dir / "training_config.json"
    with open(config_out, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    print(f"配置文件: {config_out}")

    print(f"\n完成: {len(all_annotations)} 条训练数据, {len(unique_contacts)} 个联系人")


if __name__ == "__main__":
    main()
