#!/usr/bin/env python3
"""对比两个实验的评估报告。

校验两报告的划分一致性，避免测试集不同的误比较。

用法:
  python ml/scripts/compare_experiments.py \
      --baseline ml/models/role_aware_b1/eval_report.json \
      --experiment ml/models/role_aware_b1/eval_report.json --prefix B1

  python ml/scripts/compare_experiments.py \
      --baseline ml/models/baseline_b0_prime/eval_report.json \
      --experiment ml/models/role_aware_b1_prime/eval_report.json

输出 per-label 对比表（R² / MAE / Spearman），标记变化方向。
"""
from __future__ import annotations

import json
import sys
import argparse
from pathlib import Path

LABELS = [
    "information_exchange", "opinion_expression", "emotion_positive",
    "emotion_negative", "flirt", "question_asking", "self_disclosure",
    "invitation", "framing_boundary", "perfunctory",
]


def load_report(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _fail(msg: str):
    print(f"错误: {msg}")
    sys.exit(1)


def validate_reports(base: dict, exp: dict, base_path: Path, exp_path: Path):
    """校验两份报告是否可比较。不一致则 exit(1)。"""
    # 1. 检查必要顶层字段
    for name, r in [("基线", base), ("实验", exp)]:
        for field in ["overall", "per_label", "config"]:
            if field not in r:
                _fail(f"{name} 报告缺少 '{field}' 字段")

    # 2. 检查整体指标完整性
    overall_keys = {"R2", "MAE_score", "RMSE_score", "Contact_MAE_score"}
    base_ok = overall_keys.issubset(base["overall"].keys())
    exp_ok = overall_keys.issubset(exp["overall"].keys())
    if not base_ok:
        missing = overall_keys - base["overall"].keys()
        _fail(f"基线报告整体指标缺失 {missing}。请用新版 train_macbert.py 重新评估。")
    if not exp_ok:
        missing = overall_keys - exp["overall"].keys()
        _fail(f"实验报告整体指标缺失 {missing}")

    # 3. 检查每标签指标完整性
    for name, r in [("基线", base), ("实验", exp)]:
        per_label_keys = {"R2", "MAE_score", "Spearman"}
        for lbl in LABELS:
            lp = r.get("per_label", {}).get(lbl, {})
            missing = per_label_keys - lp.keys()
            if missing:
                _fail(f"{name} {lbl} 缺失 {missing}")

    # 4. SHA256 校验——划分和数据版本一致
    bm = base.get("manifest", {})
    em = exp.get("manifest", {})

    if not bm or not em:
        _fail("报告缺少 manifest 字段（含 SHA256）。请用新版 train_macbert.py 重跑评估。")

    sha_fields = [
        ("split_manifest_sha256", "split_manifest 文件"),
        ("train_contacts_sha256", "训练联系人划分"),
        ("val_contacts_sha256", "验证联系人划分"),
        ("test_contacts_sha256", "测试联系人划分"),
        ("dataset_sha256", "数据集版本"),
        ("dataset_sample_count", "数据集样本数"),
    ]
    for key, label in sha_fields:
        bv = bm.get(key)
        ev = em.get(key)
        if not bv or not ev:
            _fail(f"{label} 的 SHA256 为空")
        if bv != ev:
            print(f"  ✗ {label} 不一致")
            print(f"    基线: {bv}")
            print(f"    实验: {ev}")
            _fail("两份报告的测试基础不一致，无法比较。请用相同 --split-manifest 和数据版本重跑。")

    # 5. 兼容性检查
    base_schema = bm.get("input_schema", "roleless_v0")
    exp_schema = em.get("input_schema", "roleless_v0")
    print(f"  input_schema: 基线={base_schema}, 实验={exp_schema}")
    if base_schema != exp_schema:
        print(f"  ⚠ input_schema 不同（{base_schema} vs {exp_schema}），确认这是有意对照？")
    base_role = bm.get("role_prefix", False)
    exp_role = em.get("role_prefix", False)
    if base_role is not None and exp_role is not None and base_role == exp_role:
        print(f"  ⚠ 两实验 role_prefix 相同（均为 {base_role}），确认这是有意对照？")

    print("  ✓ 划分和数据版本一致，可比较\n")
    return True


def main():
    parser = argparse.ArgumentParser(description="对比两个实验的评估报告")
    parser.add_argument("--baseline", required=True, help="基线报告路径")
    parser.add_argument("--experiment", required=True, help="实验报告路径")
    parser.add_argument("--prefix", default=None, help="实验标签前缀（如 B1），用于输出")
    parser.add_argument("--format", choices=["table", "json"], default="table")
    args = parser.parse_args()

    baseline_path = Path(args.baseline)
    experiment_path = Path(args.experiment)

    if not baseline_path.exists():
        _fail(f"基线报告不存在 {baseline_path}")
    if not experiment_path.exists():
        _fail(f"实验报告不存在 {experiment_path}")

    base = load_report(baseline_path)
    exp = load_report(experiment_path)

    same_manifest = validate_reports(base, exp, baseline_path, experiment_path)

    label = exp.get("label", "all")
    overall_base = base.get("overall", {})
    overall_exp = exp.get("overall", {})

    # ── per-label 对比 ──
    rows = []
    for lbl in LABELS:
        bp = base.get("per_label", {}).get(lbl, {})
        ep = exp.get("per_label", {}).get(lbl, {})

        r2_base = bp.get("R2", 0)
        r2_exp = ep.get("R2", 0)
        r2_delta = r2_exp - r2_base

        mae_base = bp.get("MAE_score", 0)
        mae_exp = ep.get("MAE_score", 0)
        mae_delta = mae_exp - mae_base

        sp_base = bp.get("Spearman", 0)
        sp_exp = ep.get("Spearman", 0)
        sp_delta = sp_exp - sp_base

        cm_base = bp.get("Contact_MAE_score", None)
        cm_exp = ep.get("Contact_MAE_score", None)

        rows.append({
            "label": lbl,
            "R2_base": r2_base, "R2_exp": r2_exp, "R2_delta": r2_delta,
            "MAE_base": mae_base, "MAE_exp": mae_exp, "MAE_delta": mae_delta,
            "Spearman_base": sp_base, "Spearman_exp": sp_exp, "Spearman_delta": sp_delta,
            "ContactMAE_base": cm_base,
            "ContactMAE_exp": cm_exp,
        })

    if args.format == "json":
        print(json.dumps({
            "baseline": str(baseline_path),
            "experiment": str(experiment_path),
            "same_manifest": same_manifest,
            "label": label,
            "overall": {
                "R2_base": overall_base.get("R2", 0),
                "R2_exp": overall_exp.get("R2", 0),
                "R2_delta": overall_exp.get("R2", 0) - overall_base.get("R2", 0),
                "MAE_base": overall_base.get("MAE_score", 0),
                "MAE_exp": overall_exp.get("MAE_score", 0),
                "MAE_delta": overall_exp.get("MAE_score", 0) - overall_base.get("MAE_score", 0),
            },
            "per_label": rows,
            "same_manifest": same_manifest,
        }, ensure_ascii=False, indent=2))
        return

    exp_name = args.prefix or experiment_path.parent.name
    base_name = baseline_path.parent.name

    # ── 表格输出 ──
    title = f"{base_name} vs {exp_name}"
    print(f"\n{'=' * 90}")
    print(f"{title:^90}")
    print(f"{'=' * 90}")

    header = (
        f"{'标签':<24} {'R² 基线':>8} {'R² 实验':>8} {'Δ':>7} | "
        f"{'MAE 基线':>8} {'MAE 实验':>8} {'Δ':>7} | "
        f"{'Sp 基线':>8} {'Sp 实验':>8} {'Δ':>7}"
    )
    print(header)
    print("-" * 90)

    for r in rows:
        arrow_r2 = "▲" if r["R2_delta"] > 0.01 else ("▼" if r["R2_delta"] < -0.01 else "─")
        arrow_mae = "▼" if r["MAE_delta"] < -0.05 else ("▲" if r["MAE_delta"] > 0.05 else "─")
        arrow_sp = "▲" if r["Spearman_delta"] > 0.01 else ("▼" if r["Spearman_delta"] < -0.01 else "─")
        print(
            f"{r['label']:<24} "
            f"{r['R2_base']:>+8.4f} {r['R2_exp']:>+8.4f} {arrow_r2} {r['R2_delta']:>+5.4f} | "
            f"{r['MAE_base']:>8.2f} {r['MAE_exp']:>8.2f} {arrow_mae} {r['MAE_delta']:>+5.2f} | "
            f"{r['Spearman_base']:>+8.4f} {r['Spearman_exp']:>+8.4f} {arrow_sp} {r['Spearman_delta']:>+5.4f}"
        )

    r2_bo = overall_base.get("R2", 0)
    r2_eo = overall_exp.get("R2", 0)
    mae_bo = overall_base.get("MAE_score", 0)
    mae_eo = overall_exp.get("MAE_score", 0)
    cm_bo = overall_base.get("Contact_MAE_score", None)
    cm_eo = overall_exp.get("Contact_MAE_score", None)

    print("-" * 90)
    print(
        f"{'Overall':<24} "
        f"{r2_bo:>+8.4f} {r2_eo:>+8.4f} {'▲' if r2_eo - r2_bo > 0.01 else ('▼' if r2_eo - r2_bo < -0.01 else '─')} {r2_eo - r2_bo:>+5.4f} | "
        f"{mae_bo:>8.2f} {mae_eo:>8.2f} {'▼' if mae_eo - mae_bo < -0.05 else ('▲' if mae_eo - mae_bo > 0.05 else '─')} {mae_eo - mae_bo:>+5.2f} | "
    )
    if cm_bo is not None and cm_eo is not None:
        cm_delta = cm_eo - cm_bo
        print(f"\n{'Contact-Macro MAE':<24} {cm_bo:>8.2f} {cm_eo:>8.2f}  {'▼' if cm_delta < -0.05 else ('▲' if cm_delta > 0.05 else '─')} {cm_delta:>+5.2f}")

    if rows[0]["ContactMAE_base"] is not None and rows[0]["ContactMAE_exp"] is not None:
        print("\nPer-label Contact-Macro MAE (0-9):")
        for r in rows:
            cm_delta = r["ContactMAE_exp"] - r["ContactMAE_base"]
            arrow = "▼" if cm_delta < -0.05 else ("▲" if cm_delta > 0.05 else "─")
            print(f"  {r['label']:<22} {r['ContactMAE_base']:>6.2f} → {r['ContactMAE_exp']:>6.2f}  {arrow} {cm_delta:>+5.2f}")

    print("")


if __name__ == "__main__":
    main()
