"""Annotation evaluation tools: kappa, precision, recall, F1.

Usage:
    1. Annotate the template (fill in [ ] with 0/1)
    2. Save annotations as a JSONL file with format:
       {"sample_id": "s_000001", "labels": {"flirt": true, ...}}
    3. Run: python evaluation/evaluate.py --pred predictions.jsonl --gold annotations.jsonl
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
import argparse

LABELS = [
    "information_exchange",
    "opinion_expression",
    "emotion_positive",
    "emotion_negative",
    "flirt",
    "question_asking",
    "self_disclosure",
    "invitation",
    "framing_boundary",
    "perfunctory",
]


# ---------------------------------------------------------------------------
# Kappa calculation (Cohen's kappa for binary labels)
# ---------------------------------------------------------------------------

def cohens_kappa(y1: list[bool], y2: list[bool]) -> float:
    """Compute Cohen's kappa between two binary annotators.

    Returns kappa value in [-1, 1].
    """
    assert len(y1) == len(y2)
    n = len(y1)
    if n == 0:
        return 0.0

    # Observed agreement
    agree = sum(1 for a, b in zip(y1, y2) if a == b)
    po = agree / n

    # Expected agreement by chance
    p1_pos = sum(1 for v in y1 if v) / n
    p2_pos = sum(1 for v in y2 if v) / n
    pe = p1_pos * p2_pos + (1 - p1_pos) * (1 - p2_pos)

    if pe >= 1.0:
        return 0.0
    return (po - pe) / (1 - pe)


# ---------------------------------------------------------------------------
# Per-label metrics
# ---------------------------------------------------------------------------

def binary_metrics(y_true: list[bool], y_pred: list[bool]) -> dict[str, float]:
    """Compute precision, recall, F1, accuracy for a single binary label."""
    tp = sum(1 for t, p in zip(y_true, y_pred) if t and p)
    fp = sum(1 for t, p in zip(y_true, y_pred) if not t and p)
    fn = sum(1 for t, p in zip(y_true, y_pred) if t and not p)
    tn = sum(1 for t, p in zip(y_true, y_pred) if not t and not p)

    total = len(y_true)
    accuracy = (tp + tn) / max(total, 1)
    precision = tp / max(tp + fp, 1)
    recall = tp / max(tp + fn, 1)
    f1 = 2 * precision * recall / max(precision + recall, 1e-8)

    return {
        "accuracy": round(accuracy, 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "support_pos": tp + fn,
        "support_neg": tn + fp,
    }


# ---------------------------------------------------------------------------
# Full evaluation
# ---------------------------------------------------------------------------

def evaluate_predictions(
    pred_path: str | Path,
    gold_path: str | Path,
    labels: list[str] = LABELS,
) -> dict[str, Any]:
    """Evaluate predictions against gold annotations.

    Args:
        pred_path: JSONL with {"sample_id": ..., "labels": {...}}
        gold_path: JSONL with same format

    Returns:
        dict with per-label metrics and overall stats
    """
    # Load
    pred_map = {}
    with open(pred_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                d = json.loads(line)
                pred_map[d["sample_id"]] = d.get("labels", {})

    gold_map = {}
    with open(gold_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                d = json.loads(line)
                gold_map[d["sample_id"]] = d.get("labels", {})

    # Find common samples
    common_ids = set(pred_map.keys()) & set(gold_map.keys())
    if not common_ids:
        raise ValueError("No common sample_ids between pred and gold")

    # Compute per-label metrics
    per_label = {}
    for label in labels:
        y_true = [bool(gold_map[sid].get(label, False)) for sid in common_ids]
        y_pred = [bool(pred_map[sid].get(label, False)) for sid in common_ids]
        metrics = binary_metrics(y_true, y_pred)
        metrics["kappa"] = round(cohens_kappa(y_true, y_pred), 4)
        per_label[label] = metrics

    # Macro averages
    avg_p = sum(m["precision"] for m in per_label.values()) / len(per_label)
    avg_r = sum(m["recall"] for m in per_label.values()) / len(per_label)
    avg_f1 = sum(m["f1"] for m in per_label.values()) / len(per_label)
    avg_kappa = sum(m["kappa"] for m in per_label.values()) / len(per_label)

    return {
        "n_samples": len(common_ids),
        "n_labels": len(labels),
        "per_label": per_label,
        "macro_avg": {
            "precision": round(avg_p, 4),
            "recall": round(avg_r, 4),
            "f1": round(avg_f1, 4),
            "kappa": round(avg_kappa, 4),
        },
    }


# ---------------------------------------------------------------------------
# Parse annotation from markdown template
# ---------------------------------------------------------------------------

def parse_annotation_template(md_path: str | Path) -> list[dict]:
    """Parse annotations from a filled-out markdown template.

    Looks for patterns like:
    - label_name: [1]  or  - label_name: [0]

    Returns list of {"sample_id": ..., "labels": {...}}
    """
    md_path = Path(md_path)
    import re

    results = []
    current_sample = None
    current_labels = {}

    with open(md_path, "r", encoding="utf-8") as f:
        for line in f:
            # Sample header: ## 样本 1: s_000001  (contact)
            m = re.match(r"## 样本 \d+: (\S+)", line)
            if m:
                if current_sample:
                    results.append({
                        "sample_id": current_sample,
                        "labels": current_labels,
                    })
                current_sample = m.group(1)
                current_labels = {}
                continue

            # Label line: - label_name: [1] or [0]
            m = re.match(r"- (\w+): \[([01])\]", line.strip())
            if m and current_sample:
                label = m.group(1)
                value = m.group(2) == "1"
                current_labels[label] = value

    # Last sample
    if current_sample:
        results.append({
            "sample_id": current_sample,
            "labels": current_labels,
        })

    return results


def template_to_jsonl(md_path: str | Path, output_path: str | Path):
    """Convert filled annotation template to JSONL format."""
    results = parse_annotation_template(md_path)
    with open(output_path, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"Converted {len(results)} annotations to: {output_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Evaluate semantic analysis predictions")
    sub = parser.add_subparsers(dest="command", required=True)

    # Evaluate
    p_eval = sub.add_parser("evaluate", help="Evaluate predictions vs gold labels")
    p_eval.add_argument("--pred", required=True, help="Predictions JSONL")
    p_eval.add_argument("--gold", required=True, help="Gold annotations JSONL")
    p_eval.add_argument("--output", help="Output report path")

    # Convert template
    p_conv = sub.add_parser("convert", help="Convert filled MD template to JSONL")
    p_conv.add_argument("--template", required=True, help="Filled annotation template MD")
    p_conv.add_argument("--output", required=True, help="Output JSONL path")

    args = parser.parse_args()

    if args.command == "evaluate":
        result = evaluate_predictions(args.pred, args.gold)

        print("=" * 70)
        print(f"Evaluation Report  (n={result['n_samples']} samples, {result['n_labels']} labels)")
        print("=" * 70)
        print(f"{'Label':25s} {'Prec':>6s} {'Rec':>6s} {'F1':>6s} {'Acc':>6s} {'Kappa':>7s} {'P+':>5s} {'P-':>5s}")
        print("-" * 70)
        for label, m in result["per_label"].items():
            print(f"{label:25s} {m['precision']:6.3f} {m['recall']:6.3f} {m['f1']:6.3f} "
                  f"{m['accuracy']:6.3f} {m['kappa']:7.3f} {m['support_pos']:5d} {m['support_neg']:5d}")
        print("-" * 70)
        m = result["macro_avg"]
        print(f"{'MACRO AVG':25s} {m['precision']:6.3f} {m['recall']:6.3f} {m['f1']:6.3f} "
              f"{'':6s} {m['kappa']:7.3f}")
        print()

        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2, ensure_ascii=False)
            print(f"Full report saved to: {args.output}")

    elif args.command == "convert":
        template_to_jsonl(args.template, args.output)


if __name__ == "__main__":
    main()
