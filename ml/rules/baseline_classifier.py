"""Rule-based baseline classifier for semantic analysis labels.

Phase 0b: 10 binary labels for ConversationBehaviorAnalyzer.
Output format: {"sample_id": ..., "labels": {"flirt": true, ...}}

Labels (10 total, all observable text behaviors):
1. information_exchange - 交换事实信息
2. opinion_expression - 表达观点/评价
3. emotion_positive - 正向情绪
4. emotion_negative - 负向情绪
5. flirt - 暧昧/调侃
6. question_asking - 主动提问
7. self_disclosure - 自我暴露
8. invitation - 邀约/提议
9. framing_boundary - 关系边界信号
10. perfunctory - 敷衍回应
"""
from __future__ import annotations

import json
import re
import sys
import yaml
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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


LEXICON_DIR = Path(__file__).parent.parent / "lexicons"


def _match_pattern(text: str, pattern: dict) -> float:
    ptype = pattern.get("type", "keyword")
    weight = float(pattern.get("weight", 1.0))
    value = pattern.get("value", [])

    if ptype == "keyword":
        for kw in value:
            if kw in text:
                return weight
        return 0.0

    elif ptype == "exact_match":
        stripped = text.strip()
        if stripped in value:
            return weight
        return 0.0

    elif ptype == "regex":
        if re.search(value, text):
            return weight
        return 0.0

    elif ptype == "length_le":
        if len(text.strip()) <= int(value):
            return weight
        return 0.0

    return 0.0


class RuleClassifier:
    def __init__(self, label: str, config: dict):
        self.label = label
        self.config = config
        self.patterns = config.get("patterns", [])
        self.window_rule = config.get("window_rule", {})

    def score_message(self, text: str) -> float:
        total = 0.0
        for pat in self.patterns:
            total += _match_pattern(text, pat)
        return total

    def classify_window(self, her_messages: list[dict]) -> tuple[bool, float]:
        if not her_messages:
            return False, 0.0

        texts = [m["content"] for m in her_messages]
        n = len(texts)
        per_msg_scores = [self.score_message(t) for t in texts]
        hit_count = sum(1 for s in per_msg_scores if s > 0)
        total_score = sum(per_msg_scores)

        rule = self.window_rule

        if "her_hit_threshold" in rule:
            threshold = rule["her_hit_threshold"]
            return hit_count >= threshold, min(hit_count / max(threshold, 1), 1.0)

        if "her_ratio_threshold" in rule:
            ratio_threshold = rule["her_ratio_threshold"]
            min_count = rule.get("min_count", 1)
            if hit_count < min_count:
                return False, 0.0
            ratio = hit_count / n
            return ratio >= ratio_threshold, min(ratio / max(ratio_threshold, 0.01), 1.0)

        return hit_count > 0, min(total_score, 1.0)


def load_all_classifiers(lexicon_dir: Path = LEXICON_DIR) -> dict[str, RuleClassifier]:
    classifiers = {}
    for label in LABELS:
        yaml_path = lexicon_dir / f"{label}.yaml"
        if not yaml_path.exists():
            print(f"  WARNING: lexicon not found: {yaml_path}")
            continue
        with open(yaml_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        classifiers[label] = RuleClassifier(label, config)
    return classifiers


def classify_samples(input_path, output_path, classifiers=None):
    if classifiers is None:
        classifiers = load_all_classifiers()

    input_path = Path(input_path)
    output_path = Path(output_path)

    label_counts = {label: 0 for label in LABELS}
    total = 0

    with open(input_path, "r", encoding="utf-8") as fin, \
         open(output_path, "w", encoding="utf-8") as fout:

        for line in fin:
            if not line.strip():
                continue
            sample = json.loads(line)
            total += 1

            her_msgs = [m for m in sample["messages"] if m["role"] == "her"]

            labels_pred = {}
            scores = {}
            for label, clf in classifiers.items():
                pred, conf = clf.classify_window(her_msgs)
                labels_pred[label] = pred
                scores[label] = round(conf, 3)
                if pred:
                    label_counts[label] += 1

            result = {
                "sample_id": sample["sample_id"],
                "contact_wxid": sample["contact_wxid"],
                "contact_remark": sample["contact_remark"],
                "turn_count": sample["turn_count"],
                "her_message_count": len(her_msgs),
                "labels": labels_pred,
                "scores": scores,
            }
            fout.write(json.dumps(result, ensure_ascii=False) + "\n")

    summary = {
        "total_samples": total,
        "label_positive_counts": label_counts,
        "label_positive_rates": {
            k: round(v / max(total, 1), 3) for k, v in label_counts.items()
        },
    }
    return summary


def main():
    print("=" * 60)
    print("Phase 0b: Rule-based baseline classification")
    print("=" * 60)

    input_path = Path(r"<project_root>\data\ml_dataset") / "samples_phase0.jsonl"
    output_path = Path(r"<project_root>\data\ml_outputs") / "baseline_results.jsonl"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not input_path.exists():
        print(f"ERROR: input file not found: {input_path}")
        print("Run dataset/sample_windows.py first.")
        sys.exit(1)

    print("\nLoading rule classifiers...")
    classifiers = load_all_classifiers()
    print(f"  Loaded {len(classifiers)} classifiers")

    print("\nClassifying samples...")
    summary = classify_samples(input_path, output_path, classifiers)

    print(f"\nResults saved to: {output_path}")
    print(f"\nLabel distribution:")
    print(f"  Total samples: {summary['total_samples']}")
    for label in LABELS:
        cnt = summary["label_positive_counts"][label]
        rate = summary["label_positive_rates"][label]
        bar = "#" * int(rate * 50)
        print(f"  {label:25s} {cnt:5d} ({rate:5.1%}) {bar}")


if __name__ == "__main__":
    main()
