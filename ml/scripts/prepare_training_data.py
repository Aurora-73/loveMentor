#!/usr/bin/env python3
"""合并所有 batch 的样本和标注为统一训练集。
输出到 data/ml_dataset/ 目录，A100 训练时通过 samba 直接读取。

去重策略（不修改原始标注文件）：
  原始标注文件（data/ml_dataset/annotations/annotations_*.jsonl）保留历史审计记录，
  本脚本按 sample_id 去重：首次出现保留，后续重复跳过。
  → training_samples.jsonl / training_annotations.jsonl 是唯一官方训练真源。
  → 如需物理清理原始文件，脚本不负责，由审计工具另行处理。

用法:
  # 输出到默认位置（data/ml_dataset/）
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

BATCHES_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "ml_dataset" / "batches"
ANN_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "ml_dataset" / "annotations"

# 2099 原始洁净样本集（直接从微信数据库提取，无噪音）
CLEAN_SAMPLES_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "ml_dataset" / "samples_phase0.jsonl"


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
                        help="输出目录（默认 data/ml_dataset/）")
    parser.add_argument("--stats", action="store_true",
                        help="只输出统计信息，不生成文件")
    args = parser.parse_args()

    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        output_dir = Path(__file__).resolve().parent.parent.parent / "data" / "ml_dataset"

    output_dir.mkdir(parents=True, exist_ok=True)

    # ── 加载所有样本 ──
    all_samples: dict[str, dict] = {}
    sample_to_batch: dict[str, str] = {}
    for bpath in get_batch_paths():
        bnum = batch_num_from_path(bpath)
        for s in load_jsonl(bpath):
            sid = s["sample_id"]
            if sid in all_samples:
                print(f"⚠ 样本重复（仅保留首次）: batch_{bnum} → {sid}")
            all_samples.setdefault(sid, s)
            sample_to_batch.setdefault(sid, bnum)

    # ── 加载所有标注（排除 discard，去重）──
    all_annotations: list[dict] = []
    seen_ann_ids: set[str] = set()
    ann_count = Counter()
    discard_count = Counter()
    for bpath in get_batch_paths():
        bnum = batch_num_from_path(bpath)
        apath = ANN_DIR / f"annotations_{bnum}.jsonl"
        for a in load_jsonl(apath):
            sid = a["sample_id"]
            if a.get("discard") or not a.get("labels"):
                discard_count[bnum] += 1
                continue
            if sid in seen_ann_ids:
                print(f"⚠ 标注重复（仅保留首次）: batch_{bnum} → {sid}")
                continue
            seen_ann_ids.add(sid)
            all_annotations.append(a)
            ann_count[bnum] += 1

    # ── 校验：annotation 必须对应有效样本 ──
    missing_samples = [a["sample_id"] for a in all_annotations if a["sample_id"] not in all_samples]
    if missing_samples:
        print(f"错误: {len(missing_samples)} 条标注无对应样本（如: {missing_samples[:3]}）")
        return

    # ── 校验：无标注的样本（仅警告）──
    annotated_ids = {a["sample_id"] for a in all_annotations}
    orphan_samples = [sid for sid in all_samples if sid not in annotated_ids]
    if orphan_samples:
        print(f"⚠ {len(orphan_samples)} 个样本无对应标注（如: {orphan_samples[:3]}）")

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

    # ── 加载 2099 原始洁净样本 ID ──
    clean_sample_ids: set[str] = set()
    if CLEAN_SAMPLES_PATH.exists():
        for s in load_jsonl(CLEAN_SAMPLES_PATH):
            clean_sample_ids.add(s["sample_id"])
        print(f"加载 2099 原始样本 ID: {len(clean_sample_ids)} 个")

    # ── 生成训练样本文件（含来源标记）──
    samples_out = output_dir / "training_samples.jsonl"
    with open(samples_out, "w", encoding="utf-8") as f:
        for a in all_annotations:
            s = all_samples[a["sample_id"]]
            record = {
                "sample_id": a["sample_id"],
                "contact_wxid": s.get("contact_wxid", ""),
                "messages": s["messages"],
                "turn_count": s.get("turn_count", len(s["messages"]) // 2),
                "from_clean_set": a["sample_id"] in clean_sample_ids,
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
    clean_count = sum(1 for a in all_annotations if a["sample_id"] in clean_sample_ids)
    config = {
        "labels": LABELS,
        "num_labels": len(LABELS),
        "score_range": [0, 9],
        "normalize": True,
        "total_samples": len(all_annotations),
        "total_contacts": len(unique_contacts),
        "source_groups": {
            "clean_2099": clean_count,
            "new_batch": len(all_annotations) - clean_count,
        },
    }
    config_out = output_dir / "training_config.json"
    with open(config_out, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    print(f"配置文件: {config_out}")

    # ── 最终校验：无重复 sample_id ──
    out_sids = [a["sample_id"] for a in all_annotations]
    if len(out_sids) != len(set(out_sids)):
        dupes = [sid for sid, cnt in Counter(out_sids).items() if cnt > 1]
        print(f"错误: 输出包含重复 sample_id: {dupes}")
        sys.exit(1)

    print(f"\n完成: {len(all_annotations)} 条训练数据, {len(unique_contacts)} 个联系人（校验通过）")


if __name__ == "__main__":
    main()
