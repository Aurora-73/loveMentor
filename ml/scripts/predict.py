#!/usr/bin/env python3
"""对话行为分析推理脚本 — 对一段对话输出 10 个行为维度的 0-9 分数。

用法:
  # 分析一段对话（直接传文本）
  python ml/scripts/predict.py "她：你咋私聊" "我：我问一下wiki" "她：屎一样"

  # 分析 sample_windows.py 生成的样本文件
  python ml/scripts/predict.py --file ml/dataset/samples_phase0.jsonl

  # 分析单条样本
  python ml/scripts/predict.py --sample s_001262

  # 输出 JSON 格式
  python ml/scripts/predict.py --json "她：你咋私聊" "我：我问一下wiki"
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import onnxruntime as ort
from transformers import AutoTokenizer

MODEL_DIR = Path(__file__).resolve().parent.parent / "models"
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


def load_model():
    tokenizer = AutoTokenizer.from_pretrained(str(MODEL_DIR))
    session = ort.InferenceSession(str(MODEL_DIR / "macbert.onnx"))
    return tokenizer, session


def predict(tokenizer, session, messages: list[str]) -> np.ndarray:
    """输入消息列表，返回 10 维分数（0-9）。"""
    text = "\n".join(messages)
    encoded = tokenizer(
        text,
        max_length=512,
        padding="max_length",
        truncation=True,
        return_tensors="np",
    )
    outputs = session.run(None, {
        "input_ids": encoded["input_ids"],
        "attention_mask": encoded["attention_mask"],
    })
    return outputs[0][0] * 9.0


def main():
    tokenizer, session = load_model()

    # ── 从文件分析 ──
    if len(sys.argv) >= 3 and sys.argv[1] == "--file":
        path = Path(sys.argv[2])
        if not path.exists():
            print(f"错误：文件不存在 {path}")
            sys.exit(1)
        with open(path, "r", encoding="utf-8") as f:
            samples = [json.loads(line) for line in f if line.strip()]
        for s in samples:
            messages = [m["content"] for m in s["messages"]]
            scores = predict(tokenizer, session, messages)
            print(f"{s['sample_id']}: " + "|".join(f"{s:.1f}" for s in scores))
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
                        messages = [m["content"] for m in s["messages"]]
                        scores = predict(tokenizer, session, messages)
                        break
            else:
                print(f"错误：未找到 sample_id {sample_id}")
                sys.exit(1)
        _print_results(messages, scores)
        return

    # ── 从命令行参数分析 ──
    if len(sys.argv) < 2:
        print(__doc__.strip())
        return

    messages = sys.argv[1:]
    scores = predict(tokenizer, session, messages)
    _print_results(messages, scores)


def _print_results(messages: list[str], scores: np.ndarray, json_output: bool = False) -> None:
    if "--json" in sys.argv:
        result = dict(zip(LABELS, [round(float(s), 1) for s in scores]))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    print("输入:")
    for m in messages:
        print(f"  {m}")
    print()
    for label, score in zip(LABELS, scores):
        bar = "█" * max(0, min(10, int(score))) + "░" * max(0, 10 - max(0, min(10, int(score))))
        print(f"  {label:22s}  {bar}  {score:.1f}")
    print()


if __name__ == "__main__":
    main()
