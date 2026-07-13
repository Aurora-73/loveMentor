"""ONNX-based behavior classifier — MacBERT ConversationBehaviorAnalyzer.

支持双模型：
- B0'（默认，use_role_prefix=False）：roleless 纯文本输入，当前生产基线
- B2（use_role_prefix=True）：target_other_v1 协议，带 [TARGET]/[OTHER] 前缀，角色感知

输入协议：
- use_role_prefix=False（B0'）：list[str] 或 list[dict]，提取 content 拼接
- use_role_prefix=True（B2）：list[dict] 含 role + content，调用 format_behavior_input

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

    与 RuleClassifier 接口对齐：classify_window(messages) -> (labels_dict, scores_dict)
    模型输出值域 [0, 9]（ONNX 输出 sigmoid 后乘以 9.0）。
    binary 判定阈值默认 >= 3.0（较弱及以上算存在）。

    双模型架构（通过 get_b0() / get_b2() 获取单例）：
    - B0'（use_role_prefix=False）：纯文本输入，当前生产基线。
      messages 可以是 list[str] 或 list[dict]（自动提取 content）。
    - B2（use_role_prefix=True）：target_other_v1 协议。messages 必须含
      role("me"/"her")+content，内部调用 format_behavior_input 添加 [TARGET]/[OTHER]。
    """

    _b0_instance: Optional["ONNXBehaviorClassifier"] = None
    _b2_instance: Optional["ONNXBehaviorClassifier"] = None

    def __init__(self, model_dir: Path = MODEL_DIR, binary_threshold: float = 3.0,
                 use_role_prefix: bool = False):
        self.model_dir = Path(model_dir)
        self.binary_threshold = binary_threshold
        self.use_role_prefix = use_role_prefix
        self._tokenizer = None
        self._session = None
        self._loaded = False

    @classmethod
    def get_instance(cls) -> "ONNXBehaviorClassifier":
        """(向后兼容) 等价于 get_b0()。"""
        return cls.get_b0()

    @classmethod
    def get_b0(cls) -> "ONNXBehaviorClassifier":
        """B0' roleless 模型（生产基线）。"""
        if cls._b0_instance is None:
            cls._b0_instance = cls(
                model_dir=MODEL_DIR / "baseline_b0_prime",
                use_role_prefix=False,
            )
        return cls._b0_instance

    @classmethod
    def get_b2(cls) -> "ONNXBehaviorClassifier":
        """B2 角色感知模型。"""
        if cls._b2_instance is None:
            cls._b2_instance = cls(
                model_dir=MODEL_DIR / "b2_role_balanced",
                use_role_prefix=True,
            )
        return cls._b2_instance

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
        logger.info("ONNX 模型已加载: %s", onnx_path)

        # 校验 model_metadata.json（校验通过后才标记 _loaded）
        metadata_path = self.model_dir / "model_metadata.json"
        if not metadata_path.exists():
            logger.warning("model_metadata.json 不存在（跳过校验）: %s", metadata_path)
            self._loaded = True
            return
        with open(metadata_path, "r", encoding="utf-8") as f:
            meta = json.load(f)

        expected_schema = "target_other_v1" if self.use_role_prefix else "roleless_v0"
        actual_schema = meta.get("schema_version", "")
        if actual_schema != expected_schema:
            self._loaded = False
            self._session = None
            self._tokenizer = None
            raise RuntimeError(
                f"模型 schema 不匹配: use_role_prefix={self.use_role_prefix} "
                f"需要 '{expected_schema}' 但 model_metadata.json 为 '{actual_schema}' "
                f"(模型目录: {self.model_dir})"
            )

        meta_labels = meta.get("labels", [])
        if meta_labels and meta_labels != LABELS:
            logger.warning(
                "model_metadata.json labels 与代码 LABELS 不一致: "
                "meta=%s, code=%s", meta_labels, LABELS
            )

        self._loaded = True
        logger.info("model_metadata 校验通过: schema=%s, labels=%d", actual_schema, len(meta_labels))

    def predict_scores(
        self,
        messages: list[dict] | list[str],
        target_role: str = "her",
    ) -> dict[str, float]:
        """对一组消息返回 10 个标签的 0-9 分数。

        use_role_prefix=False（B0' 兼容模式）：
            输入 list[str] 或 list[dict]，自动提取 content 做纯文本拼接。
            不添加任何角色前缀。

        use_role_prefix=True（B2 角色感知模式）：
            输入 [{"role": "me"/"her", "content": "..."}, ...]，
            调用 format_behavior_input 添加 [TARGET]/[OTHER] 前缀。

        Args:
            messages: 消息列表（格式取决于 use_role_prefix）。
            target_role: "her" 或 "me"。谁是 TARGET。仅在 role-aware 模式有效。

        Returns:
            {label_name: score_0_9, ...}
        """
        self._ensure_loaded()

        if not messages:
            return {label: 0.0 for label in LABELS}

        if self.use_role_prefix:
            # B2 角色感知协议：必须含 role 字段
            from ml.input_format import format_behavior_input
            text = format_behavior_input(messages, target_role=target_role)  # type: ignore[arg-type]
        else:
            # B0' 纯文本兼容
            texts = [str(m) if not isinstance(m, dict) else m.get("content", "") for m in messages]
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

    def classify_window(
        self,
        messages: list[dict] | list[str],
        target_role: str = "her",
    ) -> tuple[dict[str, bool], dict[str, float]]:
        """与 RuleClassifier.classify_window 接口兼容。

        输入格式由 self.use_role_prefix 决定：
        - False（B0'）：自动提取 content，纯文本拼接
        - True（B2）：调用 format_behavior_input 添加角色前缀

        Args:
            messages: 消息列表（同 predict_scores）。
            target_role: 目标人物角色，仅在 role-aware 模式有效。

        Returns:
            (labels_pred, scores)
            - labels_pred: {label: bool}  分数 >= threshold 算存在
            - scores: {label: float}     0-9 分数
        """
        scores = self.predict_scores(messages, target_role=target_role)
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
