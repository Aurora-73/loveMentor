"""Embedding-based classifier for semantic analysis labels.

Phase 0c: Use rule-based labels as weak supervision to train
embedding + logistic regression classifiers.

For each label:
1. Take all windows with rule predictions
2. Encode her messages into embeddings (bge-small-zh-v1.5)
3. Train a logistic regression on rule labels
4. The classifier can then predict on new windows
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
# Simple cosine-similarity based classifier
# (no training needed, uses keyword centroids)
# ---------------------------------------------------------------------------

def build_keyword_centroid(keywords: list[str], embedder) -> np.ndarray:
    """Build a centroid embedding from a list of keywords.

    This gives us a "concept vector" for the label.
    """
    embeddings = embedder.encode(keywords)
    return np.mean(embeddings, axis=0)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity between two vectors."""
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-8))


# Keyword sets for building label centroids
LABEL_KEYWORDS = {
    "question_asking": [
        "你觉得呢", "你怎么看", "你喜欢什么", "你在干嘛", "你在哪呢",
        "你有女朋友吗", "为什么呢", "怎么回事", "怎么办呢", "可以吗",
        "你觉得怎么样", "你平时做什么", "你周末干嘛", "你多大了",
        "你家在哪里", "你有什么爱好", "你吃过了吗", "你今天怎么样",
    ],
    "self_disclosure": [
        "我今天好累", "我小时候很调皮", "我家里情况", "我的秘密",
        "我跟你说件事", "我以前也这样", "我感觉很开心", "我有点难过",
        "我喜欢的类型", "我害怕孤单", "我家里有只猫", "我爸妈离婚了",
        "我梦想是当画家", "我初恋是高中", "我从来没跟别人说过",
    ],
    "emotional_expression": [
        "哈哈哈太好笑了", "好开心啊", "好可爱呀", "太棒了吧",
        "难过死了", "好委屈啊", "气死我了", "好害怕呀",
        "呜呜呜好惨", "嘿嘿嘿", "嘻嘻嘻", "哇塞厉害",
        "天哪不会吧", "真的假的啊", "好感动啊", "暖暖的很贴心",
    ],
    "initiative_response": [
        "然后呢后来呢", "还有呢还有什么", "怎么了没事吧",
        "真的吗我不信", "这样啊原来是这样", "你继续说我听着",
        "好厉害啊佩服", "太惨了心疼你", "我懂我理解你",
        "我也是这样的", "同感我也觉得", "抱抱你安慰你",
    ],
    "flirt": [
        "想你了宝贝", "喜欢你亲爱的", "爱你么么哒", "亲亲抱抱举高高",
        "你好坏呀讨厌", "笨蛋傻瓜想你", "臭宝子乖乖的", "亲爱的在干嘛",
        "宝贝晚安啦", "想你想你想你", "你真的好可爱", "人家想你了啦",
        "不要嘛人家不", "你欺负我嘤嘤", "老公老婆爱你",
    ],
    "intimacy": [
        "宝贝乖乖睡觉", "亲爱的我想你", "抱抱我好冷",
        "牵手一起走", "靠在你肩膀", "摸摸头乖啦",
        "我家里的情况", "小时候的故事", "我的秘密只告诉你",
        "我们以后一起", "见家长的事情", "我们的未来",
    ],
    "cold_conflict": [
        "随便你吧都行", "无所谓了", "不用了谢谢",
        "算了没什么", "不想说别问了", "关你什么事",
        "你好烦啊", "不想理你了", "滚远点行不行",
        "神经病啊你", "我真的服了", "无语死了",
        "你有病吧", "别烦我忙着呢", "跟你没关系",
    ],
    "perfunctory": [
        "嗯", "哦", "好的", "是的", "嗯嗯",
        "哦哦", "好吧", "ok", "行吧", "收到",
        "了解", "嗯呢", "昂", "好滴", "好哒",
        "嗯好的", "哦好的", "。。。", "...",
    ],
    "investment": [
        "我陪你一起", "我等你回来", "我去找你",
        "出来玩呗见面", "周末有空吗", "一起吃饭吧",
        "担心你身体", "心疼你辛苦", "我帮你搞定",
        "给你买礼物", "送你一个惊喜", "照顾好自己",
        "为了你值得", "想天天陪着你", "保护你不受欺负",
    ],
    "willingness": [
        "好呀好呀没问题", "可以呀当然行", "必须的呀",
        "正有此意哈哈", "求之不得呢", "好啊好啊走",
        "要不我们去吃", "不如看电影吧", "要不要一起",
        "想不想去玩", "敢不敢打赌", "来不来呀",
        "下次我们去吧", "以后一起努力", "我们的约定",
    ],
}


class EmbeddingClassifier:
    """Embedding-based classifier using keyword centroids + cosine similarity.

    Zero-shot: no training data needed, just keyword descriptions.
    """

    def __init__(self, embedder=None):
        self.embedder = embedder or get_embedder()
        self.centroids: dict[str, np.ndarray] = {}
        self.thresholds: dict[str, float] = {}
        self._build_centroids()

    def _build_centroids(self):
        """Build centroid vectors for each label from keyword lists."""
        print("Building label centroids from keywords...")
        for label, keywords in LABEL_KEYWORDS.items():
            centroid = build_keyword_centroid(keywords, self.embedder)
            # Normalize
            centroid = centroid / (np.linalg.norm(centroid) + 1e-8)
            self.centroids[label] = centroid
            # Default threshold: 0.75 (tuned for bge-small-zh Chinese)
            # Higher because Chinese sentence embeddings have high baseline similarity
            self.thresholds[label] = 0.75
        print(f"  Built centroids for {len(self.centroids)} labels")

    def score_window(self, messages: list[dict]) -> dict[str, float]:
        """Score a window against all label centroids.

        Returns dict of {label: cosine_similarity}.
        """
        her_texts = [m["content"] for m in messages if m.get("role") == "her"]
        if not her_texts:
            return {label: 0.0 for label in LABELS}

        # Encode each message, then average
        embeddings = self.embedder.encode(her_texts)
        window_embedding = np.mean(embeddings, axis=0)
        window_embedding = window_embedding / (np.linalg.norm(window_embedding) + 1e-8)

        scores = {}
        for label, centroid in self.centroids.items():
            scores[label] = cosine_similarity(window_embedding, centroid)
        return scores

    def classify_window(
        self,
        messages: list[dict],
        thresholds: dict[str, float] | None = None,
    ) -> tuple[dict[str, bool], dict[str, float]]:
        """Classify a window: compare scores to thresholds.

        Returns (predictions, scores).
        """
        scores = self.score_window(messages)
        thresh = thresholds or self.thresholds
        preds = {label: scores[label] >= thresh.get(label, 0.4) for label in LABELS}
        return preds, scores


# ---------------------------------------------------------------------------
# Batch classification
# ---------------------------------------------------------------------------

def classify_samples_embedding(
    input_path: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    """Classify all samples using embedding-based classifier.

    Args:
        input_path: path to samples JSONL
        output_path: path to write results JSONL

    Returns:
        summary dict
    """
    input_path = Path(input_path)
    output_path = Path(output_path)

    clf = EmbeddingClassifier()

    label_counts = {label: 0 for label in LABELS}
    total = 0

    with open(input_path, "r", encoding="utf-8") as fin, \
         open(output_path, "w", encoding="utf-8") as fout:

        for line in fin:
            if not line.strip():
                continue
            sample = json.loads(line)
            total += 1

            preds, scores = clf.classify_window(sample["messages"])

            # Round scores
            scores_rounded = {k: round(v, 4) for k, v in scores.items()}

            for label in LABELS:
                if preds[label]:
                    label_counts[label] += 1

            result = {
                "sample_id": sample["sample_id"],
                "contact_wxid": sample["contact_wxid"],
                "contact_remark": sample["contact_remark"],
                "turn_count": sample["turn_count"],
                "her_message_count": sum(1 for m in sample["messages"] if m.get("role") == "her"),
                "labels": preds,
                "scores": scores_rounded,
            }
            fout.write(json.dumps(result, ensure_ascii=False) + "\n")

            if total % 100 == 0:
                print(f"  Processed {total} samples...")

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
    print("Phase 0c: Embedding-based classification")
    print("=" * 60)

    project_root = Path(__file__).resolve().parent.parent.parent
    input_path = project_root / "data" / "ml_dataset" / "samples_5000.jsonl"
    output_path = project_root / "data" / "ml_outputs" / "embedding_results.jsonl"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not input_path.exists():
        print(f"ERROR: input file not found: {input_path}")
        print("Run dataset/sample_windows.py first.")
        sys.exit(1)

    print("\nClassifying samples with embedding centroids...")
    summary = classify_samples_embedding(input_path, output_path)

    print(f"\nResults saved to: {output_path}")
    print(f"\nLabel distribution (threshold = 0.75):")
    print(f"  Total samples: {summary['total_samples']}")
    for label in LABELS:
        cnt = summary["label_positive_counts"][label]
        rate = summary["label_positive_rates"][label]
        bar = "#" * int(rate * 50)
        print(f"  {label:25s} {cnt:5d} ({rate:5.1%}) {bar}")


if __name__ == "__main__":
    main()
