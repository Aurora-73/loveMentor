"""ONNX-based behavior classifier — MacBERT ConversationBehaviorAnalyzer.

Phase 2 部署产物：与 baseline_classifier.py 接口兼容，可作为双参考之一。
模型只输出 10 个可观测行为标签的 0-9 分数（Layer 1），不做关系层推断。

标签顺序（与 labels.json 一致）：
1. information_exchange
2. opinion_expression
3. emotion_positive
4. emotion_negative
5. flirt
6. question_asking
7. self_disclosure
8. invitation
9. framing_boundary
10. perfunctory
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

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


class ONNXBehaviorClassifier:
    """MacBERT ONNX 推理器。

    与 RuleClassifier 接口对齐：
    - classify_window(messages) -> (labels_dict, scores_dict)

    模型输出值域 [0, 9]（ONNX 输出 sigmoid 后乘以 9.0）。
    binary 判定阈值默认 >= 3.0（较弱及以上算存在）。
    """

    _instance: Optional["ONNXBehaviorClassifier"] = None

    def __init__(self, model_dir: Path = MODEL_DIR, binary_threshold: float = 3.0):
        self.model_dir = Path(model_dir)
        self.binary_threshold = binary_threshold
        self._tokenizer = None
        self._session = None
        self._loaded = False

    @classmethod
    def get_instance(cls) -> "ONNXBehaviorClassifier":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _ensure_loaded(self):
        if self._loaded:
            return
        onnx_path = self.model_dir / "macbert.onnx"
        if not onnx_path.exists():
            raise FileNotFoundError(f"ONNX 模型不存在: {onnx_path}")

        import onnxruntime as ort
        from transformers import AutoTokenizer

        self._tokenizer = AutoTokenizer.from_pretrained(str(self.model_dir))
        self._session = ort.InferenceSession(str(onnx_path))
        self._loaded = True
        logger.info("ONNXBehaviorClassifier 已加载: %s", onnx_path)

    def predict_scores(self, messages: list[dict] | list[str]) -> dict[str, float]:
        """对一组消息返回 10 个标签的 0-9 分数。

        Args:
            messages: 消息列表，支持 [{"content": "..."}] 或 ["文本1", "文本2"]

        Returns:
            {label_name: score_0_9, ...}
        """
        self._ensure_loaded()

        if not messages:
            return {label: 0.0 for label in LABELS}

        texts = []
        for m in messages:
            if isinstance(m, dict):
                texts.append(m.get("content", ""))
            else:
                texts.append(str(m))

        text = "\n".join(texts)
        encoded = self._tokenizer(
            text,
            max_length=512,
            padding="max_length",
            truncation=True,
            return_tensors="np",
        )
        outputs = self._session.run(None, {
            "input_ids": encoded["input_ids"],
            "attention_mask": encoded["attention_mask"],
        })
        scores_raw = outputs[0][0] * 9.0

        return {label: round(float(scores_raw[i]), 2) for i, label in enumerate(LABELS)}

    def classify_window(self, messages: list[dict] | list[str]) -> tuple[dict[str, bool], dict[str, float]]:
        """与 RuleClassifier.classify_window 接口兼容。

        Returns:
            (labels_pred, scores)
            - labels_pred: {label: bool}  分数 >= threshold 算存在
            - scores: {label: float}     0-9 分数
        """
        scores = self.predict_scores(messages)
        labels_pred = {label: score >= self.binary_threshold for label, score in scores.items()}
        return labels_pred, scores

    def classify_her_messages(self, her_messages: list[dict]) -> tuple[dict[str, bool], dict[str, float]]:
        """与 RuleClassifier 完全兼容的接口（只输入她的消息）。

        注意：MacBERT 训练时用的是完整对话（含双方消息），
        这里如果只传她的消息会损失上下文。推荐用 classify_window 传完整对话。
        """
        return self.classify_window(her_messages)


def classify_samples_onnx(
    input_path,
    output_path,
    classifier: ONNXBehaviorClassifier | None = None,
):
    """批量分类样本文件（与 baseline_classifier.classify_samples 接口对齐）。

    输入格式：samples_phase0.jsonl（每行一个 sample，含 messages 列表）
    输出格式：{sample_id, labels: {bool}, scores: {float}}
    """
    if classifier is None:
        classifier = ONNXBehaviorClassifier.get_instance()

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

            messages = sample.get("messages", [])
            labels_pred, scores = classifier.classify_window(messages)

            for label, pred in labels_pred.items():
                if pred:
                    label_counts[label] += 1

            result = {
                "sample_id": sample["sample_id"],
                "contact_wxid": sample.get("contact_wxid", ""),
                "contact_remark": sample.get("contact_remark", ""),
                "turn_count": sample.get("turn_count", 0),
                "labels": labels_pred,
                "scores": scores,
                "source": "macbert_onnx",
            }
            fout.write(json.dumps(result, ensure_ascii=False) + "\n")

    summary = {
        "total_samples": total,
        "label_positive_counts": label_counts,
        "label_positive_rates": {
            k: round(v / max(total, 1), 3) for k, v in label_counts.items()
        },
        "source": "macbert_onnx",
    }
    return summary


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if len(sys.argv) < 2:
        print(__doc__.strip())
        print("\n用法:")
        print("  python -X utf8 ml/rules/classifier_onnx.py \"她：你咋私聊\" \"我：我问一下\"")
        print("  python -X utf8 ml/rules/classifier_onnx.py --file data/ml_dataset/samples_phase0.jsonl")
        sys.exit(0)

    clf = ONNXBehaviorClassifier.get_instance()

    if sys.argv[1] == "--file":
        input_path = sys.argv[2]
        output_path = str(Path(input_path).parent / "onnx_results.jsonl")
        print(f"批量分类: {input_path} -> {output_path}")
        summary = classify_samples_onnx(input_path, output_path, clf)
        print(f"\n总计: {summary['total_samples']} 样本")
        print("标签分布:")
        for label in LABELS:
            cnt = summary["label_positive_counts"][label]
            rate = summary["label_positive_rates"][label]
            print(f"  {label:25s} {cnt:5d} ({rate:5.1%})")
    else:
        messages = sys.argv[1:]
        scores = clf.predict_scores(messages)
        labels_pred, _ = clf.classify_window(messages)
        print("\n输入:")
        for m in messages:
            print(f"  {m}")
        print("\n行为分析结果:")
        for label in LABELS:
            score = scores[label]
            present = "✓" if labels_pred[label] else " "
            bar = "█" * max(0, min(10, int(score))) + "░" * max(0, 10 - max(0, min(10, int(score))))
            print(f"  [{present}] {label:22s}  {bar}  {score:.1f}")
