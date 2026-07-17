#!/usr/bin/env python3
"""对话行为分析推理脚本 — 对一段对话输出 10 个行为维度的 0-9 分数。

用法:
  python ml/scripts/predict.py "她：你咋私聊" "我：我问一下wiki" "她：屎一样"
  python ml/scripts/predict.py --file data/ml_dataset/samples_phase0.jsonl
  python ml/scripts/predict.py --sample s_001262
  python ml/scripts/predict.py --json "她：你咋私聊" "我：我问一下wiki"
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

MODEL_DIR = Path(__file__).resolve().parent.parent / "models"
LABELS = [
    "information_exchange", "opinion_expression", "emotion_positive",
    "emotion_negative", "flirt", "question_asking", "self_disclosure",
    "invitation", "framing_boundary", "perfunctory",
]


def predict_via_classifier(messages: list[dict]) -> dict[str, float]:
    """使用 ONNXBehaviorClassifier（B0 默认，roleless 兼容）。"""
    from ml.rules.classifier_onnx import ONNXBehaviorClassifier
    clf = ONNXBehaviorClassifier.get_instance()
    return clf.predict_scores(messages, target_role="her")


def main():
    # ── 从文件分析 ──
    if len(sys.argv) >= 3 and sys.argv[1] == "--file":
        path = Path(sys.argv[2])
        if not path.exists():
            print(f"错误：文件不存在 {path}")
            sys.exit(1)
        with open(path, "r", encoding="utf-8") as f:
            samples = [json.loads(line) for line in f if line.strip()]
        for s in samples:
            msgs = s.get("messages", [])
            scores = predict_via_classifier(msgs)
            print(f"{s['sample_id']}: " + "|".join(f"{scores[l]:.1f}" for l in LABELS))
        return

    # ── 按 sample_id 分析 ──
    if len(sys.argv) >= 3 and sys.argv[1] == "--sample":
        sample_id = sys.argv[2]
        samples_path = Path(__file__).resolve().parent.parent.parent / "data" / "ml_dataset" / "samples_phase0.jsonl"
        if not samples_path.exists():
            print(f"错误：找不到样本文件 {samples_path}")
            sys.exit(1)
        with open(samples_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    s = json.loads(line)
                    if s["sample_id"] == sample_id:
                        msgs = s.get("messages", [])
                        scores = predict_via_classifier(msgs)
                        _print_results([m.get("content", "") for m in msgs], scores)
                        return
            print(f"错误：未找到 sample_id {sample_id}")
            sys.exit(1)

    # ── 从命令行参数分析（纯文本）──
    if len(sys.argv) < 2:
        print(__doc__.strip())
        return

    messages = sys.argv[1:]
    scores = predict_via_classifier(messages)
    print("输入:")
    for m in messages:
        print(f"  {m}")
    print()


def _print_results(messages: list[str], scores: dict, json_output: bool = False) -> None:
    if "--json" in sys.argv:
        print(json.dumps(scores, ensure_ascii=False, indent=2))
        return

    print("输入:")
    for m in messages:
        print(f"  {m}")
    print()
    for label in LABELS:
        score = scores.get(label, 0)
        bar = "█" * max(0, min(10, int(score))) + "░" * max(0, 10 - max(0, min(10, int(score))))
        print(f"  {label:22s}  {bar}  {score:.1f}")
    print()


if __name__ == "__main__":
    main()
