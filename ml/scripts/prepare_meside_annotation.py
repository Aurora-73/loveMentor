#!/usr/bin/env python3
"""生成 me_side_pilot_v1 候选集 — 三桶采样 + 联系人预切分。

采样策略：
  - diagnosis_bucket（~250）：她侧与我侧行为差异明显的边界案例
  - symmetric_bucket（~150）：双方行为相近的对称互动
  - random_bucket（~100）：按联系人/来源/分数分布分层的随机样本

输出字段：
  sample_id, contact_wxid, selection_bucket, selection_reason, split,
  messages, her_scores (已有), me_labels (待标), annotation_status

输出文件：
  ml/dataset/annotations/me_side_pilot_v1_candidates.jsonl

联系人预切分（70/30）在标注前完成，held_out 在标注期间不接触。

用法：
  cd /home2/cme_code/lm/ml
  /home2/cme_code/convert/python_env/bin/python3 scripts/prepare_meside_annotation.py
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path
from collections import defaultdict, Counter

ROOT = Path(__file__).resolve().parent.parent.parent

LABELS = [
    "information_exchange", "opinion_expression", "emotion_positive",
    "emotion_negative", "flirt", "question_asking", "self_disclosure",
    "invitation", "framing_boundary", "perfunctory",
]

OUTPUT_PATH = ROOT / "ml" / "dataset" / "annotations" / "me_side_pilot_v1_candidates.jsonl"
SAMPLES_PATH = ROOT / "ml" / "dataset" / "training_samples.jsonl"
ANNOTATIONS_PATH = ROOT / "ml" / "dataset" / "training_annotations.jsonl"

random.seed(42)


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def estimate_me_scores(messages: list[dict]) -> dict[str, float]:
    """规则估计"我"侧行为分数（0-9），仅用于候选筛选。"""
    me_texts = [m["content"] for m in messages if m.get("role") == "me"]
    combined = "\n".join(me_texts).lower()
    scores: dict[str, float] = {}

    if not me_texts:
        return {l: 0.0 for l in LABELS}

    q_words = sum(1 for t in me_texts if "?" in t or "？" in t or "吗" in t or "呢" in t)
    scores["question_asking"] = min(9.0, q_words * 1.5)

    sd_kw = ["我", "我的", "我家", "我觉得", "我想", "我喜欢", "我住", "我工作"]
    scores["self_disclosure"] = min(9.0, sum(combined.count(k) for k in sd_kw) * 0.3)

    fl_kw = ["可爱", "好看", "漂亮", "想你", "想见", "约会", "喜欢", "哈哈"]
    scores["flirt"] = min(9.0, sum(combined.count(k) for k in fl_kw) * 0.5)

    inv_kw = ["一起", "去", "来", "约", "见个面", "出来", "吃饭"]
    scores["invitation"] = min(9.0, sum(combined.count(k) for k in inv_kw) * 0.4)

    pos_kw = ["开心", "高兴", "不错", "好", "可以", "ok", "好的"]
    scores["emotion_positive"] = min(9.0, sum(combined.count(k) for k in pos_kw) * 0.2)

    perf_kw = ["嗯", "哦", "好的", "知道了", "行吧"]
    scores["perfunctory"] = min(9.0, sum(combined.count(k) for k in perf_kw) * 0.3)

    fb_kw = ["朋友", "兄弟", "哥们", "闺蜜", "同事"]
    scores["framing_boundary"] = min(9.0, sum(combined.count(k) for k in fb_kw) * 0.5)

    return scores


# ── 诊断维度（不对称筛选）──
DIAGNOSIS_DIMENSIONS = [
    {
        "name": "她主动提问_我不问",
        "her_high": ["question_asking"], "min_her": 4.0,
        "me_low": ["question_asking"], "max_me": 2.0,
    },
    {
        "name": "她暧昧_我冷淡",
        "her_high": ["flirt"], "min_her": 3.0,
        "me_low": ["flirt"], "max_me": 1.0,
    },
    {
        "name": "她自我分享_我不分享",
        "her_high": ["self_disclosure"], "min_her": 4.0,
        "me_low": ["self_disclosure"], "max_me": 2.0,
    },
    {
        "name": "她邀约_我不接",
        "her_high": ["invitation"], "min_her": 3.0,
        "me_low": ["invitation"], "max_me": 1.0,
    },
    {
        "name": "她负面_我正面",
        "her_high": ["emotion_negative"], "min_her": 3.0,
        "me_low": ["emotion_positive"], "max_me": 2.0,
    },
    {
        "name": "她边界化_我不反抗",
        "her_high": ["framing_boundary"], "min_her": 3.0,
        "me_low": ["flirt", "invitation"], "max_me": 1.0,
    },
    {
        "name": "她敷衍_我努力",
        "her_high": ["perfunctory"], "min_her": 3.0,
        "me_low": ["perfunctory"], "max_me": 1.0,
    },
    {
        "name": "双方暧昧",
        "her_high": ["flirt"], "min_her": 3.0,
        "me_high": ["flirt"], "min_me": 3.0,
    },
    {
        "name": "高信息_低情感",
        "her_high": ["information_exchange"], "min_her": 5.0,
        "her_low": ["emotion_positive", "emotion_negative", "flirt"], "max_her_emotion": 2.0,
    },
]


def match_diagnosis(her: dict[str, float], me: dict[str, float], dim: dict) -> bool:
    for lbl in dim.get("her_high", []):
        if her.get(lbl, 0) < dim["min_her"]:
            return False
    for lbl in dim.get("her_low", []):
        if her.get(lbl, 0) > dim.get("max_her_emotion", 5.0):
            return False
    if "me_low" in dim:
        for lbl in dim["me_low"]:
            if me.get(lbl, 0) > dim["max_me"]:
                return False
    if "me_high" in dim:
        for lbl in dim["me_high"]:
            if me.get(lbl, 0) < dim["min_me"]:
                return False
    return True


def select_diagnosis_bucket(
    samples: list[dict],
    ann_by_id: dict,
    used_ids: set[str],
    target: int = 250,
) -> list[dict]:
    """从 9 个差异维度中选取不对称案例。每个维度均分。"""
    per_dim = max(1, target // len(DIAGNOSIS_DIMENSIONS))
    candidates: dict[str, list[dict]] = defaultdict(list)

    for s in samples:
        sid = s["sample_id"]
        if sid in used_ids:
            continue
        ann = ann_by_id.get(sid)
        if not ann or not ann.get("labels"):
            continue
        her = ann["labels"]
        me = estimate_me_scores(s.get("messages", []))
        for dim in DIAGNOSIS_DIMENSIONS:
            if len(candidates[dim["name"]]) >= per_dim:
                continue
            if match_diagnosis(her, me, dim):
                candidates[dim["name"]].append({
                    "sample_id": sid,
                    "contact_wxid": s.get("contact_wxid", ""),
                    "messages": s["messages"],
                    "her_scores": her,
                    "dimension": dim["name"],
                })

    result = []
    for dim in DIAGNOSIS_DIMENSIONS:
        entries = candidates[dim["name"]]
        result.extend(entries)
        used_ids.update(e["sample_id"] for e in entries)
    return result


def select_symmetric_bucket(
    samples: list[dict],
    ann_by_id: dict,
    used_ids: set[str],
    target: int = 150,
) -> list[dict]:
    """选取双方行为相近的对称互动案例。

    条件：对话有适当深度, her 和 estimated-me 在情感类标签上差异小。
    """
    candidates = []
    for s in samples:
        sid = s["sample_id"]
        if sid in used_ids:
            continue
        ann = ann_by_id.get(sid)
        if not ann or not ann.get("labels"):
            continue
        her = ann["labels"]
        me = estimate_me_scores(s.get("messages", []))
        msgs = s.get("messages", [])
        turn_count = s.get("turn_count", len(msgs) // 2)
        if turn_count < 4:
            continue

        # 计算两侧差异：在情感和互动维度上
        compare_keys = ["emotion_positive", "emotion_negative", "flirt", "question_asking", "self_disclosure"]
        diffs = [abs(her.get(k, 0) - me.get(k, 0)) for k in compare_keys]
        avg_diff = sum(diffs) / len(diffs)

        # 双方都有一定参与度
        her_engagement = sum(her.get(k, 0) for k in compare_keys) / len(compare_keys)
        me_engagement = sum(me.get(k, 0) for k in compare_keys) / len(compare_keys)

        # 选择差异小 + 双方都有参与
        if avg_diff <= 2.0 and her_engagement >= 2.0 and me_engagement >= 1.5:
            candidates.append({
                "sample_id": sid,
                "contact_wxid": s.get("contact_wxid", ""),
                "messages": msgs,
                "her_scores": her,
                "symmetry_score": round(1.0 - avg_diff / 9.0, 3),
            })

    # 按对称度排序，取 target 条
    candidates.sort(key=lambda x: x["symmetry_score"], reverse=True)
    result = candidates[:target]
    used_ids.update(e["sample_id"] for e in result)
    return result


def select_random_bucket(
    samples: list[dict],
    ann_by_id: dict,
    used_ids: set[str],
    target: int = 100,
) -> list[dict]:
    """分层随机采样：按联系人 + her-score 活跃度分层。

    目标：覆盖尽量多的联系人，代表整体分布。
    """
    # 构建每个联系人的采样池
    contact_pool: dict[str, list[dict]] = defaultdict(list)
    for s in samples:
        sid = s["sample_id"]
        if sid in used_ids:
            continue
        ann = ann_by_id.get(sid)
        if not ann or not ann.get("labels"):
            continue
        cid = s.get("contact_wxid", "")
        contact_pool[cid].append({
            "sample_id": sid,
            "contact_wxid": cid,
            "messages": s["messages"],
            "her_scores": ann["labels"],
        })

    # 从每个联系人抽最多 2 条，避免单一联系人占比过高
    result = []
    all_contacts = list(contact_pool.keys())
    random.shuffle(all_contacts)

    for cid in all_contacts:
        if len(result) >= target:
            break
        pool = contact_pool[cid]
        random.shuffle(pool)
        take = min(2, len(pool), target - len(result))
        result.extend(pool[:take])

    # 如果还不够，补充采样
    if len(result) < target:
        remaining = []
        for s in samples:
            sid = s["sample_id"]
            if sid in used_ids:
                continue
            ann = ann_by_id.get(sid)
            if ann and ann.get("labels"):
                remaining.append({
                    "sample_id": sid,
                    "contact_wxid": s.get("contact_wxid", ""),
                    "messages": s["messages"],
                    "her_scores": ann["labels"],
                })
        random.shuffle(remaining)
        result.extend(remaining[:target - len(result)])

    used_ids.update(e["sample_id"] for e in result)
    return result


def pre_split_contacts(candidates: list[dict], held_out_ratio: float = 0.3) -> dict[str, str]:
    """按联系人切分为 train/held_out。返回 {contact_wxid: split}。"""
    contacts = sorted(set(c["contact_wxid"] for c in candidates))
    random.shuffle(contacts)
    n_held = max(1, int(len(contacts) * held_out_ratio))
    held_contacts = set(contacts[:n_held])
    return {c: "held_out" if c in held_contacts else "train" for c in contacts}


def main():
    if not SAMPLES_PATH.exists() or not ANNOTATIONS_PATH.exists():
        print(f"错误：训练数据不存在，请先运行 prepare_training_data.py")
        sys.exit(1)

    samples = load_jsonl(SAMPLES_PATH)
    annotations = load_jsonl(ANNOTATIONS_PATH)
    ann_by_id = {a["sample_id"]: a for a in annotations}

    print(f"样本: {len(samples)}, 标注: {len(annotations)}")
    used_ids: set[str] = set()

    # ── Bucket 1: 诊断不对称案例 ~250 ──
    diag = select_diagnosis_bucket(samples, ann_by_id, used_ids, target=250)
    print(f"\n[Bucket 1] 诊断不对称: {len(diag)} 条")
    dim_counts = Counter(e.get("dimension", "?") for e in diag)
    for dim, cnt in sorted(dim_counts.items()):
        print(f"    {dim:<20} {cnt}")

    # ── Bucket 2: 对称互动 ~150 ──
    sym = select_symmetric_bucket(samples, ann_by_id, used_ids, target=150)
    print(f"\n[Bucket 2] 对称互动: {len(sym)} 条")

    # ── Bucket 3: 随机分层 ~100 ──
    rnd = select_random_bucket(samples, ann_by_id, used_ids, target=100)
    print(f"\n[Bucket 3] 随机分层: {len(rnd)} 条")

    all_candidates = []

    for e in diag:
        all_candidates.append({
            "sample_id": e["sample_id"],
            "contact_wxid": e["contact_wxid"],
            "selection_bucket": "diagnosis",
            "selection_reason": e.get("dimension", "不对称"),
            "messages": e["messages"],
            "her_scores": e["her_scores"],
            "me_labels": None,
            "annotation_status": "pending",
        })

    for e in sym:
        all_candidates.append({
            "sample_id": e["sample_id"],
            "contact_wxid": e["contact_wxid"],
            "selection_bucket": "symmetric",
            "selection_reason": f"对称度={e.get('symmetry_score', 0):.2f}",
            "messages": e["messages"],
            "her_scores": e["her_scores"],
            "me_labels": None,
            "annotation_status": "pending",
        })

    for e in rnd:
        all_candidates.append({
            "sample_id": e["sample_id"],
            "contact_wxid": e["contact_wxid"],
            "selection_bucket": "random",
            "selection_reason": "分层随机",
            "messages": e["messages"],
            "her_scores": e["her_scores"],
            "me_labels": None,
            "annotation_status": "pending",
        })

    # ── 预切分联系人 ──
    split_map = pre_split_contacts(all_candidates, held_out_ratio=0.3)
    for c in all_candidates:
        c["split"] = split_map.get(c["contact_wxid"], "train")

    # 统计
    train_count = sum(1 for c in all_candidates if c["split"] == "train")
    held_count = sum(1 for c in all_candidates if c["split"] == "held_out")
    train_contacts = len(set(c["contact_wxid"] for c in all_candidates if c["split"] == "train"))
    held_contacts = len(set(c["contact_wxid"] for c in all_candidates if c["split"] == "held_out"))

    # ── 写入 ──
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        for c in all_candidates:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    total = len(all_candidates)
    print(f"\n{'=' * 50}")
    print(f"me_side_pilot_v1 已生成")
    print(f"{'=' * 50}")
    print(f"总计: {total} 条候选")
    print(f"  diagnosis_bucket:  {len(diag)}")
    print(f"  symmetric_bucket:  {len(sym)}")
    print(f"  random_bucket:     {len(rnd)}")
    print(f"联系人切分:")
    print(f"  train:     {train_count} 条 / {train_contacts} 人")
    print(f"  held_out:  {held_count} 条 / {held_contacts} 人")
    print(f"输出: {OUTPUT_PATH}")

    # 按 bucket 的分桶统计
    print(f"\n按 bucket 的 held_out 分布:")
    for bucket_name in ["diagnosis", "symmetric", "random"]:
        bucket = [c for c in all_candidates if c["selection_bucket"] == bucket_name]
        h = sum(1 for c in bucket if c["split"] == "held_out")
        print(f"  {bucket_name:<15} held_out={h}/{len(bucket)} ({h/len(bucket)*100:.0f}%)")

    print(f"\n开始标注:")
    print(f"  python ml/scripts/label_meside.py --count 5")
    print(f"  提交: python ml/scripts/label_meside.py --submit \"7|8|6|1|5|5|3|7|6|1\"")
    print(f"  进度: python ml/scripts/label_meside.py --progress")


if __name__ == "__main__":
    main()
