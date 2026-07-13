#!/usr/bin/env python3
"""me-side Δ 诊断 — 判断 B1′ 是否感知角色前缀变化且方向正确。

对同一批 held-out 样本，B1′ 分别以 target_role="her" 和 "me" 推理，
逐标签计算 Δ_pred = pred_her - pred_me 与 Δ_gold = her_gold - me_gold 的：

  - Spearman（方向排序一致性）
  - 方向一致率（sign(Δ_pred) == sign(Δ_gold)）
  - Δ MAE（差值绝对误差，越低越好）

以此区分三种情况：

  | 结果 | 含义 |
  |------|------|
  | Δ_pred ≈ 0 | 模型基本忽略角色前缀 |
  | Δ_pred 有变化，但与 Δ_gold 不相关 | 识别了 token 差异，但没学会角色切换 |
  | Δ_pred 与 Δ_gold 同方向 | 角色前缀有潜力，校准不足即可通过联合微调修复 |

用法（A100）:
  cd /home2/cme_code/lm/ml
  PY=/home2/cme_code/convert/python_env/bin/python3

  # 1. 先跑两次 evaluate（如果还没跑 her target）：
  $PY scripts/evaluate_meside_zero_shot.py \
    --model-dir models/role_aware_b1_prime \
    --candidates dataset/annotations/me_side_pilot_v1_candidates.jsonl \
    --annotations dataset/annotations/annotations_meside_000.jsonl \
    --split held_out --target-role her \
    --output /dev/null \
    --predictions models/role_aware_b1_prime/predictions_her.jsonl

  # 2. Δ 诊断
  $PY scripts/me_side_delta_diagnosis.py \
    --predictions-her models/role_aware_b1_prime/predictions_her.jsonl \
    --predictions-me models/role_aware_b1_prime/predictions_me.jsonl \
    --her-annotations dataset/training_annotations.jsonl \
    --me-annotations dataset/annotations/annotations_meside_000.jsonl \
    --output models/role_aware_b1_prime/me_side_delta_report.json
"""
from __future__ import annotations

import json
import sys
import argparse
import numpy as np
from pathlib import Path
from collections import defaultdict
from scipy.stats import spearmanr

LABELS = [
    "information_exchange", "opinion_expression", "emotion_positive",
    "emotion_negative", "flirt", "question_asking", "self_disclosure",
    "invitation", "framing_boundary", "perfunctory",
]


def load_predictions(path: Path) -> dict[str, dict]:
    """加载预测明细 JSONL，返回 {sample_id: {label: score}}。"""
    results = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            results[d["sample_id"]] = d["prediction"]
    return results


def load_annotations(path: Path, target: str | None = "me") -> dict[str, dict]:
    """加载标注文件，返回 {sample_id: {label: score}}。"""
    results = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            sid = d["sample_id"]
            if sid in results:
                continue  # 去重
            if target and d.get("target") != target:
                continue
            if d.get("discard"):
                continue
            labels = d.get("labels", {})
            if all(k in labels for k in LABELS):
                results[sid] = {k: float(labels[k]) for k in LABELS}
    return results


def main():
    parser = argparse.ArgumentParser(description="me-side Δ 诊断")
    parser.add_argument("--predictions-her", required=True,
                        help="B1' target_role=her 预测明细 JSONL")
    parser.add_argument("--predictions-me", required=True,
                        help="B1' target_role=me 预测明细 JSONL")
    parser.add_argument("--her-annotations", required=True,
                        help="her-side 标注文件（training_annotations.jsonl）")
    parser.add_argument("--me-annotations", required=True,
                        help="me-side 标注文件（annotations_meside_000.jsonl）")
    parser.add_argument("--output", required=True,
                        help="检测报告输出路径")
    args = parser.parse_args()

    # ── 加载数据 ──
    preds_her = load_predictions(Path(args.predictions_her))
    preds_me = load_predictions(Path(args.predictions_me))
    gold_her = load_annotations(Path(args.her_annotations), target=None)  # her 标注无 target 字段
    gold_me = load_annotations(Path(args.me_annotations), target="me")

    # ── 取交集 ──
    common = set(preds_her) & set(preds_me) & set(gold_her) & set(gold_me)
    print(f"预测 her: {len(preds_her)} 条")
    print(f"预测 me:  {len(preds_me)} 条")
    print(f"标注 her:  {len(gold_her)} 条")
    print(f"标注 me:   {len(gold_me)} 条")
    print(f"交集:      {len(common)} 条")
    assert len(common) > 0, "无交集样本，请检查 sample_id 是否一致"

    # ── 逐标签 Δ 分析 ──
    per_label = {}
    all_delta_preds = []
    all_delta_golds = []

    for label in LABELS:
        pred_h = np.array([preds_her[sid][label] for sid in common])
        pred_m = np.array([preds_me[sid][label] for sid in common])
        gold_h = np.array([gold_her[sid][label] for sid in common])
        gold_m = np.array([gold_me[sid][label] for sid in common])

        delta_pred = pred_h - pred_m
        delta_gold = gold_h - gold_m

        # Spearman
        try:
            sp, _ = spearmanr(delta_pred, delta_gold)
        except Exception:
            sp = 0.0
        sp = float(sp)

        # 方向一致率
        sign_pred = np.sign(delta_pred)
        sign_gold = np.sign(delta_gold)
        # 0 值处理：如果 gold 差为 0，预测差也为 0 才算一致
        agree = np.sum(sign_pred == sign_gold)
        # 排除 both-zero 的情况（没有分歧时双方一致是 trivial 的）
        nonzero_mask = sign_gold != 0
        nonzero_agree = np.sum((sign_pred == sign_gold) & nonzero_mask)
        nonzero_total = np.sum(nonzero_mask)
        nonzero_agree_rate = nonzero_agree / nonzero_total if nonzero_total > 0 else 0.0

        # Δ MAE（预测的差值 vs 真实的差值）
        delta_mae = float(np.mean(np.abs(delta_pred - delta_gold)))

        # 均值差异
        mean_delta_pred = float(np.mean(delta_pred))
        mean_delta_gold = float(np.mean(delta_gold))

        per_label[label] = {
            "n": len(common),
            "delta_pred_mean": round(mean_delta_pred, 3),
            "delta_gold_mean": round(mean_delta_gold, 3),
            "spearman": round(sp, 4),
            "direction_agreement_rate": round(float(agree / len(common)), 3),
            "nonzero_direction_agreement_rate": round(nonzero_agree_rate, 3),
            "delta_mae": round(delta_mae, 3),
            "note": _delta_note(mean_delta_pred, mean_delta_gold, sp),
        }

        all_delta_preds.append(delta_pred)
        all_delta_golds.append(delta_gold)

    # ── 全局汇总 ──
    all_dp = np.concatenate(all_delta_preds)
    all_dg = np.concatenate(all_delta_golds)
    try:
        sp_all, _ = spearmanr(all_dp, all_dg)
    except Exception:
        sp_all = 0.0

    overall = {
        "samples": len(common),
        "labels": len(LABELS),
        "delta_spearman_overall": round(float(sp_all), 4),
        "delta_mae_overall": round(float(np.mean(np.abs(all_dp - all_dg))), 3),
        "delta_direction_agreement_overall": round(float(np.mean(np.sign(all_dp) == np.sign(all_dg))), 3),
        "mean_abs_delta_pred": round(float(np.mean(np.abs(all_dp))), 3),
        "mean_abs_delta_gold": round(float(np.mean(np.abs(all_dg))), 3),
    }

    # ── 结论 ──
    mean_abs_dp = overall["mean_abs_delta_pred"]
    sp_global = overall["delta_spearman_overall"]
    if mean_abs_dp < 0.05 * 9.0:  # Δ_pred 平均不到 0.45
        conclusion = "B1 基本忽略角色前缀（Δ_pred ≈ 0）"
    elif sp_global < 0.15:
        conclusion = "B1 感知了 token 变化，但 Δ_pred 与 Δ_gold 几乎无关（尚未学会角色切换）"
    elif sp_global >= 0.15:
        conclusion = "B1 的 Δ_pred 与 Δ_gold 同方向，角色前缀有潜力，校准不足可联合微调修复"
    else:
        conclusion = "不确定，需人工检查"

    report = {
        "diagnosis": "me_side_delta",
        "model": "B1'",
        "samples": len(common),
        "overall": overall,
        "per_label": per_label,
        "conclusion": conclusion,
    }

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # ── 控制台 ──
    print(f"\n{'='*60}")
    print(f"  B1' 角色切换 Δ 诊断")
    print(f"  {len(common)} 条 held-out 样本")
    print(f"{'='*60}")
    print(f"\n  全局:")
    print(f"    Δ Spearman:       {overall['delta_spearman_overall']:+.4f}")
    print(f"    Δ MAE:             {overall['delta_mae_overall']:.3f}")
    print(f"    方向一致率:        {overall['delta_direction_agreement_overall']:.1%}")
    print(f"    平均 |Δ_pred|:     {overall['mean_abs_delta_pred']:.3f}")
    print(f"    平均 |Δ_gold|:     {overall['mean_abs_delta_gold']:.3f}")

    print(f"\n  逐标签:")
    print(f"  {'标签':>25} | {'Δ_pred均值':>9} | {'Δ_gold均值':>9} | {'Spearman':>8} | {'方向一致率':>8} | {'Δ MAE':>6}")
    print(f"  {'-'*25}-+-{'-'*9}-+-{'-'*9}-+-{'-'*8}-+-{'-'*8}-+-{'-'*6}")
    for label in LABELS:
        p = per_label[label]
        print(f"  {label:>25} | {p['delta_pred_mean']:>+8.2f} | {p['delta_gold_mean']:>+8.2f} | {p['spearman']:>+7.3f} | {p['direction_agreement_rate']:>7.1%} | {p['delta_mae']:>5.2f}")

    print(f"\n  结论: {conclusion}")
    print(f"  报告: {args.output}")
    print(f"{'='*60}")


def _delta_note(mean_dp: float, mean_dg: float, sp: float) -> str:
    """生成单标签简短判断。"""
    parts = []
    if abs(mean_dp) < 0.15:
        parts.append("Δ_pred≈0")
    elif mean_dp * mean_dg > 0:
        parts.append(f"方向一致({'偏her' if mean_dp > 0 else '偏me'})")
    else:
        parts.append("方向相反")
    if sp > 0.3:
        parts.append("排序相关")
    elif sp > 0.1:
        parts.append("弱相关")
    else:
        parts.append("不相关")
    return " | ".join(parts)


if __name__ == "__main__":
    main()
