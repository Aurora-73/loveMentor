"""Weakly supervised classifier: train logistic regression on rule labels.

Uses embeddings as features and rule-based predictions as weak labels.
This should work better than pure zero-shot centroid similarity.

Phase 0c step 2: weak supervision baseline.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from embedding.embedder import get_embedder  # noqa: E402

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
# Feature extraction
# ---------------------------------------------------------------------------

def extract_features(sample: dict, embedder) -> np.ndarray:
    """Extract embedding features for a window.

    Features:
    - mean embedding of her messages
    - mean embedding of all messages
    - (optional) count-based features could be added
    """
    her_texts = [m["content"] for m in sample["messages"] if m.get("role") == "her"]
    all_texts = [m["content"] for m in sample["messages"]]

    features = []

    # Her messages mean embedding
    if her_texts:
        her_emb = embedder.encode(her_texts)
        her_mean = np.mean(her_emb, axis=0)
    else:
        her_mean = np.zeros(embedder._load_model().get_sentence_embedding_dimension())
    features.append(her_mean)

    # All messages mean embedding
    if all_texts:
        all_emb = embedder.encode(all_texts)
        all_mean = np.mean(all_emb, axis=0)
    else:
        all_mean = np.zeros_like(her_mean)
    features.append(all_mean)

    # Normalize
    feat = np.concatenate(features)
    feat = feat / (np.linalg.norm(feat) + 1e-8)
    return feat


# ---------------------------------------------------------------------------
# Simple logistic regression (no sklearn dependency, pure numpy)
# ---------------------------------------------------------------------------

def sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(x, -30, 30)))


class LogisticRegression:
    """Simple logistic regression with L2 regularization."""

    def __init__(self, lr: float = 0.1, epochs: int = 500, l2: float = 0.01):
        self.lr = lr
        self.epochs = epochs
        self.l2 = l2
        self.w: np.ndarray | None = None
        self.b: float = 0.0

    def fit(self, X: np.ndarray, y: np.ndarray):
        n_samples, n_features = X.shape
        self.w = np.zeros(n_features)
        self.b = 0.0

        # Handle class imbalance with class weights
        pos_weight = (n_samples - y.sum()) / max(y.sum(), 1)

        for _ in range(self.epochs):
            z = X @ self.w + self.b
            pred = sigmoid(z)

            # Weighted gradient
            error = pred - y
            weights = np.where(y == 1, pos_weight, 1.0)
            grad_w = (X.T * error * weights).mean(axis=1) + self.l2 * self.w
            grad_b = (error * weights).mean()

            self.w -= self.lr * grad_w
            self.b -= self.lr * grad_b

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        z = X @ self.w + self.b
        return sigmoid(z)

    def predict(self, X: np.ndarray, threshold: float = 0.5) -> np.ndarray:
        return self.predict_proba(X) >= threshold


# ---------------------------------------------------------------------------
# Train + classify
# ---------------------------------------------------------------------------

def train_weak_classifier(
    samples_path: str | Path,
    rule_labels_path: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    """Train weakly supervised classifiers for all labels.

    Uses rule-based predictions as weak labels, trains on embeddings.
    """
    samples_path = Path(samples_path)
    rule_labels_path = Path(rule_labels_path)
    output_path = Path(output_path)

    # Load data
    samples = []
    with open(samples_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                samples.append(json.loads(line))

    rule_map = {}
    with open(rule_labels_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                d = json.loads(line)
                rule_map[d["sample_id"]] = d.get("labels", {})

    # Filter to samples with rule labels
    samples = [s for s in samples if s["sample_id"] in rule_map]
    print(f"Training on {len(samples)} samples")

    # Extract features
    embedder = get_embedder()
    print("Extracting features...")
    X = np.array([extract_features(s, embedder) for s in samples])
    print(f"  Feature dim: {X.shape[1]}")

    # Train per-label
    classifiers = {}
    label_counts = {}

    for label in LABELS:
        y = np.array([float(rule_map[s["sample_id"]].get(label, False)) for s in samples])

        if y.sum() < 5:
            print(f"  {label}: too few positives ({int(y.sum())}), skipping training")
            classifiers[label] = None
            label_counts[label] = int(y.sum())
            continue

        clf = LogisticRegression(lr=0.5, epochs=1000, l2=0.001)
        clf.fit(X, y)

        # In-sample predictions
        preds = clf.predict(X)
        pos = int(preds.sum())
        classifiers[label] = clf
        label_counts[label] = int(y.sum())

        print(f"  {label}: rule_pos={int(y.sum())}, pred_pos={pos}")

    # Generate predictions on all samples
    output_path.parent.mkdir(parents=True, exist_ok=True)
    results = []
    for i, sample in enumerate(samples):
        labels_pred = {}
        scores = {}
        for label in LABELS:
            clf = classifiers.get(label)
            if clf is None:
                # Fallback to rule label if too few positives
                labels_pred[label] = bool(rule_map[sample["sample_id"]].get(label, False))
                scores[label] = 1.0 if labels_pred[label] else 0.0
            else:
                prob = float(clf.predict_proba(X[i:i+1])[0])
                scores[label] = round(prob, 4)
                labels_pred[label] = prob >= 0.5

        results.append({
            "sample_id": sample["sample_id"],
            "contact_wxid": sample["contact_wxid"],
            "contact_remark": sample["contact_remark"],
            "turn_count": sample["turn_count"],
            "her_message_count": sum(1 for m in sample["messages"] if m.get("role") == "her"),
            "labels": labels_pred,
            "scores": scores,
        })

    with open(output_path, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # Summary
    summary = {
        "n_samples": len(samples),
        "label_positive_counts": {
            label: sum(1 for r in results if r["labels"][label])
            for label in LABELS
        },
        "rule_positive_counts": label_counts,
    }
    summary["label_positive_rates"] = {
        k: round(v / max(len(results), 1), 3)
        for k, v in summary["label_positive_counts"].items()
    }
    return summary


def main():
    print("=" * 60)
    print("Phase 0c: Weakly supervised embedding classifier")
    print("(train logistic regression on rule labels + embeddings)")
    print("=" * 60)

    project_root = Path(__file__).resolve().parents[2]
    samples_path = project_root / "data" / "ml_dataset" / "samples_5000.jsonl"
    rule_path = project_root / "data" / "ml_outputs" / "baseline_results.jsonl"
    output_path = project_root / "data" / "ml_outputs" / "weak_supervised_results.jsonl"

    print()
    summary = train_weak_classifier(samples_path, rule_path, output_path)

    print(f"\nResults saved to: {output_path}")
    print(f"\nLabel distribution (weak supervised, threshold=0.5):")
    print(f"  Total samples: {summary['n_samples']}")
    for label in LABELS:
        cnt = summary["label_positive_counts"][label]
        rate = summary["label_positive_rates"][label]
        rule_cnt = summary["rule_positive_counts"].get(label, 0)
        bar = "#" * int(rate * 50)
        print(f"  {label:25s} {cnt:5d} ({rate:5.1%}) rule={rule_cnt:4d} {bar}")


if __name__ == "__main__":
    main()
