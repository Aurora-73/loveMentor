"""Analyze consistency between rule-based and embedding-based classifiers.

This gives us a rough estimate of how well the two methods agree,
without needing manual annotations.

If they agree well → both are capturing similar signals
If they disagree a lot → at least one is noisy, need human adjudication
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evaluation.evaluate import cohens_kappa, binary_metrics  # noqa: E402

LABELS = [
    "question_asking", "self_disclosure", "emotional_expression",
    "initiative_response", "flirt", "intimacy",
    "cold_conflict", "perfunctory", "investment", "willingness",
]


def load_jsonl(path: Path) -> dict[str, dict]:
    items = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                d = json.loads(line)
                items[d["sample_id"]] = d
    return items


def main():
    project_root = Path(__file__).resolve().parents[2]
    rule_path = project_root / "data" / "ml_outputs" / "baseline_results.jsonl"
    emb_path = project_root / "data" / "ml_outputs" / "embedding_results.jsonl"

    rule = load_jsonl(rule_path)
    emb = load_jsonl(emb_path)

    common = set(rule.keys()) & set(emb.keys())
    print(f"Common samples: {len(common)}")
    print()
    print("=" * 70)
    print("Rule vs Embedding: Consistency Analysis")
    print("(rule is treated as 'gold' for this comparison)")
    print("=" * 70)
    print(f"{'Label':25s} {'Rule+':>6s} {'Emb+':>6s} {'Acc':>6s} {'Kappa':>7s} {'F1':>6s}")
    print("-" * 70)

    per_label = {}
    for label in LABELS:
        y_rule = [bool(rule[sid]["labels"].get(label, False)) for sid in common]
        y_emb = [bool(emb[sid]["labels"].get(label, False)) for sid in common]
        metrics = binary_metrics(y_rule, y_emb)
        kappa = cohens_kappa(y_rule, y_emb)

        rule_pos = sum(y_rule)
        emb_pos = sum(y_emb)
        per_label[label] = {**metrics, "kappa": kappa}

        print(f"{label:25s} {rule_pos:6d} {emb_pos:6d} {metrics['accuracy']:6.3f} "
              f"{kappa:7.3f} {metrics['f1']:6.3f}")

    print("-" * 70)

    # Macro averages
    avg_acc = sum(m["accuracy"] for m in per_label.values()) / len(per_label)
    avg_kappa = sum(m["kappa"] for m in per_label.values()) / len(per_label)
    avg_f1 = sum(m["f1"] for m in per_label.values()) / len(per_label)
    print(f"{'MACRO AVG':25s} {'':>6s} {'':>6s} {avg_acc:6.3f} {avg_kappa:7.3f} {avg_f1:6.3f}")

    print()
    print("Interpretation:")
    print("  kappa < 0.2 → poor agreement, methods capture very different things")
    print("  kappa 0.2-0.4 → fair agreement")
    print("  kappa 0.4-0.6 → moderate agreement")
    print("  kappa 0.6-0.8 → substantial agreement")
    print("  kappa > 0.8 → almost perfect agreement")
    print()

    # Disagreement analysis: where do they differ most?
    print("=" * 70)
    print("Top disagreement samples (differ on 4+ labels)")
    print("=" * 70)
    disagreements = []
    for sid in common:
        diff = sum(
            1 for label in LABELS
            if rule[sid]["labels"].get(label, False) != emb[sid]["labels"].get(label, False)
        )
        if diff >= 4:
            disagreements.append((sid, diff, rule[sid].get("contact_remark", "?")))

    disagreements.sort(key=lambda x: -x[1])
    for sid, diff, contact in disagreements[:10]:
        print(f"  {sid} ({contact}): differ on {diff}/{len(LABELS)} labels")

    print()
    print(f"Total samples with >=4 label disagreements: {len(disagreements)}")

    # Save full analysis
    report_path = Path(__file__).parent.parent / "reports" / "rule_vs_embedding_consistency.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# 规则 vs Embedding 一致性分析\n\n")
        f.write(f"> 样本数: {len(common)}\n\n")
        f.write("| 标签 | 规则正例 | Emb正例 | 准确率 | Kappa | F1 |\n")
        f.write("|------|---------|---------|-------|-------|-----|\n")
        for label in LABELS:
            m = per_label[label]
            rp = sum(1 for sid in common if rule[sid]["labels"].get(label, False))
            ep = sum(1 for sid in common if emb[sid]["labels"].get(label, False))
            f.write(f"| {label} | {rp} | {ep} | {m['accuracy']:.3f} | {m['kappa']:.3f} | {m['f1']:.3f} |\n")
        f.write(f"| **平均** | - | - | **{avg_acc:.3f}** | **{avg_kappa:.3f}** | **{avg_f1:.3f}** |\n")

    print(f"\nFull report saved to: {report_path}")


if __name__ == "__main__":
    main()
