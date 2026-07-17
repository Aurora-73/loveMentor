#!/usr/bin/env python3
"""抽取 50 条 her-side 样本用于标注盲审。

分层抽样:
  1. 高行为分（flirt / question_asking / invitation ≥ 6）— 15 条
  2. 高不对称（her/me 双侧标注差异大） — 15 条
  3. 随机 — 15 条
  4. OCR 边界（低中文比例、乱码） — 5 条

输出（不包含原分数，供盲审）:
  outputs/blind_audit_50/samples.jsonl
  outputs/blind_audit_50/key.jsonl（原标签，仅用于后续对比）
  outputs/blind_audit_50/info.json
"""
from __future__ import annotations

import json
import random
from pathlib import Path
from collections import Counter

random.seed(42)

LABELS = [
    "information_exchange", "opinion_expression", "emotion_positive",
    "emotion_negative", "flirt", "question_asking", "self_disclosure",
    "invitation", "framing_boundary", "perfunctory",
]

BASE = Path(__file__).resolve().parent.parent  # ml/

HER_SAMPLES = BASE.parent / "data/ml_dataset/training_samples.jsonl"
HER_ANNOTATIONS = BASE.parent / "data/ml_dataset/training_annotations.jsonl"
ME_ANNOTATIONS = BASE.parent / "data/ml_dataset/annotations/annotations_meside_000.jsonl"

OUT_DIR = BASE / "outputs/blind_audit_50"
OUT_SAMPLES = OUT_DIR / "samples.jsonl"
OUT_KEY = OUT_DIR / "key.jsonl"
OUT_INFO = OUT_DIR / "info.json"


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1. 加载样本
    print("加载 her-side 样本...")
    sample_map = {}
    with open(HER_SAMPLES, encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            sample_map[d["sample_id"]] = d

    # 2. 加载 her 标注
    her_labels = {}
    with open(HER_ANNOTATIONS, encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            sid = d["sample_id"]
            labels = d.get("labels", {})
            if all(k in labels for k in LABELS):
                her_labels[sid] = labels

    # 3. 加载 me 标注（用于不对称采样）
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

    her_me_both = set(her_labels) & set(me_labels)
    print(f"  双侧标注: {len(her_me_both)} 条")

    # ── 池 1：高行为分 ──
    pool_high = []
    for sid in her_labels:
        if sid not in sample_map:
            continue
        h = her_labels[sid]
        max_score = max(h[k] for k in LABELS)
        if max_score >= 6:
            pool_high.append(sid)
    print(f"  高行为分池: {len(pool_high)} 条")

    # ── 池 2：高不对称（双侧标注中 her/me 差异大的）──
    pool_asym = []
    for sid in her_me_both:
        if sid not in sample_map:
            continue
        h = her_labels[sid]
        m = me_labels[sid]
        total_diff = sum(abs(h[k] - m[k]) for k in LABELS)
        # 至少有两个标签差异 ≥ 3 或总差异 ≥ 15
        big_diffs = sum(1 for k in LABELS if abs(h[k] - m[k]) >= 3)
        if total_diff >= 15 or big_diffs >= 2:
            pool_asym.append((total_diff, sid))
    pool_asym.sort(reverse=True)
    print(f"  高不对称池: {len(pool_asym)} 条")

    # ── 池 3：OCR 边界 ──
    def is_ocr_boundary(messages):
        text = " ".join(m.get("content", "") for m in messages)
        # 低中文比例
        cn_chars = sum(1 for c in text if "一" <= c <= "鿿")
        if len(text) > 30 and cn_chars < len(text) * 0.1:
            return True
        # 明显乱码
        garbled = ["lС", "oo@", "Hahahaaha", "hahah"]
        for g in garbled:
            if g in text:
                return True
        return False

    pool_ocr = []
    for sid, smp in sample_map.items():
        if sid not in her_labels:
            continue
        if is_ocr_boundary(smp.get("messages", [])):
            pool_ocr.append(sid)
    print(f"  OCR 边界池: {len(pool_ocr)} 条")

    # ── 池 4：全量随机 ──
    pool_random = [sid for sid in her_labels if sid in sample_map]
    print(f"  全量随机池: {len(pool_random)} 条")

    # ── 分层抽样 ──
    selected = set()
    strata = []

    # 1) 高行为分: 15
    random.shuffle(pool_high)
    for sid in pool_high:
        if sid not in selected:
            selected.add(sid)
            strata.append(("high_behavior", sid))
            if len(strata) >= 15:
                break

    # 2) 高不对称: 15
    for _, sid in pool_asym:
        if sid not in selected:
            selected.add(sid)
            strata.append(("high_asymmetry", sid))
            if sum(1 for s, _ in strata if s == "high_asymmetry") >= 15:
                break

    # 3) OCR 边界: 5
    random.shuffle(pool_ocr)
    for sid in pool_ocr:
        if sid not in selected:
            selected.add(sid)
            strata.append(("ocr_boundary", sid))
            if sum(1 for s, _ in strata if s == "ocr_boundary") >= 5:
                break

    # 4) 随机: 补齐到 50
    random.shuffle(pool_random)
    for sid in pool_random:
        if len(selected) >= 50:
            break
        if sid not in selected:
            selected.add(sid)
            strata.append(("random", sid))

    print(f"\n抽样结果: {len(selected)} 条")
    strata_count = Counter(s for s, _ in strata)
    for k, v in strata_count.most_common():
        print(f"  {k}: {v}")

    # ── 写入盲审文件（不含原分数）──
    with open(OUT_SAMPLES, "w", encoding="utf-8") as fs, \
         open(OUT_KEY, "w", encoding="utf-8") as fk:
        for stratum, sid in strata:
            smp = sample_map[sid]
            her = her_labels[sid]
            me_lbl = me_labels.get(sid)

            # 盲审样本：只含对话 + 空白评分表
            audit = {
                "sample_id": sid,
                "stratum": stratum,
                "target_role": "her",  # 明确标注目标角色
                "annotation_schema": "her_target_v1",
                "messages": smp.get("messages", []),
                "labels": {},  # 空白，供标注者填写
            }
            fs.write(json.dumps(audit, ensure_ascii=False) + "\n")

            # Key：原标签
            key = {
                "sample_id": sid,
                "stratum": stratum,
                "her_labels": her,
            }
            if me_lbl:
                key["me_labels"] = me_lbl
            fk.write(json.dumps(key, ensure_ascii=False) + "\n")

    # ── 信息 ──
    info = {
        "audit": "her_side_blind_reannotation",
        "description": "50 条 her-side 样本盲审。不展示原分数，重新按 target_role='her' 标注。",
        "total": len(selected),
        "strata": dict(strata_count),
        "annotation_guide": "每条样本的 TARGET 是'她'，只评价她的行为。另一方消息仅用于理解上下文。",
        "schema": "her_target_v1",
        "output_files": {
            "samples": str(OUT_SAMPLES),
            "key": str(OUT_KEY),
        },
    }

    with open(OUT_INFO, "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=2)

    print(f"\n盲审文件:")
    print(f"  样本: {OUT_SAMPLES}")
    print(f"  标签: {OUT_KEY}（不发给标注者）")
    print(f"  信息: {OUT_INFO}")


if __name__ == "__main__":
    main()
