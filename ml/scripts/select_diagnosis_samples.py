#!/usr/bin/env python3
"""角色诊断集选样工具 — 从已有数据中挑选双方行为差异明显的窗口。

用途：
  为 B1 模型的 role-prefix 效果做人工抽检。挑出 "她说A、我说B" 的边界案例，
  手工判断 B1 输出是否比 B0 更合理。

输出：
  - 按差异维度分组的候选窗口列表（每窗口 20 条消息）
  - 推荐抽检 100-200 条

用法：
  python ml/scripts/select_diagnosis_samples.py \
      --samples data/ml_dataset/training_samples.jsonl \
      --annotations data/ml_dataset/training_annotations.jsonl \
      --output data/ml_dataset/diagnosis_candidates.jsonl \
      --max-per-group 30
"""
from __future__ import annotations

import json
import argparse
import random
from pathlib import Path
from collections import defaultdict

LABELS = [
    "information_exchange", "opinion_expression", "emotion_positive",
    "emotion_negative", "flirt", "question_asking", "self_disclosure",
    "invitation", "framing_boundary", "perfunctory",
]

# ── 诊断维度定义 ──
# 每个维度：名称、她侧高标签、我侧低标签、描述
DIAGNOSIS_DIMENSIONS = [
    {
        "name": "她主动提问_我不问",
        "her_high": ["question_asking"],
        "me_low": ["question_asking"],
        "min_her": 4.0,
        "max_me": 2.0,
        "description": "她主动提问但我几乎不问，对话驱动力在她",
    },
    {
        "name": "她暧昧_我冷淡",
        "her_high": ["flirt"],
        "me_low": ["flirt"],
        "min_her": 3.0,
        "max_me": 1.0,
        "description": "她释放暧昧信号但我不接，可能错过升温窗口",
    },
    {
        "name": "她自我分享_我不分享",
        "her_high": ["self_disclosure"],
        "me_low": ["self_disclosure"],
        "min_her": 4.0,
        "max_me": 2.0,
        "description": "她主动分享个人信息但我不对等回应",
    },
    {
        "name": "她邀约_我不接",
        "her_high": ["invitation"],
        "me_low": ["invitation"],
        "min_her": 3.0,
        "max_me": 1.0,
        "description": "她发出邀约信号但我不积极回应",
    },
    {
        "name": "她负面_我正面",
        "her_high": ["emotion_negative"],
        "me_low": ["emotion_positive"],
        "min_her": 3.0,
        "max_me": 2.0,
        "description": "她表达负面情绪时我反应偏正面（错位）",
    },
    {
        "name": "她边界化_我不反抗",
        "her_high": ["framing_boundary"],
        "me_low": ["flirt", "invitation"],
        "min_her": 3.0,
        "max_me": 1.0,
        "description": "她用朋友/兄弟框架但我没拉回来",
    },
    {
        "name": "她敷衍_我努力",
        "her_high": ["perfunctory"],
        "me_low": ["perfunctory"],
        "min_her": 3.0,
        "max_me": 1.0,
        "description": "她敷衍回应但我还在努力推进对话",
    },
    {
        "name": "双方暧昧",
        "her_high": ["flirt"],
        "me_high": ["flirt"],
        "min_her": 3.0,
        "min_me": 3.0,
        "description": "双方都有暧昧信号，看角色前缀是否让B1更准确",
    },
    {
        "name": "高信息_低情感",
        "her_high": ["information_exchange"],
        "her_low": ["emotion_positive", "emotion_negative", "flirt"],
        "min_her": 5.0,
        "max_her_emotion": 2.0,
        "description": "纯信息交换无情感色彩，角色前缀影响最小（负对照）",
    },
]

# ── Me-side 标签（仅存在于样本 messages 中，需从消息双方提取）──


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _estimate_me_scores(messages: list[dict]) -> dict[str, float]:
    """从消息文本粗略估计我的侧行为分数（基于关键词）。

    这是一个快速的规则估计，用于筛选候选窗口。
    正式评分需要 MacBERT 模型。
    """
    me_texts = [m["content"] for m in messages if m.get("role") == "me" or not m.get("is_mine", False)]
    combined = "\n".join(me_texts).lower()

    scores = {}

    # question_asking
    q_words = sum(1 for t in me_texts if "?" in t or "？" in t or "吗" in t or "呢" in t)
    scores["question_asking"] = min(9.0, q_words * 1.5)

    # self_disclosure
    sd_keywords = ["我", "我的", "我家", "我觉得", "我想", "我喜欢", "我住", "我工作"]
    sd_count = sum(combined.count(kw) for kw in sd_keywords)
    scores["self_disclosure"] = min(9.0, sd_count * 0.3)

    # flirt
    flirt_keywords = ["可爱", "好看", "漂亮", "想你", "想见", "约会", "喜欢", "哈哈"]
    flirt_count = sum(combined.count(kw) for kw in flirt_keywords)
    scores["flirt"] = min(9.0, flirt_count * 0.5)

    # invitation
    inv_keywords = ["一起", "去", "来", "约", "见个面", "出来", "吃饭"]
    inv_count = sum(combined.count(kw) for kw in inv_keywords)
    scores["invitation"] = min(9.0, inv_count * 0.4)

    # emotion_positive
    pos_keywords = ["开心", "高兴", "不错", "好", "可以", "ok", "好的"]
    pos_count = sum(combined.count(kw) for kw in pos_keywords)
    scores["emotion_positive"] = min(9.0, pos_count * 0.2)

    # perfunctory
    perf_keywords = ["嗯", "哦", "好的", "知道了", "行吧"]
    perf_count = sum(combined.count(kw) for kw in perf_keywords)
    scores["perfunctory"] = min(9.0, perf_count * 0.3)

    # framing_boundary
    fb_keywords = ["朋友", "兄弟", "哥们", "闺蜜", "同事"]
    fb_count = sum(combined.count(kw) for kw in fb_keywords)
    scores["framing_boundary"] = min(9.0, fb_count * 0.5)

    return scores


def match_dimension(
    her_scores: dict[str, float],
    me_scores: dict[str, float],
    dim: dict,
) -> bool:
    """判断某对话窗口是否符合诊断维度的筛选条件。"""
    # 她侧高标签检查
    for label in dim.get("her_high", []):
        if her_scores.get(label, 0) < dim.get("min_her", 3.0):
            return False

    # 她侧低标签检查
    for label in dim.get("her_low", []):
        if her_scores.get(label, 0) > dim.get("max_her_emotion", 5.0):
            return False

    # 我侧高标签检查（维度要求我也有某种行为）
    if "me_high" in dim:
        for label in dim["me_high"]:
            if me_scores.get(label, 0) < dim.get("min_me", 3.0):
                return False

    # 我侧低标签检查
    if "me_low" in dim:
        for label in dim["me_low"]:
            if me_scores.get(label, 0) > dim.get("max_me", 2.0):
                return False

    return True


def main():
    parser = argparse.ArgumentParser(description="角色诊断集选样")
    parser.add_argument("--samples", default="data/ml_dataset/training_samples.jsonl")
    parser.add_argument("--annotations", default="data/ml_dataset/training_annotations.jsonl")
    parser.add_argument("--output", default="data/ml_dataset/diagnosis_candidates.jsonl")
    parser.add_argument("--max-per-group", type=int, default=30,
                        help="每组最多选多少个")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--model-scores", default=None,
                        help="可选：模型预测分数 JSONL（含 me_scores 字段），"
                             "代替规则估计")
    args = parser.parse_args()

    random.seed(args.seed)

    samples_path = Path(args.samples)
    annotations_path = Path(args.annotations)
    output_path = Path(args.output)

    if not samples_path.exists():
        print(f"错误：样本文件不存在 {samples_path}")
        return
    if not annotations_path.exists():
        print(f"错误：标注文件不存在 {annotations_path}")
        return

    samples = load_jsonl(samples_path)
    annotations = load_jsonl(annotations_path)
    ann_by_id = {a["sample_id"]: a for a in annotations}

    # 加载模型预测分数（如已存在）
    model_scores = {}
    if args.model_scores:
        for entry in load_jsonl(Path(args.model_scores)):
            model_scores[entry["sample_id"]] = entry

    print(f"样本: {len(samples)}, 标注: {len(annotations)}")
    print(f"模型预测: {'有 ' + str(len(model_scores)) if model_scores else '无（使用规则估计）'}")

    # 按维度分组选样
    candidates: dict[str, list[dict]] = defaultdict(list)

    for s in samples:
        sid = s["sample_id"]
        ann = ann_by_id.get(sid)
        if not ann:
            continue

        her_scores = ann.get("labels", {})
        if not her_scores:
            continue

        messages = s.get("messages", [])
        if not messages:
            continue

        # 我侧分数：优先模型预测，其次规则估计
        if sid in model_scores:
            me_scores = model_scores[sid].get("me_scores", {})
        else:
            me_scores = _estimate_me_scores(messages)

        for dim in DIAGNOSIS_DIMENSIONS:
            if len(candidates[dim["name"]]) >= args.max_per_group:
                continue
            if match_dimension(her_scores, me_scores, dim):
                candidates[dim["name"]].append({
                    "sample_id": sid,
                    "contact_wxid": s.get("contact_wxid", ""),
                    "dimension": dim["name"],
                    "her_scores": {k: round(v, 1) for k, v in her_scores.items()
                                   if k in dim.get("her_high", []) + dim.get("her_low", [])},
                    "me_scores_estimated": {k: round(v, 1) for k, v in me_scores.items()
                                            if k in dim.get("me_low", []) + dim.get("me_high", [])},
                    "messages": messages,
                    "turn_count": s.get("turn_count", len(messages) // 2),
                })

    # 输出
    total = 0
    with open(output_path, "w", encoding="utf-8") as f:
        for dim_name in sorted(candidates):
            entries = candidates[dim_name]
            for e in entries:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
            total += len(entries)

    print(f"\n诊断集已保存: {output_path} ({total} 条)")
    print(f"\n各维度分布:")
    for dim in DIAGNOSIS_DIMENSIONS:
        count = len(candidates[dim["name"]])
        bar = "█" * min(30, count) + "░" * max(0, 30 - min(30, count))
        print(f"  {dim['name']:<20} {count:>4}  {bar}")
        if count > 0:
            print(f"    {dim['description']}")
    print(f"\n建议抽检量: min(200, {total}) 条")
    print("查看方式: python -X utf8 -c \"")
    print("import json")
    print("with open('data/ml_dataset/diagnosis_candidates.jsonl') as f:")
    print("    for i, line in enumerate(f):")
    print("        if i >= 10: break")
    print("        d = json.loads(line)")
    print('        print(d[\'sample_id\'], d[\'dimension\'])')
    print('"')


if __name__ == "__main__":
    main()
