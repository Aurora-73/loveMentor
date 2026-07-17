#!/usr/bin/env python3
"""B2 成对监督数据准备。

对 me-side pilot-train 中联系人属于 canonical train 的样本，
每条构造一对监督记录：

  target=her → her 标签（来自 training_annotations.jsonl）
  target=me  → me 标签（来自 annotations_meside_000.jsonl）

输出:
  dataset/b2_paired_train.jsonl   — 成对训练数据
  dataset/b2_paired_info.json     — 元信息

用法:
  cd /home2/cme_code/lm/ml
  PY=/home2/cme_code/convert/python_env/bin/python3
  $PY scripts/prepare_b2_paired_data.py
"""
from __future__ import annotations

import json
from pathlib import Path
from collections import Counter

LABELS = [
    "information_exchange", "opinion_expression", "emotion_positive",
    "emotion_negative", "flirt", "question_asking", "self_disclosure",
    "invitation", "framing_boundary", "perfunctory",
]

BASE = Path(__file__).resolve().parent.parent  # ml/
CANDIDATES = BASE.parent / "data/ml_dataset/annotations/me_side_pilot_v1_candidates.jsonl"
ME_ANNOTATIONS = BASE.parent / "data/ml_dataset/annotations/annotations_meside_000.jsonl"
HER_ANNOTATIONS = BASE.parent / "data/ml_dataset/training_annotations.jsonl"
MANIFEST = BASE / "models/canonical_manifest.json"

OUTPUT = BASE.parent / "data/ml_dataset/b2_paired_train.jsonl"
INFO = BASE.parent / "data/ml_dataset/b2_paired_info.json"


def main():
    # 1. 加载 canonical 联系人划分
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    train_contacts = set(manifest["train_contacts"])
    val_contacts = set(manifest["val_contacts"])
    test_contacts = set(manifest["test_contacts"])

    # 2. 加载候选（去重）
    cands = {}
    with open(CANDIDATES, encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            cands.setdefault(d["sample_id"], d)

    # 3. 加载 me-side 标注（去重）
    me_labels = {}
    with open(ME_ANNOTATIONS, encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            sid = d["sample_id"]
            if sid in me_labels:
                continue
            if d.get("discard"):
                continue
            if d.get("target") != "me":
                continue
            labels = d.get("labels", {})
            if all(k in labels for k in LABELS):
                me_labels[sid] = labels

    # 4. 加载 her-side 标注（全量，用于匹配）
    her_labels = {}
    with open(HER_ANNOTATIONS, encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            sid = d["sample_id"]
            labels = d.get("labels", {})
            if all(k in labels for k in LABELS):
                her_labels[sid] = labels

    # 5. 筛选：me-side pilot train ∩ canonical train contacts
    paired = []
    skipped_val = 0
    skipped_test = 0
    skipped_no_her = 0

    for sid, cand in cands.items():
        if cand.get("split") != "train":
            continue
        if sid not in me_labels:
            continue

        contact = cand.get("contact_wxid", "?")

        # 只使用 canonical train 中的联系人
        if contact in val_contacts:
            skipped_val += 1
            continue
        if contact in test_contacts:
            skipped_test += 1
            continue
        if contact not in train_contacts:
            # 理论上不会走到这里（上一步检查过了）
            continue

        # her 标签必须存在
        her = her_labels.get(sid)
        if her is None:
            skipped_no_her += 1
            continue

        me = me_labels[sid]
        messages = cand.get("messages", [])

        paired.append({
            "sample_id": sid,
            "contact_wxid": contact,
            "messages": messages,
            "pairs": [
                {"target_role": "her", "labels": her},
                {"target_role": "me", "labels": me},
            ],
        })

    # 6. 写入
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8") as f:
        for p in paired:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")

    # 7. 标签分布统计
    her_dist = Counter()
    me_dist = Counter()
    for p in paired:
        for label in LABELS:
            her_dist[label] += p["pairs"][0]["labels"][label]
            me_dist[label] += p["pairs"][1]["labels"][label]
    n = len(paired)

    info = {
        "dataset": "b2_paired_train",
        "description": "B2 成对监督训练数据 — 同一对话、双 target_role、双标签",
        "source_her": str(HER_ANNOTATIONS),
        "source_me": str(ME_ANNOTATIONS),
        "total_paired_samples": n,
        "contacts": len(set(p["contact_wxid"] for p in paired)),
        "total_records": n * 2,  # 每条含 her + me 两条记录
        "skipped": {
            "canonical_val_contacts": skipped_val,
            "canonical_test_contacts": skipped_test,
            "missing_her_labels": skipped_no_her,
        },
        "label_means": {
            "her": {k: round(v / n, 2) for k, v in her_dist.items()},
            "me": {k: round(v / n, 2) for k, v in me_dist.items()},
        },
        "notes": [
            "仅包含联系人属于 canonical train 的样本（不含 val/test 联系人，防止泄漏）",
            "每条含一对记录：target_role='her' + her-side 标签 / target_role='me' + me-side 标签",
            "训练时对同一 batch 随机选择 target_role，确保模型见到同一对话的双视角",
        ],
    }

    with open(INFO, "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=2)

    print(f"B2 成对训练数据:")
    print(f"  样本数: {n}（每条 2 条记录 = {n * 2} 总训练记录）")
    print(f"  联系人: {info['contacts']}")
    print(f"  跳过 canonical val: {skipped_val}  跳过 canonical test: {skipped_test}")
    print(f"  输出: {OUTPUT}")
    print(f"  信息: {INFO}")
    print(f"\n  标签均值对比:")
    for label in LABELS:
        h = info["label_means"]["her"][label]
        m = info["label_means"]["me"][label]
        print(f"  {label:>25}: her={h:.2f}  me={m:.2f}  Δ={h-m:+.2f}")
    print(f"\n  144 条 held-out 保持不变：me_side_pilot_v1/held_out.jsonl")


if __name__ == "__main__":
    main()
