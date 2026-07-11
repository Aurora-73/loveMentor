# -*- coding: utf-8 -*-
import json
import argparse
import numpy as np
from pathlib import Path

import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from torch.optim import AdamW
from transformers import AutoTokenizer, AutoModel, get_linear_schedule_with_warmup

LABELS = ["information_exchange", "opinion_expression", "emotion_positive", "emotion_negative", "flirt", "question_asking", "self_disclosure", "invitation", "framing_boundary", "perfunctory"]


class ConversationDataset(Dataset):
    def __init__(self, samples, labels, tokenizer, max_len=512):
        self.samples = samples
        self.labels = labels
        self.tokenizer = tokenizer
        self.max_len = max_len

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        messages = self.samples[idx]["messages"]
        text = "\n".join(m["content"] for m in messages)
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


class MacBERTRegressor(nn.Module):
    """多标签回归模型：输出 0-9 归一化后的 [0,1] 连续值"""

    def __init__(self, model_name="/home2/cme_code/convert/hf_cache/hfl_chinese-macbert-base", num_labels=10):
        super().__init__()
        self.bert = AutoModel.from_pretrained(model_name)
        self.dropout = nn.Dropout(0.3)
        self.regressor = nn.Linear(self.bert.config.hidden_size, num_labels)

    def forward(self, input_ids, attention_mask):
        outputs = self.bert(input_ids=input_ids, attention_mask=attention_mask)
        cls_output = outputs.last_hidden_state[:, 0, :]
        cls_output = self.dropout(cls_output)
        logits = self.regressor(cls_output)
        return torch.sigmoid(logits)  # 约束到 [0, 1]，对应归一化后的标签


def load_data(samples_path, annotations_path):
    with open(samples_path, "r", encoding="utf-8") as f:
        samples = {s["sample_id"]: s for s in [json.loads(line) for line in f if line.strip()]}

    with open(annotations_path, "r", encoding="utf-8") as f:
        annotations = [json.loads(line) for line in f if line.strip()]

    data = []
    for ann in annotations:
        sample_id = ann["sample_id"]
        if sample_id in samples:
            labels = ann["labels"]
            # 0-9 整数值归一化到 [0, 1]
            label_array = [labels.get(l, 0) / 9.0 for l in LABELS]
            data.append({
                "sample_id": sample_id,
                "contact_wxid": samples[sample_id].get("contact_wxid", ""),
                "messages": samples[sample_id]["messages"],
                "labels": label_array,
            })
    return data


def split_by_contact(data, test_size=0.2):
    contacts = list(set(d["contact_wxid"] for d in data))
    train_contacts, test_contacts = train_test_split(contacts, test_size=test_size, random_state=42)

    train_data = [d for d in data if d["contact_wxid"] in train_contacts]
    test_data = [d for d in data if d["contact_wxid"] in test_contacts]

    print(f"Total contacts: {len(contacts)}")
    print(f"Train contacts: {len(train_contacts)}, samples: {len(train_data)}")
    print(f"Test contacts: {len(test_contacts)}, samples: {len(test_data)}")

    return train_data, test_data


def train_epoch(model, data_loader, loss_fn, optimizer, scheduler, device):
    model.train()
    total_loss = 0
    for batch in data_loader:
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

    return total_loss / len(data_loader.dataset)


def eval_model(model, data_loader, loss_fn, device):
    model.eval()
    total_loss = 0
    all_preds = []
    all_labels = []

    with torch.no_grad():
        for batch in data_loader:
            input_ids = batch["input_ids"].to(device)
            attention_mask = batch["attention_mask"].to(device)
            labels = batch["labels"].to(device)

            preds = model(input_ids, attention_mask)
            loss = loss_fn(preds, labels)
            total_loss += loss.item() * input_ids.size(0)

            all_preds.extend(preds.cpu().numpy())
            all_labels.extend(labels.cpu().numpy())

    avg_loss = total_loss / len(data_loader.dataset)
    return avg_loss, np.array(all_preds), np.array(all_labels)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", default=None)
    parser.add_argument("--annotations", default=None)
    parser.add_argument("--output", default=None)
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--patience", type=int, default=3)
    parser.add_argument("--batch_size", type=int, default=16)
    parser.add_argument("--lr", type=float, default=2e-5)
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent.parent
    dataset_dir = project_root / "data" / "ml_dataset"
    samples_path = Path(args.samples) if args.samples else dataset_dir / "samples_phase0.jsonl"
    annotations_path = Path(args.annotations) if args.annotations else dataset_dir / "annotations_phase1.jsonl"
    output_dir = Path(args.output) if args.output else project_root / "ml" / "models"

    output_dir.mkdir(parents=True, exist_ok=True)

    data = load_data(samples_path, annotations_path)
    print(f"Loaded {len(data)} annotated samples (label range 0-9, normalized to 0-1)")

    train_data, test_data = split_by_contact(data)

    tokenizer = AutoTokenizer.from_pretrained("/home2/cme_code/convert/hf_cache/hfl_chinese-macbert-base")

    train_samples = [d for d in train_data]
    train_labels = [d["labels"] for d in train_data]
    test_samples = [d for d in test_data]
    test_labels = [d["labels"] for d in test_data]

    train_dataset = ConversationDataset(train_samples, train_labels, tokenizer)
    test_dataset = ConversationDataset(test_samples, test_labels, tokenizer)

    train_loader = DataLoader(train_dataset, batch_size=args.batch_size, shuffle=True)
    test_loader = DataLoader(test_dataset, batch_size=args.batch_size, shuffle=False)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Using device: {device}")

    model = MacBERTRegressor()
    model = model.to(device)

    loss_fn = nn.MSELoss()
    optimizer = AdamW(model.parameters(), lr=args.lr)
    total_steps = len(train_loader) * args.epochs
    scheduler = get_linear_schedule_with_warmup(optimizer, num_warmup_steps=0, num_training_steps=total_steps)

    best_val_loss = float("inf")
    patience_counter = 0
    for epoch in range(args.epochs):
        print(f"\nEpoch {epoch + 1}/{args.epochs}")
        train_loss = train_epoch(model, train_loader, loss_fn, optimizer, scheduler, device)
        val_loss, val_preds, val_labels = eval_model(model, test_loader, loss_fn, device)

        print(f"Train loss: {train_loss:.6f}")
        print(f"Val loss: {val_loss:.6f}")

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            torch.save(model.state_dict(), output_dir / "macbert_best.pt")
            patience_counter = 0
            print("✓ Saved best model (val loss improved)")
        else:
            patience_counter += 1
            print(f"✗ No improvement ({patience_counter}/{args.patience})")
            if patience_counter >= args.patience:
                print(f"Early stopping triggered after {epoch+1} epochs")
                break

    best_path = output_dir / "macbert_best.pt"
    if best_path.exists():
        model.load_state_dict(torch.load(best_path, weights_only=True))
    _, test_preds, test_labels = eval_model(model, test_loader, loss_fn, device)

    # 回归报告：MAE / MSE / R²（归一化空间）
    print("\nRegression Report (normalized 0-1 space, per-label):")
    for i, label in enumerate(LABELS):
        mae = mean_absolute_error(test_labels[:, i], test_preds[:, i])
        mse = mean_squared_error(test_labels[:, i], test_preds[:, i])
        r2 = r2_score(test_labels[:, i], test_preds[:, i])
        print(f"  {label}: MAE={mae:.4f}, MSE={mse:.4f}, R²={r2:+.4f}")

    overall_mae = mean_absolute_error(test_labels, test_preds)
    overall_mse = mean_squared_error(test_labels, test_preds)
    overall_r2 = r2_score(test_labels, test_preds)
    print(f"\n  Overall: MAE={overall_mae:.4f}, MSE={overall_mse:.4f}, R²={overall_r2:+.4f}")

    report = {
        "overall": {"MAE": float(overall_mae), "MSE": float(overall_mse), "R2": float(overall_r2)},
        "per_label": {},
    }
    for i, label in enumerate(LABELS):
        report["per_label"][label] = {
            "MAE": float(mean_absolute_error(test_labels[:, i], test_preds[:, i])),
            "MSE": float(mean_squared_error(test_labels[:, i], test_preds[:, i])),
            "R2": float(r2_score(test_labels[:, i], test_preds[:, i])),
        }

    with open(output_dir / "eval_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    tokenizer.save_pretrained(output_dir)
    print(f"\nResults saved to {output_dir}")


if __name__ == "__main__":
    main()
