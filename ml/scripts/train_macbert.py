#!/usr/bin/env python3
"""MacBERT 多标签回归训练 — 适配 13,676 条标注数据集。

用法（A100 上）:
  # 数据已通过 samba 同步到 /home2/cme_code/loveMentor_ml/dataset/
  cd /home2/cme_code/loveMentor_ml

  # 快速验证（3 epoch）
  python scripts/train_macbert.py --epochs 3 --batch-size 16

  # 正式训练
  python scripts/train_macbert.py --epochs 20 --batch-size 32 --lr 2e-5

参数:
  --samples      训练样本文件（默认 dataset/training_samples.jsonl）
  --annotations  标注文件（默认 dataset/training_annotations.jsonl）
  --model-name   MacBERT 模型路径（默认预训练缓存路径）
  --output       模型输出目录（默认 models/）
  --epochs       训练轮数（默认 20）
  --batch-size   batch size（默认 32）
  --lr           学习率（默认 2e-5）
  --patience     早停耐心值（默认 5）
  --val-split    验证集比例（默认 0.1）
  --seed         随机种子（默认 42）
"""
from __future__ import annotations

import json
import argparse
import random
import numpy as np
from pathlib import Path
from collections import defaultdict

import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader
from torch.optim import AdamW
from transformers import AutoTokenizer, AutoModel, get_linear_schedule_with_warmup

LABELS = [
    "information_exchange", "opinion_expression", "emotion_positive",
    "emotion_negative", "flirt", "question_asking", "self_disclosure",
    "invitation", "framing_boundary", "perfunctory",
]

# ── 预训练模型路径（A100 本地缓存）──
DEFAULT_MODEL = "/home2/cme_code/convert/hf_cache/hfl_chinese-macbert-base"

# ── 默认数据路径（相对于项目根目录）──
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SAMPLES = PROJECT_ROOT / "dataset" / "training_samples.jsonl"
DEFAULT_ANNOTATIONS = PROJECT_ROOT / "dataset" / "training_annotations.jsonl"
DEFAULT_OUTPUT = PROJECT_ROOT / "models"

# ═══════════════════════════════════════════
#  数据集
# ═══════════════════════════════════════════


class ConversationDataset(Dataset):
    def __init__(self, samples: list[dict], labels: list[list[float]], tokenizer, max_len: int = 512):
        self.samples = samples
        self.labels = labels
        self.tokenizer = tokenizer
        self.max_len = max_len

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        text = "\n".join(m["content"] for m in self.samples[idx]["messages"])
        label = self.labels[idx]

        encoding = self.tokenizer.encode_plus(
            text,
            add_special_tokens=True,
            max_length=self.max_len,
            return_token_type_ids=False,
            padding="max_length",
            truncation=True,
            return_attention_mask=True,
            return_tensors="pt",
        )

        return {
            "input_ids": encoding["input_ids"].flatten(),
            "attention_mask": encoding["attention_mask"].flatten(),
            "labels": torch.tensor(label, dtype=torch.float),
        }


def load_data(samples_path: Path, annotations_path: Path) -> list[dict]:
    """加载样本 + 标注，归一化标签到 [0, 1]。"""
    with open(samples_path, "r", encoding="utf-8") as f:
        samples_by_id = {
            s["sample_id"]: s
            for s in [json.loads(line) for line in f if line.strip()]
        }

    with open(annotations_path, "r", encoding="utf-8") as f:
        annotations = [json.loads(line) for line in f if line.strip()]

    data = []
    for ann in annotations:
        sid = ann["sample_id"]
        if sid not in samples_by_id:
            continue
        s = samples_by_id[sid]
        labels_raw = ann["labels"]
        # 0-9 → [0, 1]
        label_norm = [labels_raw.get(l, 0) / 9.0 for l in LABELS]
        data.append({
            "sample_id": sid,
            "contact_wxid": s.get("contact_wxid", ""),
            "messages": s["messages"],
            "labels": label_norm,
        })

    return data


def split_by_contact(data: list[dict], val_ratio: float = 0.1, seed: int = 42) -> tuple[list[dict], list[dict], list[dict]]:
    """按联系人划分 train / val / test。"""
    rng = random.Random(seed)
    contacts = list(set(d["contact_wxid"] for d in data))
    rng.shuffle(contacts)

    n_val = max(1, int(len(contacts) * val_ratio))
    n_test = max(1, int(len(contacts) * val_ratio))

    val_contacts = set(contacts[:n_val])
    test_contacts = set(contacts[n_val:n_val + n_test])
    train_contacts = set(contacts[n_val + n_test:])

    train_data = [d for d in data if d["contact_wxid"] in train_contacts]
    val_data = [d for d in data if d["contact_wxid"] in val_contacts]
    test_data = [d for d in data if d["contact_wxid"] in test_contacts]

    print(f"联系人: {len(contacts)} total → "
          f"{len(train_contacts)} train / {len(val_contacts)} val / {len(test_contacts)} test")
    print(f"样本: {len(train_data)} / {len(val_data)} / {len(test_data)}")

    return train_data, val_data, test_data


# ═══════════════════════════════════════════
#  模型
# ═══════════════════════════════════════════


class MacBERTRegressor(nn.Module):
    def __init__(self, model_name: str = DEFAULT_MODEL, num_labels: int = 10):
        super().__init__()
        self.bert = AutoModel.from_pretrained(model_name)
        self.dropout = nn.Dropout(0.3)
        self.regressor = nn.Linear(self.bert.config.hidden_size, num_labels)

    def forward(self, input_ids, attention_mask):
        outputs = self.bert(input_ids=input_ids, attention_mask=attention_mask)
        cls_output = outputs.last_hidden_state[:, 0, :]
        cls_output = self.dropout(cls_output)
        logits = self.regressor(cls_output)
        return torch.sigmoid(logits)  # [0, 1]


# ═══════════════════════════════════════════
#  训练
# ═══════════════════════════════════════════


def train_epoch(model, loader, loss_fn, optimizer, scheduler, device):
    model.train()
    total_loss = 0
    for batch in loader:
        input_ids = batch["input_ids"].to(device)
        attention_mask = batch["attention_mask"].to(device)
        labels = batch["labels"].to(device)

        optimizer.zero_grad()
        preds = model(input_ids, attention_mask)
        loss = loss_fn(preds, labels)
        loss.backward()
        optimizer.step()
        scheduler.step()
        total_loss += loss.item() * input_ids.size(0)

    return total_loss / len(loader.dataset)


def evaluate(model, loader, loss_fn, device):
    model.eval()
    total_loss = 0
    all_preds = []
    all_labels = []

    with torch.no_grad():
        for batch in loader:
            input_ids = batch["input_ids"].to(device)
            attention_mask = batch["attention_mask"].to(device)
            labels = batch["labels"].to(device)

            preds = model(input_ids, attention_mask)
            loss = loss_fn(preds, labels)
            total_loss += loss.item() * input_ids.size(0)

            all_preds.extend(preds.cpu().numpy())
            all_labels.extend(labels.cpu().numpy())

    avg_loss = total_loss / len(loader.dataset)
    return avg_loss, np.array(all_preds), np.array(all_labels)


# ═══════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════


def main():
    parser = argparse.ArgumentParser(description="MacBERT 多标签回归训练")
    parser.add_argument("--samples", default=str(DEFAULT_SAMPLES))
    parser.add_argument("--annotations", default=str(DEFAULT_ANNOTATIONS))
    parser.add_argument("--model-name", default=DEFAULT_MODEL)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--lr", type=float, default=2e-5)
    parser.add_argument("--patience", type=int, default=5)
    parser.add_argument("--val-split", type=float, default=0.1)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    # 固定随机种子
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    # ── 加载数据 ──
    samples_path = Path(args.samples)
    annotations_path = Path(args.annotations)

    if not samples_path.exists():
        print(f"错误：找不到 {samples_path}")
        print("请先运行: python scripts/prepare_training_data.py")
        return

    data = load_data(samples_path, annotations_path)
    print(f"加载 {len(data)} 条标注数据")

    train_data, val_data, test_data = split_by_contact(
        data, val_ratio=args.val_split, seed=args.seed
    )

    # ── Tokenizer ──
    tokenizer = AutoTokenizer.from_pretrained(args.model_name)

    train_ds = ConversationDataset(
        train_data, [d["labels"] for d in train_data], tokenizer
    )
    val_ds = ConversationDataset(
        val_data, [d["labels"] for d in val_data], tokenizer
    )
    test_ds = ConversationDataset(
        test_data, [d["labels"] for d in test_data], tokenizer
    )

    train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True)
    val_loader = DataLoader(val_ds, batch_size=args.batch_size)
    test_loader = DataLoader(test_ds, batch_size=args.batch_size)

    # ── 设备 ──
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"设备: {device}")
    if device.type == "cuda":
        print(f"  GPU: {torch.cuda.get_device_name(0)}")
        print(f"  显存: {torch.cuda.get_device_properties(0).total_mem / 1e9:.1f} GB")

    # ── 模型 ──
    model = MacBERTRegressor(model_name=args.model_name)
    model = model.to(device)

    loss_fn = nn.MSELoss()
    optimizer = AdamW(model.parameters(), lr=args.lr)
    total_steps = len(train_loader) * args.epochs
    scheduler = get_linear_schedule_with_warmup(
        optimizer, num_warmup_steps=int(0.05 * total_steps), num_training_steps=total_steps
    )

    # ── 训练循环 ──
    best_val_loss = float("inf")
    patience_counter = 0

    print(f"\n开始训练 ({args.epochs} epochs, {len(train_loader)} batches/epoch)...")
    print(f"{'Epoch':>6} {'Train Loss':>11} {'Val Loss':>10}")

    for epoch in range(args.epochs):
        train_loss = train_epoch(model, train_loader, loss_fn, optimizer, scheduler, device)
        val_loss, _, _ = evaluate(model, val_loader, loss_fn, device)

        marker = " "
        if val_loss < best_val_loss:
            best_val_loss = val_loss
            torch.save(model.state_dict(), output_dir / "macbert_best.pt")
            patience_counter = 0
            marker = "✓"
        else:
            patience_counter += 1
            marker = "✗"

        print(f"{epoch + 1:>4}/{args.epochs}  {train_loss:.6f}  {val_loss:.6f}  {marker}")

        if patience_counter >= args.patience:
            print(f"早停于 epoch {epoch + 1}")
            break

    # ── 测试集评估 ──
    print(f"\n{'=' * 60}")
    print("测试集评估（归一化空间）")
    print(f"{'=' * 60}")

    best_path = output_dir / "macbert_best.pt"
    if best_path.exists():
        model.load_state_dict(torch.load(best_path, map_location=device))

    _, test_preds, test_labels = evaluate(model, test_loader, loss_fn, device)

    from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

    per_label = {}
    for i, label in enumerate(LABELS):
        mae = mean_absolute_error(test_labels[:, i], test_preds[:, i])
        mse = mean_squared_error(test_labels[:, i], test_preds[:, i])
        r2 = r2_score(test_labels[:, i], test_preds[:, i])
        per_label[label] = {"MAE": round(float(mae), 4), "MSE": round(float(mse), 6), "R2": round(float(r2), 4)}
        print(f"  {label:>25}: MAE={mae:.4f}  MSE={mse:.6f}  R²={r2:+.4f}")

    overall_mae = mean_absolute_error(test_labels, test_preds)
    overall_mse = mean_squared_error(test_labels, test_preds)
    overall_r2 = r2_score(test_labels, test_preds)
    print(f"\n  {'Overall':>25}: MAE={overall_mae:.4f}  MSE={overall_mse:.6f}  R²={overall_r2:+.4f}")

    # ── 保存评估报告 + 标签配置 ──
    report = {
        "overall": {"MAE": round(float(overall_mae), 4), "MSE": round(float(overall_mse), 6), "R2": round(float(overall_r2), 4)},
        "per_label": per_label,
        "config": {
            "train_samples": len(train_data),
            "val_samples": len(val_data),
            "test_samples": len(test_data),
            "train_contacts": len(set(d["contact_wxid"] for d in train_data)),
            "test_contacts": len(set(d["contact_wxid"] for d in test_data)),
            "epochs": epoch + 1,
            "batch_size": args.batch_size,
            "lr": args.lr,
        },
    }

    with open(output_dir / "eval_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # 保存标签配置
    with open(output_dir / "labels.json", "w", encoding="utf-8") as f:
        json.dump({"labels": LABELS, "num_labels": len(LABELS)}, f, ensure_ascii=False, indent=2)

    # 保存 tokenizer（供 ONNX 导出使用）
    tokenizer.save_pretrained(output_dir)

    print(f"\n结果保存至: {output_dir}")
    print("训练完成。")


if __name__ == "__main__":
    main()
