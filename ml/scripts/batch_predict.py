#!/usr/bin/env python3
"""批量推理脚本 — 对所有已标注样本运行 MacBERT 模型预测。

用法:
  python ml/scripts/batch_predict.py [--model-base PATH] [--batch-size 64] [--output preds.jsonl]

默认将预测结果保存到 ml/dataset/annotations/predictions.jsonl。
每行格式: {"sample_id": "s_001000", "scores": [0.5, 0.3, ...]}

在 A100 GPU 上运行:
  python ml/scripts/batch_predict.py --batch-size 128
"""
from __future__ import annotations

import json
import sys
import argparse
from pathlib import Path

import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader
from transformers import AutoTokenizer, AutoModel

LABELS = [
    "information_exchange", "opinion_expression", "emotion_positive",
    "emotion_negative", "flirt", "question_asking", "self_disclosure",
    "invitation", "framing_boundary", "perfunctory",
]
NUM_LABELS = len(LABELS)

# ── 模型定义（与 phase2_train.py 一致）──

class MacBERTRegressor(nn.Module):
    def __init__(self, model_name: str, num_labels: int = NUM_LABELS):
        super().__init__()
        self.bert = AutoModel.from_pretrained(model_name)
        self.dropout = nn.Dropout(0.3)
        self.regressor = nn.Linear(self.bert.config.hidden_size, num_labels)

    def forward(self, input_ids, attention_mask):
        outputs = self.bert(input_ids=input_ids, attention_mask=attention_mask)
        cls_output = outputs.last_hidden_state[:, 0, :]
        cls_output = self.dropout(cls_output)
        logits = self.regressor(cls_output)
        return torch.sigmoid(logits)


# ── 数据 ──

class InferenceDataset(Dataset):
    """只存 sample_id + tokenized inputs，不依赖完整 sample 记录。"""
    def __init__(self, records: list[dict]):
        self.records = records  # 每个元素: {sample_id, input_ids, attention_mask}

    def __len__(self):
        return len(self.records)

    def __getitem__(self, idx):
        r = self.records[idx]
        return {
            "sample_id": r["sample_id"],
            "input_ids": r["input_ids"].flatten(),
            "attention_mask": r["attention_mask"].flatten(),
        }


# ── 加载数据 ──

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
BATCHES_DIR = PROJECT_ROOT / "ml" / "dataset" / "batches"
ANN_DIR = PROJECT_ROOT / "ml" / "dataset" / "annotations"


def collect_samples() -> list[dict]:
    """从所有 batch 中收集待推理的样本（只含 non-discard 的）。"""
    samples = {}

    # 读所有 batch 文件
    for bpath in sorted(BATCHES_DIR.glob("batch_*.jsonl")):
        with open(bpath, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    s = json.loads(line)
                    samples[s["sample_id"]] = {
                        "sample_id": s["sample_id"],
                        "messages": s["messages"],
                    }

    # 读所有 annotation 文件，排除 discard 的
    ann_files = sorted(ANN_DIR.glob("annotations_*.jsonl"))
    keep_ids = set()
    for apath in ann_files:
        with open(apath, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    ann = json.loads(line)
                    if not ann.get("discard", False) and ann.get("labels"):
                        keep_ids.add(ann["sample_id"])

    # 返回保留的样本
    result = []
    for sid in keep_ids:
        if sid in samples:
            result.append(samples[sid])
    return result


def tokenize_samples(
    samples: list[dict], tokenizer, max_len: int = 512,
) -> list[dict]:
    records = []
    for s in samples:
        messages = s.get("messages", [])
        # 纯文本拼接（B0 roleless 兼容，有 role 字段时自动提取 content）
        text = "\n".join(m["content"] if isinstance(m, dict) else str(m) for m in messages)
        encoded = tokenizer(
            text,
            max_length=max_len,
            padding="max_length",
            truncation=True,
            return_tensors="pt",
        )
        records.append({
            "sample_id": s["sample_id"],
            "input_ids": encoded["input_ids"][0],
            "attention_mask": encoded["attention_mask"][0],
        })
    return records


@torch.inference_mode()
def predict(
    model: nn.Module,
    loader: DataLoader,
    device: torch.device,
) -> dict[str, list[float]]:
    """返回 {sample_id: [10 scores normalized 0-1]}"""
    model.eval()
    results = {}
    for batch in loader:
        input_ids = batch["input_ids"].to(device)
        attention_mask = batch["attention_mask"].to(device)
        scores = model(input_ids, attention_mask)  # [B, 10]
        for i, sid in enumerate(batch["sample_id"]):
            results[sid] = scores[i].cpu().tolist()
    return results


def main():
    parser = argparse.ArgumentParser(description="批量推理：MacBERT 对话行为预测")
    parser.add_argument("--model-base", default=None,
                        help="MacBERT 基础模型路径或名称（默认自动查找）")
    parser.add_argument("--model-dir", default=None,
                        help="模型权重目录（含 macbert_best.pt）")
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--output", default=None,
                        help="输出路径（默认 ml/dataset/annotations/predictions.jsonl）")
    args = parser.parse_args()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")
    if device.type == "cuda":
        print(f"  GPU: {torch.cuda.get_device_name(0)}")
        print(f"  Memory: {torch.cuda.get_device_properties(0).total_memory / 1e9:.1f} GB")

    # ── 路径 ──
    model_dir = Path(args.model_dir) if args.model_dir else PROJECT_ROOT / "ml" / "models"
    output_path = Path(args.output) if args.output else ANN_DIR / "predictions.jsonl"

    # ── 确定 MacBERT 基础模型路径 ──
    if args.model_base:
        model_base_path = args.model_base
    else:
        candidates = [
            "/home2/cme_code/convert/hf_cache/hfl_chinese-macbert-base",
            "hfl/chinese-macbert-base",
        ]
        model_base_path = candidates[0]
        if not Path(model_base_path).exists():
            model_base_path = candidates[1]
            print(f"本地缓存不存在，回退到 HF hub: {model_base_path}")

    print(f"Base model: {model_base_path}")
    print(f"Weights: {model_dir / 'macbert_best.pt'}")
    print(f"Output: {output_path}")

    # ── 加载模型 ──
    print("Loading model...")
    tokenizer = AutoTokenizer.from_pretrained(str(model_dir))
    model = MacBERTRegressor(model_base_path)
    # 扩展 embedding 层以容纳 [TARGET]/[OTHER] 特殊 token（训练时已添加）
    model.bert.resize_token_embeddings(len(tokenizer))
    state_dict = torch.load(
        model_dir / "macbert_best.pt",
        map_location=device,
        weights_only=True,
    )
    model.load_state_dict(state_dict)
    model = model.to(device)
    print(f"  Parameters: {sum(p.numel() for p in model.parameters()):,}")

    # ── 收集样本 ──
    print("Collecting samples...")
    samples = collect_samples()
    print(f"  Total non-discard samples: {len(samples)}")

    # ── Tokenize ──
    print("Tokenizing...")
    records = tokenize_samples(samples, tokenizer)
    dataset = InferenceDataset(records)
    loader = DataLoader(
        dataset,
        batch_size=args.batch_size,
        shuffle=False,
        num_workers=0,
    )
    print(f"  Batches: {len(loader)} (batch_size={args.batch_size})")

    # ── 推理 ──
    print("Running inference...")
    import time
    start = time.perf_counter()
    results = predict(model, loader, device)
    elapsed = time.perf_counter() - start
    print(f"  Done: {len(results)} samples in {elapsed:.1f}s ({elapsed/len(results)*1000:.1f}ms/sample)")

    # ── 保存 ──
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        for sid in sorted(results.keys()):
            record = {"sample_id": sid, "scores": results[sid]}
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"Saved: {output_path}")


if __name__ == "__main__":
    main()
