"""Generate annotation template for 150 audit samples.

Stratified sampling: for each label, pick some positives and negatives
to ensure we can evaluate precision/recall for all labels.
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

LABELS = [
    "question_asking", "self_disclosure", "emotional_expression",
    "initiative_response", "flirt", "intimacy",
    "cold_conflict", "perfunctory", "investment", "willingness",
]

SAMPLES_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "ml_dataset" / "samples_5000.jsonl"
BASELINE_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "ml_outputs" / "baseline_results.jsonl"
OUTPUT_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "ml_outputs" / "audit_samples_150.jsonl"
TEMPLATE_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "ml_outputs" / "annotation_template_150.md"

TARGET = 150


def load_jsonl(path: Path) -> list[dict]:
    items = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                items.append(json.loads(line))
    return items


def main():
    samples = load_jsonl(SAMPLES_PATH)
    baseline = load_jsonl(BASELINE_PATH)

    # Index by sample_id
    sample_by_id = {s["sample_id"]: s for s in samples}
    baseline_by_id = {b["sample_id"]: b for b in baseline}

    selected_ids: set[str] = set()
    selected: list[dict] = []

    # Stratified: for each label, pick 8 positives + 8 negatives (if available)
    # That's 10 labels * 16 = 160, then we dedupe and cap at 150
    random.seed(42)

    for label in LABELS:
        pos_ids = [
            b["sample_id"] for b in baseline
            if b["labels"].get(label, False) and b["sample_id"] not in selected_ids
        ]
        neg_ids = [
            b["sample_id"] for b in baseline
            if not b["labels"].get(label, False) and b["sample_id"] not in selected_ids
        ]

        random.shuffle(pos_ids)
        random.shuffle(neg_ids)

        # Take up to 8 of each
        n_pos = min(8, len(pos_ids))
        n_neg = min(8, len(neg_ids))

        for sid in pos_ids[:n_pos]:
            selected_ids.add(sid)
        for sid in neg_ids[:n_neg]:
            selected_ids.add(sid)

    print(f"After stratified sampling: {len(selected_ids)} unique samples")

    # If we have fewer than TARGET, fill randomly
    all_ids = [b["sample_id"] for b in baseline if b["sample_id"] not in selected_ids]
    random.shuffle(all_ids)
    need = max(0, TARGET - len(selected_ids))
    for sid in all_ids[:need]:
        selected_ids.add(sid)

    # Build final list
    selected = [sample_by_id[sid] for sid in selected_ids if sid in sample_by_id]
    random.shuffle(selected)
    selected = selected[:TARGET]

    print(f"Final audit set: {len(selected)} samples")

    # Save audit samples JSONL
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        for s in selected:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    print(f"Saved to: {OUTPUT_PATH}")

    # Generate annotation template (Markdown)
    with open(TEMPLATE_PATH, "w", encoding="utf-8") as f:
        f.write("# 语义分析标注模板 — 150 条抽检样本\n\n")
        f.write("> 标注规范：ml/docs/annotation_guideline.md\n")
        f.write("> 标注说明：对每个样本的 10 个标签逐一判断，在 [ ] 中填 1（正例）或 0（负例）\n\n")
        f.write("---\n\n")

        for i, s in enumerate(selected, 1):
            sample_id = s["sample_id"]
            contact = s.get("contact_remark", s.get("contact_wxid", "?"))
            bl = baseline_by_id.get(sample_id, {})
            rule_labels = bl.get("labels", {})

            f.write(f"## 样本 {i}: {sample_id}  ({contact})\n\n")
            f.write(f"- 轮数: {s['turn_count']}\n")
            f.write(f"- 规则基线预测: " + ", ".join(
                f"{k}={'是' if v else '否'}" for k, v in rule_labels.items()
            ) + "\n\n")

            f.write("**对话内容：**\n\n")
            for msg in s["messages"]:
                role = "她" if msg["role"] == "her" else "我"
                content = msg["content"].replace("\n", " / ")
                if len(content) > 120:
                    content = content[:120] + "..."
                f.write(f"- [{role}] {content}\n")

            f.write("\n**标注：**\n\n")
            for label in LABELS:
                f.write(f"- {label}: [ ]  \n")
            f.write("\n---\n\n")

    print(f"Annotation template saved to: {TEMPLATE_PATH}")


if __name__ == "__main__":
    main()
