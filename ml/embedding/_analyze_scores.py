"""Quick analysis of embedding score distributions to set thresholds."""
import json
import sys
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

results_path = Path(__file__).parent.parent / "outputs" / "embedding_results.jsonl"

LABELS = [
    "question_asking", "self_disclosure", "emotional_expression",
    "initiative_response", "flirt", "intimacy",
    "cold_conflict", "perfunctory", "investment", "willingness",
]

score_stats = defaultdict(list)

with open(results_path, "r", encoding="utf-8") as f:
    for line in f:
        if not line.strip():
            continue
        d = json.loads(line)
        for label in LABELS:
            score_stats[label].append(d["scores"][label])

print(f"Total samples: {len(score_stats[LABELS[0]])}")
print(f"\n{'Label':25s} {'min':>7s} {'max':>7s} {'mean':>7s} {'std':>7s} {'p10':>7s} {'p50':>7s} {'p90':>7s}")
print("-" * 90)

import numpy as np
for label in LABELS:
    scores = np.array(score_stats[label])
    print(f"{label:25s} {scores.min():7.4f} {scores.max():7.4f} {scores.mean():7.4f} "
          f"{scores.std():7.4f} {np.percentile(scores, 10):7.4f} "
          f"{np.percentile(scores, 50):7.4f} {np.percentile(scores, 90):7.4f}")

# Suggest thresholds: roughly the 60th-70th percentile
print(f"\nSuggested thresholds (using 70th percentile as starting point):")
for label in LABELS:
    scores = np.array(score_stats[label])
    p70 = np.percentile(scores, 70)
    p80 = np.percentile(scores, 80)
    print(f"  {label:25s} p70={p70:.4f}  p80={p80:.4f}")
