#!/usr/bin/env python3
"""B2 角色平衡训练 — her-side 全量数据 + 成对 her/me 监督。

与 B0'/B1' 的区别：
  - 加载 B2 成对数据，对同一对话同时构造 target=her 和 target=me 样本
  - 使用 WeightedRandomSampler 平衡 me-side 样本不被 her-side 淹没
  - 评估时同时输出 her-side 测试集和 me-side held-out 指标

用法（A100）:
  cd /home2/cme_code/lm/ml
  PY=/home2/cme_code/convert/python_env/bin/python3
  $PY scripts/train_macbert_b2.py \
    --epochs 20 --batch-size 32 --lr 2e-5 \
    --split-manifest models/canonical_manifest.json \
    --b2-paired dataset/b2_paired_train.jsonl \
    --b2-held-out dataset/annotations/me_side_pilot_v1/held_out.jsonl \
    --b2-candidates dataset/annotations/me_side_pilot_v1_candidates.jsonl \
    --output models/b2_role_balanced/
"""
from __future__ import annotations

import json
import sys
import hashlib
import argparse
import random
import time
import warnings
import numpy as np
from pathlib import Path
from collections import defaultdict

import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader, WeightedRandomSampler, ConcatDataset
from torch.optim import AdamW
from transformers import AutoTokenizer, AutoModel, get_linear_schedule_with_warmup

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from ml.input_format import format_behavior_input

# 静音 spearmanr 常数输入的 warning
warnings.filterwarnings("ignore", message="An input array is constant", category=RuntimeWarning)

try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False

LABELS = [
    "information_exchange", "opinion_expression", "emotion_positive",
    "emotion_negative", "flirt", "question_asking", "self_disclosure",
    "invitation", "framing_boundary", "perfunctory",
]

DEFAULT_MODEL = "/home2/cme_code/convert/hf_cache/hfl_chinese-macbert-base"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SAMPLES = PROJECT_ROOT.parent / "data" / "ml_dataset" / "training_samples.jsonl"
DEFAULT_ANNOTATIONS = PROJECT_ROOT.parent / "data" / "ml_dataset" / "training_annotations.jsonl"
DEFAULT_OUTPUT = PROJECT_ROOT / "models"


# ── 模型（与 train_macbert.py 一致） ──


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
        return torch.sigmoid(logits)


# ── 数据集 ──


class RegularDataset(Dataset):
    """常规 her-side 数据集。target_role 固定为 her。"""

    def __init__(self, samples: list[dict], labels: list[list[float]], tokenizer,
                 max_len: int = 512):
        self.samples = samples
        self.labels = labels
        self.tokenizer = tokenizer
        self.max_len = max_len

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        msgs = self.samples[idx]["messages"]
        text = format_behavior_input(msgs, target_role="her")
        tokens = self.tokenizer(text, max_length=self.max_len, truncation=True,
                                padding="max_length", return_tensors="pt")
        return {
            "input_ids": tokens["input_ids"].squeeze(0),
            "attention_mask": tokens["attention_mask"].squeeze(0),
            "labels": torch.tensor(self.labels[idx], dtype=torch.float),
        }


class B2PairedDataset(Dataset):
    """B2 成对数据集。

    每条样本含一对 (target=her + her_label, target=me + me_label)。
    __getitem__ 随机选择 target_role，确保模型见到双侧监督。
    """

    def __init__(self, paired_records: list[dict], tokenizer, max_len: int = 512):
        self.records = paired_records
        self.tokenizer = tokenizer
        self.max_len = max_len

    def __len__(self):
        return len(self.records)

    def __getitem__(self, idx):
        rec = self.records[idx]
        msgs = rec["messages"]
        # 随机选 target_role
        side = random.choice(["her", "me"])
        pair = rec["pairs"][0] if side == "her" else rec["pairs"][1]
        text = format_behavior_input(msgs, target_role=side)
        tokens = self.tokenizer(text, max_length=self.max_len, truncation=True,
                                padding="max_length", return_tensors="pt")
        label_vals = [pair["labels"][k] / 9.0 for k in LABELS]
        return {
            "input_ids": tokens["input_ids"].squeeze(0),
            "attention_mask": tokens["attention_mask"].squeeze(0),
            "labels": torch.tensor(label_vals, dtype=torch.float),
        }


class MesideEvalDataset(Dataset):
    """me-side held-out 评估集。用于 B2 训练中的 me-side 评估。"""

    def __init__(self, samples: list[dict], labels: list[list[float]], tokenizer,
                 target_role: str = "me", max_len: int = 512):
        self.samples = samples
        self.labels = labels
        self.tokenizer = tokenizer
        self.target_role = target_role
        self.max_len = max_len

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        msgs = self.samples[idx]["messages"]
        text = format_behavior_input(msgs, target_role=self.target_role)
        tokens = self.tokenizer(text, max_length=self.max_len, truncation=True,
                                padding="max_length", return_tensors="pt")
        return {
            "input_ids": tokens["input_ids"].squeeze(0),
            "attention_mask": tokens["attention_mask"].squeeze(0),
            "labels": torch.tensor(self.labels[idx], dtype=torch.float),
        }


# ── 加载数据 ──


def load_data(samples_path: Path, annotations_path: Path) -> list[dict]:
    """加载标注数据（与 B0' 一致）。"""
    sid_to_labels = {}
    with open(annotations_path, encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            sid = d["sample_id"]
            labels = d.get("labels", {})
            if all(k in labels for k in LABELS):
                sid_to_labels[sid] = [labels[k] / 9.0 for k in LABELS]

    samples = []
    with open(samples_path, encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            sid = d["sample_id"]
            if sid in sid_to_labels:
                d["labels"] = sid_to_labels[sid]
                samples.append(d)

    print(f"  加载 {len(samples)} 条 her-side 标注数据")
    return samples


def load_b2_paired(path: Path) -> list[dict]:
    """加载 B2 成对训练数据。"""
    records = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            records.append(json.loads(line))
    print(f"  加载 {len(records)} 条 B2 成对数据")
    return records


def load_meside_heldout(heldout_path: Path,
                         candidates_path: Path | None = None) -> tuple[list[dict], list[list[float]]]:
    """加载 me-side held-out 评估集。

    held_out.jsonl 只含 sample_id / labels，messages 需从 candidates 回填。
    如果 candidates_path 不为 None，按 sample_id 查找消息。
    """
    # 加载 held-out 标注
    held_records = {}
    with open(heldout_path, encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            if d.get("discard"):
                continue
            labels = d.get("labels", {})
            if all(k in labels for k in LABELS):
                held_records[d["sample_id"]] = [labels[k] / 9.0 for k in LABELS]

    # 加载候选（含 messages / contact_wxid）
    if candidates_path and candidates_path.exists():
        cands = {}
        with open(candidates_path, encoding="utf-8") as f:
            for line in f:
                c = json.loads(line)
                cands[c["sample_id"]] = c
        print(f"  候选集: {len(cands)} 条")
    else:
        cands = {}

    samples = []
    for sid, label_vals in held_records.items():
        if sid in cands:
            samples.append({
                "messages": cands[sid].get("messages", []),
                "contact_wxid": cands[sid].get("contact_wxid", "?"),
                "labels": label_vals,
            })
        else:
            # 兜底：用空 messages（会在 eval 时报 warning）
            print(f"  警告: {sid} 不在候选集中，使用空消息")
            samples.append({
                "messages": [],
                "contact_wxid": "?",
                "labels": label_vals,
            })

    labels = [s.pop("labels") for s in samples]
    print(f"  加载 {len(samples)} 条 me-side held-out 评估集（含文本）")
    return samples, labels


# ── 评估（与 train_macbert.py 一致） ──


def evaluate(model, loader, loss_fn, device, name="val"):
    model.eval()
    total_loss = 0
    all_preds = []
    all_labels = []
    total_batches = len(loader)
    start_time = time.time()

    with torch.no_grad():
        iterator = tqdm(loader, desc=f"  {name}", unit="batch") if HAS_TQDM else loader
        for batch in iterator:
            input_ids = batch["input_ids"].to(device)
            attention_mask = batch["attention_mask"].to(device)
            labels = batch["labels"].to(device)

            preds = model(input_ids, attention_mask)
            loss = loss_fn(preds, labels)
            total_loss += loss.item() * input_ids.size(0)

            all_preds.extend(preds.cpu().numpy())
            all_labels.extend(labels.cpu().numpy())

    avg_loss = total_loss / len(loader.dataset)
    elapsed = time.time() - start_time
    return avg_loss, np.array(all_preds), np.array(all_labels), elapsed


def format_eval_report(preds: np.ndarray, labels: np.ndarray,
                       contacts: list[str] | None = None) -> dict:
    """将预测和标签格式化为评估报告。"""
    from sklearn.metrics import mean_absolute_error, r2_score
    from scipy.stats import spearmanr

    preds_score = preds * 9.0
    labels_score = labels * 9.0

    overall_mae = float(mean_absolute_error(labels_score, preds_score))
    overall_r2 = float(r2_score(labels_score, preds_score))
    try:
        sp, _ = spearmanr(labels_score.ravel(), preds_score.ravel())
    except Exception:
        sp = 0.0

    report = {
        "overall": {
            "MAE_score": round(overall_mae, 2),
            "R2": round(overall_r2, 4),
            "Spearman": round(float(sp), 4),
        },
        "per_label": {},
    }

    for i, label in enumerate(LABELS):
        yt = labels_score[:, i]
        yp = preds_score[:, i]
        mae_l = float(mean_absolute_error(yt, yp))
        r2_l = float(r2_score(yt, yp))
        try:
            sp_l, _ = spearmanr(yt, yp)
        except Exception:
            sp_l = 0.0
        report["per_label"][label] = {
            "MAE_score": round(mae_l, 2),
            "R2": round(r2_l, 4),
            "Spearman": round(sp_l, 4),
        }

    # Contact-Macro（可选）
    if contacts:
        contact_preds = defaultdict(list)
        contact_labels = defaultdict(list)
        for i, cid in enumerate(contacts):
            contact_preds[cid].append(preds_score[i])
            contact_labels[cid].append(labels_score[i])
        contact_maes = [
            float(mean_absolute_error(np.array(contact_labels[cid]), np.array(contact_preds[cid])))
            for cid in contact_preds
        ]
        report["overall"]["Contact_MAE_score"] = round(float(np.mean(contact_maes)), 2)

    return report


# ── 训练 + 评估主流程 ──


def main():
    parser = argparse.ArgumentParser(description="B2 角色平衡训练")
    parser.add_argument("--samples", default=str(DEFAULT_SAMPLES))
    parser.add_argument("--annotations", default=str(DEFAULT_ANNOTATIONS))
    parser.add_argument("--model-name", default=DEFAULT_MODEL)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--lr", type=float, default=2e-5)
    parser.add_argument("--patience", type=int, default=5)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--split-manifest", type=str, required=True,
                        help="划分文件（必须与 B0'/B1' 相同）")
    parser.add_argument("--b2-paired", type=str, required=True,
                        help="B2 成对训练数据（b2_paired_train.jsonl）")
    parser.add_argument("--b2-held-out", type=str, required=True,
                        help="me-side held-out 评估集（仅标注，无消息）")
    parser.add_argument("--b2-candidates", type=str, required=True,
                        help="me-side 候选集（含 messages/contact_wxid，用于回填 held-out 文本）")
    parser.add_argument("--init-checkpoint", type=str, default=None,
                        help="从旧 B0'/B1' checkpoint 初始化（可选）")
    parser.add_argument("--b2-upsample", type=float, default=20.0,
                        help="B2 数据上采样倍率（默认 20x → B2 约占 31%；44x 可达 50%）")
    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"设备: {device}")
    if device.type == "cuda":
        print(f"  GPU: {torch.cuda.get_device_name(0)}")
        print(f"  显存: {torch.cuda.get_device_properties(0).total_memory / 1e9:.1f} GB")

    # ── 加载数据 ──
    print("\n加载 her-side 数据...")
    data = load_data(Path(args.samples), Path(args.annotations))

    print("加载 B2 成对数据...")
    b2_records = load_b2_paired(Path(args.b2_paired))

    print("加载 me-side held-out...")
    cand_path = Path(args.b2_candidates)
    held_samples, held_labels = load_meside_heldout(Path(args.b2_held_out), cand_path)

    # ── 划分（复用 canonical manifest）──
    manifest_path = Path(args.split_manifest)
    if not manifest_path.exists():
        print(f"错误: split-manifest 不存在 {manifest_path}")
        sys.exit(1)
    print(f"加载划分: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    train_contacts = set(manifest["train_contacts"])
    val_contacts = set(manifest["val_contacts"])
    test_contacts = set(manifest["test_contacts"])

    # ── 设置随机种子 ──
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)

    train_data = [d for d in data if d["contact_wxid"] in train_contacts]
    val_data = [d for d in data if d["contact_wxid"] in val_contacts]
    test_data = [d for d in data if d["contact_wxid"] in test_contacts]
    print(f"her-side: {len(train_data)} train / {len(val_data)} val / {len(test_data)} test")

    # ── 加载 me-side held-out 的联系人列表（用于 contact-macro）──
    held_contacts = [s.get("contact_wxid", "?") for s in held_samples]

    # ── Tokenizer ──
    print("\n加载 tokenizer...")
    if (output_dir / "tokenizer.json").exists():
        tokenizer = AutoTokenizer.from_pretrained(str(output_dir))
        print(f"  从 {output_dir} 加载已有 tokenizer")
    else:
        tokenizer = AutoTokenizer.from_pretrained(args.model_name)
        # 注册 [TARGET]/[OTHER] token
        special_tokens = {"additional_special_tokens": ["[TARGET]", "[OTHER]"]}
        tokenizer.add_special_tokens(special_tokens)
        tokenizer.save_pretrained(str(output_dir))
        print(f"  注册 [TARGET]/[OTHER] 并保存到 {output_dir}")

    # ── 数据集 ──
    train_labels = [d["labels"] for d in train_data]
    val_labels = [d["labels"] for d in val_data]
    test_labels = [d["labels"] for d in test_data]

    train_regular = RegularDataset(train_data, train_labels, tokenizer)
    val_ds = RegularDataset(val_data, val_labels, tokenizer)
    test_ds = RegularDataset(test_data, test_labels, tokenizer)
    b2_ds = B2PairedDataset(b2_records, tokenizer)

    # me-side held-out 评估（target="me"）
    held_ds = MesideEvalDataset(held_samples, held_labels, tokenizer, target_role="me")

    # ── 合并训练集 + 平衡采样 ──
    # regular 权重 = 1，B2 权重 = upsample 倍率
    n_regular = len(train_regular)
    n_b2 = len(b2_ds)
    b2_weight = args.b2_upsample
    weights = [1.0] * n_regular + [b2_weight] * n_b2
    combined = ConcatDataset([train_regular, b2_ds])

    sampler = WeightedRandomSampler(
        weights=weights,
        num_samples=len(combined),
        replacement=True,
    )
    train_loader = DataLoader(
        combined, batch_size=args.batch_size, sampler=sampler,
        num_workers=0,  # Windows 兼容
    )
    val_loader = DataLoader(val_ds, batch_size=args.batch_size)
    test_loader = DataLoader(test_ds, batch_size=args.batch_size)
    held_loader = DataLoader(held_ds, batch_size=args.batch_size)

    # 采样统计
    epoch_batches = len(train_loader)
    expected_regular_per_epoch = epoch_batches * args.batch_size * (n_regular / (n_regular + n_b2 * b2_weight))
    expected_b2_per_epoch = epoch_batches * args.batch_size * (n_b2 * b2_weight / (n_regular + n_b2 * b2_weight))
    print(f"\n训练集: {n_regular} regular + {n_b2} B2 paired (upsample={b2_weight}x)")
    print(f"  每 epoch batch: {epoch_batches}")
    print(f"  预期每 epoch: regular≈{expected_regular_per_epoch:.0f}  B2≈{expected_b2_per_epoch:.0f}")

    # ── 模型 ──
    model = MacBERTRegressor(model_name=args.model_name, num_labels=len(LABELS))
    model.bert.resize_token_embeddings(len(tokenizer))

    if args.init_checkpoint:
        ckpt_path = Path(args.init_checkpoint)
        if not ckpt_path.exists():
            print(f"错误: init_checkpoint 不存在 {ckpt_path}")
            sys.exit(1)
        print(f"从 checkpoint 初始化: {ckpt_path}")
        checkpoint = torch.load(ckpt_path, map_location="cpu", weights_only=True)
        model_dict = model.state_dict()
        # 只加载 key 存在且 shape 匹配的参数（跳过词表大小不同导致的 shape 不匹配）
        filtered = {k: v for k, v in checkpoint.items()
                    if k in model_dict and v.shape == model_dict[k].shape}
        skipped = [k for k in checkpoint if k not in filtered]
        model.load_state_dict(filtered, strict=False)
        print(f"  loaded {len(filtered)} keys, skipped {len(skipped)} (shape mismatch)")

    model = model.to(device)

    # ── 优化器 ──
    optimizer = AdamW(model.parameters(), lr=args.lr)
    total_steps = args.epochs * len(train_loader)
    scheduler = get_linear_schedule_with_warmup(
        optimizer, num_warmup_steps=int(0.1 * total_steps), num_training_steps=total_steps,
    )
    loss_fn = nn.MSELoss()

    # ── 训练 ──
    best_val_loss = float("inf")
    patience_counter = 0
    ckpt_name = "macbert_best.pt"
    best_path = output_dir / ckpt_name

    print(f"\n{'='*60}")
    print(f"开始训练 ({args.epochs} epochs, batch={args.batch_size}, lr={args.lr})")
    print(f"{'='*60}")

    for epoch in range(1, args.epochs + 1):
        model.train()
        total_loss = 0
        start_time = time.time()

        iterator = tqdm(train_loader, desc=f"Epoch {epoch}/{args.epochs}",
                        unit="batch") if HAS_TQDM else train_loader

        for batch in iterator:
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

        train_loss = total_loss / len(train_loader.dataset)
        train_time = time.time() - start_time

        # ── Val ──
        val_loss, _, _, val_time = evaluate(model, val_loader, loss_fn, device, name="val")

        # ── Me-side held-out ──
        held_loss, held_preds, held_labels_arr, _ = evaluate(
            model, held_loader, loss_fn, device, name="held"
        )
        held_report = format_eval_report(held_preds, held_labels_arr, contacts=held_contacts)

        lr_now = scheduler.get_last_lr()[0]
        flag = "✓" if val_loss < best_val_loss else " "

        # 进度输出
        time_str = f"Epoch time: {train_time:.0f}s train + {val_time:.0f}s val"
        print(f"  {epoch:>3}/{args.epochs:>3}  |  {train_loss:.4f}  |  {val_loss:.4f}  |"
              f"  {train_time + val_time:.0f}s  |  {lr_now:.2e}  |{flag}")
        print(f"  {'':>25}held MAE={held_report['overall']['MAE_score']:.2f}"
              f" | {time_str}")

        # ── 早停 ──
        if val_loss < best_val_loss:
            best_val_loss = val_loss
            patience_counter = 0
            torch.save(model.state_dict(), best_path)
            print(f"  ✓ 新 best model 已保存 ({best_path})")
        else:
            patience_counter += 1
            if patience_counter >= args.patience:
                print(f"  早停: val loss {args.patience} epoch 未下降")
                break

    # ── 最终评估 ──
    print(f"\n{'='*60}")
    print(f"加载 best checkpoint 做最终评估...")
    model.load_state_dict(torch.load(best_path, map_location=device))
    model.eval()

    # her-side 测试集
    _, test_preds, test_labels_arr, _ = evaluate(model, test_loader, loss_fn, device, "test")
    test_report = format_eval_report(test_preds, test_labels_arr)
    print(f"\nher-side 测试集:")
    for label in LABELS:
        p = test_report["per_label"][label]
        print(f"  {label:>25}: MAE={p['MAE_score']:.2f}  R2={p['R2']:+.4f}  Sp={p['Spearman']:+.4f}")
    o = test_report["overall"]
    print(f"  {'Overall':>25}: MAE={o['MAE_score']:.2f}  R2={o['R2']:+.4f}  Sp={o['Spearman']:+.4f}")

    # me-side held-out（用 best checkpoint 重新评估）
    _, held_preds, held_labels_arr, _ = evaluate(
        model, held_loader, loss_fn, device, name="held"
    )
    held_report = format_eval_report(held_preds, held_labels_arr, contacts=held_contacts)

    print(f"\nme-side held-out (target_role='me'):")
    for label in LABELS:
        p = held_report["per_label"][label]
        print(f"  {label:>25}: MAE={p['MAE_score']:.2f}  R2={p['R2']:+.4f}  Sp={p['Spearman']:+.4f}")
    ho = held_report["overall"]
    print(f"  {'Overall':>25}: MAE={ho['MAE_score']:.2f}"
          f"  R2={ho['R2']:+.4f}  Sp={ho['Spearman']:+.4f}"
          f"  Contact-MAE={ho.get('Contact_MAE_score', '?'):.2f}")

    # ── 保存报告 ──
    report_path = output_dir / "eval_report.json"
    held_report_path = output_dir / "me_side_held_out_report.json"

    with open(held_report_path, "w", encoding="utf-8") as f:
        json.dump(held_report, f, ensure_ascii=False, indent=2)

    full_report = {
        "experiment": "B2_role_balanced",
        "her_side": test_report,
        "me_side_held_out": held_report,
        "config": {
            "epochs": epoch,
            "batch_size": args.batch_size,
            "lr": args.lr,
            "b2_upsample": args.b2_upsample,
            "init_checkpoint": args.init_checkpoint,
        },
        "manifest": {
            "path": args.split_manifest,
        },
    }

    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(full_report, f, ensure_ascii=False, indent=2)
    print(f"\n报告已保存: {report_path}")
    print(f"me-side held-out 报告已保存: {held_report_path}")


if __name__ == "__main__":
    main()
