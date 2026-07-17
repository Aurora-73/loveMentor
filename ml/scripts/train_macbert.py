#!/usr/bin/env python3
"""MacBERT 多标签/单标签回归训练 — 13,676 条标注数据集。

用法:
  cd /home2/cme_code/lm/ml && export PY=/home2/cme_code/convert/python_env/bin/python3

  # 截断率检查（不训练）
  $PY scripts/train_macbert.py --check-truncation

  # 多标签训练（全部 10 标签）
  $PY scripts/train_macbert.py --epochs 20 --batch-size 32 --lr 2e-5

  # 单标签训练（推荐 — 各标签独立早停）
  $PY scripts/train_macbert.py --label perfunctory --epochs 30 --batch-size 32

  # 复用已保存的联系人划分
  $PY scripts/train_macbert.py --label flirt --split-manifest models/split_manifest.json

参数:
  --samples        训练样本文件（默认 dataset/training_samples.jsonl）
  --annotations    标注文件（默认 dataset/training_annotations.jsonl）
  --model-name     MacBERT 模型路径（默认预训练缓存路径）
  --output         模型输出目录（默认 models/）
  --epochs         训练轮数（默认 20）
  --batch-size     batch size（默认 32）
  --lr             学习率（默认 2e-5）
  --patience       早停耐心值（默认 5）
  --val-split      验证集比例（默认 0.1）
  --seed           随机种子（默认 42）
  --label          训练单个标签（如 --label flirt，默认 None=全部）
  --split-manifest 复用已保存的划分 JSON（所有实验共用同一划分）
  --check-truncation 仅检查 tokenizer 截断率，不训练

变更:
  2026-07-13 去重 + sorted() + [TARGET]/[OTHER] 角色前缀 + 固定划分 + 0-9 评估 + 截断检查
  2026-07-12 分层采样 + --label 单标签模式 + 进度条
"""
from __future__ import annotations

import json
import sys
import hashlib
import argparse
import random
import time
import numpy as np
from pathlib import Path
from collections import defaultdict

import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader
from torch.optim import AdamW
from transformers import AutoTokenizer, AutoModel, get_linear_schedule_with_warmup

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # 添加项目根路径以支持 ml.input_format
from ml.input_format import format_behavior_input

try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False
    print("提示: pip install tqdm 可获得进度条")

LABELS = [
    "information_exchange", "opinion_expression", "emotion_positive",
    "emotion_negative", "flirt", "question_asking", "self_disclosure",
    "invitation", "framing_boundary", "perfunctory",
]
LABEL_ALIASES = {
    "info_exchange": "information_exchange",
    "opinion": "opinion_expression",
    "pos_emotion": "emotion_positive",
    "neg_emotion": "emotion_negative",
    "question": "question_asking",
    "self_disc": "self_disclosure",
    "boundary": "framing_boundary",
}

# ── 预训练模型路径（A100 本地缓存）──
DEFAULT_MODEL = "/home2/cme_code/convert/hf_cache/hfl_chinese-macbert-base"

# ── 默认数据路径（相对于项目根目录）──
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SAMPLES = PROJECT_ROOT.parent / "data" / "ml_dataset" / "training_samples.jsonl"
DEFAULT_ANNOTATIONS = PROJECT_ROOT.parent / "data" / "ml_dataset" / "training_annotations.jsonl"
DEFAULT_OUTPUT = PROJECT_ROOT / "models"

# ═══════════════════════════════════════════
#  数据集
# ═══════════════════════════════════════════


class ConversationDataset(Dataset):
    def __init__(self, samples: list[dict], labels: list[list[float]], tokenizer,
                 max_len: int = 512, use_role_prefix: bool = False):
        self.samples = samples
        self.labels = labels
        self.tokenizer = tokenizer
        self.max_len = max_len
        self.use_role_prefix = use_role_prefix

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        if self.use_role_prefix:
            text = format_behavior_input(self.samples[idx]["messages"], target_role="her")
        else:
            lines = [m["content"] if isinstance(m, dict) else str(m) for m in self.samples[idx]["messages"]]
            text = "\n".join(lines)
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


def load_data(samples_path: Path, annotations_path: Path, label: str | None = None) -> list[dict]:
    """加载样本 + 标注，归一化标签到 [0, 1]。
    从 training_samples.jsonl 读取 from_clean_set 标记供分层采样使用。

    如果 label 指定，只加载该标签的分数（单标签训练用）。
    """
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

        if label:
            label_norm = [labels_raw.get(label, 0) / 9.0]
        else:
            label_norm = [labels_raw.get(l, 0) / 9.0 for l in LABELS]

        data.append({
            "sample_id": sid,
            "contact_wxid": s.get("contact_wxid", ""),
            "messages": s["messages"],
            "labels": label_norm,
            "from_clean_set": s.get("from_clean_set", False),
            "active_labels": [label] if label else LABELS,
        })

    return data


def split_by_contact(data: list[dict], val_ratio: float = 0.1, seed: int = 42) -> tuple[list[dict], list[dict], list[dict]]:
    """按联系人分层划分 train / val / test。

    将 2099 原始洁净样本和新增样本的联系人分组后各自随机采样，
    保证两类样本在各集合中都有分布。
    """
    rng = random.Random(seed)

    # 按是否含 2099 原始样本将联系人分组
    clean_contacts: set[str] = set()
    new_contacts: set[str] = set()
    for d in data:
        if d.get("from_clean_set"):
            clean_contacts.add(d["contact_wxid"])
        else:
            new_contacts.add(d["contact_wxid"])

    # 如果一个联系人既有洁净样本又有新增，归入洁净组
    new_contacts -= clean_contacts

    clean_list = sorted(clean_contacts)
    new_list = sorted(new_contacts)
    rng.shuffle(clean_list)
    rng.shuffle(new_list)

    def split_group(contacts, ratio):
        n_val = max(1, int(len(contacts) * ratio))
        n_test = max(1, int(len(contacts) * ratio))
        return (set(contacts[n_val + n_test:]),
                set(contacts[:n_val]),
                set(contacts[n_val:n_val + n_test]))

    train_clean, val_clean, test_clean = split_group(clean_list, val_ratio)
    train_new, val_new, test_new = split_group(new_list, val_ratio)

    train_contacts = train_clean | train_new
    val_contacts = val_clean | val_new
    test_contacts = test_clean | test_new

    train_data = [d for d in data if d["contact_wxid"] in train_contacts]
    val_data = [d for d in data if d["contact_wxid"] in val_contacts]
    test_data = [d for d in data if d["contact_wxid"] in test_contacts]

    # 统计各类样本在各集合中的分布
    def count_clean(items):
        return sum(1 for d in items if d.get("from_clean_set"))

    print(f"联系人: {len(clean_contacts)} clean / {len(new_contacts)} new → "
          f"{len(train_contacts)} train / {len(val_contacts)} val / {len(test_contacts)} test")
    print(f"样本: {len(train_data)} / {len(val_data)} / {len(test_data)}")
    print(f"2099 分布: train={count_clean(train_data)} val={count_clean(val_data)} test={count_clean(test_data)}")

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


def train_epoch(model, loader, loss_fn, optimizer, scheduler, device, epoch, total_epochs):
    model.train()
    total_loss = 0
    total_batches = len(loader)
    start_time = time.time()

    iterator = tqdm(loader, desc=f"Epoch {epoch}/{total_epochs}", unit="batch") if HAS_TQDM else loader

    for batch_idx, batch in enumerate(iterator):
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

        # 手动进度（无 tqdm 时）
        if not HAS_TQDM and (batch_idx + 1) % max(1, total_batches // 10) == 0:
            elapsed = time.time() - start_time
            batches_done = batch_idx + 1
            eta = (elapsed / batches_done) * (total_batches - batches_done)
            print(f"  [{epoch}/{total_epochs}] batch {batches_done}/{total_batches}  "
                  f"loss={loss.item():.4f}  elapsed={elapsed:.0f}s  eta={eta:.0f}s")

    avg_loss = total_loss / len(loader.dataset)
    epoch_time = time.time() - start_time
    return avg_loss, epoch_time


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


# ═══════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════


def main():
    parser = argparse.ArgumentParser(description="MacBERT 多标签/单标签回归训练 — 支持 [TARGET]/[OTHER] 角色前缀、固定划分复用")
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
    parser.add_argument("--label", type=str, default=None,
                        help="训练单个标签（默认 None=全部 10 标签）。支持别名：flirt, perfunctory, boundary, ...")
    parser.add_argument("--split-manifest", type=str, default=None,
                        help="使用已保存的划分文件（JSON），所有实验共用同一划分")
    parser.add_argument("--init-checkpoint", type=str, default=None,
                        help="从旧 checkpoint 初始化权重（不指定则从基座随机初始化）")
    parser.add_argument("--role-prefix", action="store_true",
                        help="使用 [TARGET]/[OTHER] 角色前缀（B1 实验）。默认 roleless（B0 兼容）")
    parser.add_argument("--check-truncation", action="store_true",
                        help="仅检查 tokenizer 截断率，不训练")
    parser.add_argument("--eval-only", action="store_true",
                        help="仅评估（不训练）。从 checkpoint 加载模型后直接在测试集上评估。")
    args = parser.parse_args()

    # 标签别名解析
    if args.label:
        args.label = LABEL_ALIASES.get(args.label, args.label)
        assert args.label in LABELS, f"未知标签: {args.label}，可选: {', '.join(LABELS)}"
        print(f"单标签训练模式: {args.label}")
        num_labels = 1
    else:
        print("多标签训练模式: 全部 10 个标签")
        num_labels = 10

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

    data = load_data(samples_path, annotations_path, label=args.label)
    print(f"加载 {len(data)} 条标注数据")

    # ── 联系人划分（首次生成并保存，后续复用）──
    manifest_path = Path(args.split_manifest) if args.split_manifest else output_dir / "split_manifest.json"

    if args.split_manifest and manifest_path.exists():
        # 复用已保存的划分
        print(f"加载已有划分: {manifest_path}")
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        train_contacts = set(manifest["train_contacts"])
        val_contacts = set(manifest["val_contacts"])
        test_contacts = set(manifest["test_contacts"])

        train_data = [d for d in data if d["contact_wxid"] in train_contacts]
        val_data = [d for d in data if d["contact_wxid"] in val_contacts]
        test_data = [d for d in data if d["contact_wxid"] in test_contacts]

        def count_clean(items):
            return sum(1 for d in items if d.get("from_clean_set"))
        print(f"联系人: {len(train_contacts)} train / {len(val_contacts)} val / {len(test_contacts)} test")
        print(f"样本: {len(train_data)} / {len(val_data)} / {len(test_data)}")
        print(f"2099 分布: train={count_clean(train_data)} val={count_clean(val_data)} test={count_clean(test_data)}")
    else:
        # 首次划分并保存
        train_data, val_data, test_data = split_by_contact(
            data, val_ratio=args.val_split, seed=args.seed
        )
        # 提取联系人列表
        train_contacts = sorted(set(d["contact_wxid"] for d in train_data))
        val_contacts = sorted(set(d["contact_wxid"] for d in val_data))
        test_contacts = sorted(set(d["contact_wxid"] for d in test_data))
        manifest = {
            "train_contacts": train_contacts,
            "val_contacts": val_contacts,
            "test_contacts": test_contacts,
            "val_ratio": args.val_split,
            "seed": args.seed,
        }
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        print(f"划分已保存: {manifest_path}")

    # ── Tokenizer ──
    tokenizer = AutoTokenizer.from_pretrained(args.model_name)

    # 条件性注册 [TARGET]/[OTHER] 特殊 token（B1 实验）
    if args.role_prefix:
        special_tokens_dict = {"additional_special_tokens": ["[TARGET]", "[OTHER]"]}
        num_added = tokenizer.add_special_tokens(special_tokens_dict)
        if num_added:
            print(f"添加 {num_added} 个特殊 token: [TARGET], [OTHER]")

    # ── 可选的截断率检查 ──
    if args.check_truncation:
        max_len = 512  # 与 ConversationDataset 一致
        print(f"\n检查 tokenizer 截断率（max_length={max_len}）...")
        truncated_count = 0
        for d in data:
            if args.role_prefix:
                text = format_behavior_input(d["messages"], target_role="her")
            else:
                lines = [m["content"] if isinstance(m, dict) else str(m) for m in d["messages"]]
                text = "\n".join(lines)
            tokens = tokenizer.encode(text)
            if len(tokens) > max_len:
                truncated_count += 1
        pct = 100.0 * truncated_count / len(data)
        print(f"截断: {truncated_count}/{len(data)} ({pct:.1f}%)")
        if pct > 0:
            for source_name, source_val in [("clean_2099", True), ("new", False)]:
                subset = [d for d in data if d.get("from_clean_set") == source_val]
                if subset:
                    trunc_sub = 0
                    for d in subset:
                        if args.role_prefix:
                            text = format_behavior_input(d["messages"], target_role="her")
                        else:
                            lines = [m["content"] if isinstance(m, dict) else str(m) for m in d["messages"]]
                            text = "\n".join(lines)
                        if len(tokenizer.encode(text)) > max_len:
                            trunc_sub += 1
                    print(f"  {source_name}: {trunc_sub}/{len(subset)} ({100.0*trunc_sub/len(subset):.1f}%)")
        print("检查完成。")
        return

    train_ds = ConversationDataset(
        train_data, [d["labels"] for d in train_data], tokenizer,
        use_role_prefix=args.role_prefix,
    )
    val_ds = ConversationDataset(
        val_data, [d["labels"] for d in val_data], tokenizer,
        use_role_prefix=args.role_prefix,
    )
    test_ds = ConversationDataset(
        test_data, [d["labels"] for d in test_data], tokenizer,
        use_role_prefix=args.role_prefix,
    )

    train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True)
    val_loader = DataLoader(val_ds, batch_size=args.batch_size)
    test_loader = DataLoader(test_ds, batch_size=args.batch_size)

    # ── 设备 ──
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"设备: {device}")
    if device.type == "cuda":
        print(f"  GPU: {torch.cuda.get_device_name(0)}")
        print(f"  显存: {torch.cuda.get_device_properties(0).total_memory / 1e9:.1f} GB")

    # ── 模型 ──
    model = MacBERTRegressor(model_name=args.model_name, num_labels=num_labels)
    if args.role_prefix:
        # 扩展 embedding 层以容纳 [TARGET]/[OTHER] token
        model.bert.resize_token_embeddings(len(tokenizer))

    # ── 从旧 checkpoint 初始化（可选）──
    if args.init_checkpoint:
        ckpt_path = Path(args.init_checkpoint)
        if not ckpt_path.exists():
            print(f"错误：checkpoint 不存在 {ckpt_path}")
            sys.exit(1)
        print(f"从 checkpoint 初始化: {ckpt_path}")
        checkpoint = torch.load(ckpt_path, map_location="cpu", weights_only=True)
        model_dict = model.state_dict()
        loaded = 0
        partial = 0
        skipped = 0
        for key, val in checkpoint.items():
            if key not in model_dict:
                skipped += 1
                continue
            if model_dict[key].shape == val.shape:
                model_dict[key] = val
                loaded += 1
            elif val.dim() == 2 and model_dict[key].dim() == 2:
                # 部分加载（如 embedding 扩展后前 N 行保留旧权重）
                min_rows = min(val.size(0), model_dict[key].size(0))
                min_cols = min(val.size(1), model_dict[key].size(1))
                model_dict[key][:min_rows, :min_cols] = val[:min_rows, :min_cols]
                partial += 1
                print(f"  Partial load {key}: {val.shape} -> {model_dict[key].shape}")
            else:
                skipped += 1
        model.load_state_dict(model_dict)
        print(f"  Checkpoint loaded: {loaded} full, {partial} partial, {skipped} skipped")

        # 单标签模式：从旧多标签回归头抽取对应标签行
        if args.label and "regressor.weight" in checkpoint:
            old_out = checkpoint["regressor.weight"].size(0)
            new_out = model_dict["regressor.weight"].size(0)
            if old_out > 1 and new_out == 1:
                label_idx = LABELS.index(args.label)
                with torch.no_grad():
                    model.regressor.weight.copy_(checkpoint["regressor.weight"][label_idx:label_idx+1])
                    if checkpoint["regressor.bias"].dim() == 1:
                        model.regressor.bias.copy_(checkpoint["regressor.bias"][label_idx:label_idx+1])
                print(f"  抽取回归头: label={args.label} (index={label_idx}) from {old_out}-head checkpoint")

        del checkpoint

    model = model.to(device)

    # ── checkpoint 文件名（单标签 vs 多标签）──
    ckpt_name = f"macbert_{args.label}_best.pt" if args.label else "macbert_best.pt"
    best_path = output_dir / ckpt_name

    # ── loss_fn 在训练和评估中都需定义 ──
    loss_fn = nn.MSELoss()

    # ── 仅评估模式：跳过训练，直接评估 ──
    if args.eval_only:
        epoch = 0
        # 优先使用 --init-checkpoint 已加载的权重，不再次加载
        if args.init_checkpoint:
            print(f"仅评估模式：使用 --init-checkpoint 权重（跳过 {best_path}）")
        elif best_path.exists():
            model.load_state_dict(torch.load(best_path, map_location=device))
            print(f"仅评估模式：已加载 {best_path}")
        else:
            print(f"警告：checkpoint 不存在 {best_path}，使用随机初始化模型评估")
    else:
        optimizer = AdamW(model.parameters(), lr=args.lr)
        total_steps = len(train_loader) * args.epochs
        scheduler = get_linear_schedule_with_warmup(
            optimizer, num_warmup_steps=int(0.05 * total_steps), num_training_steps=total_steps
        )

        # ── 训练循环 ──
        best_val_loss = float("inf")
        patience_counter = 0
        train_start = time.time()

        print(f"\n{'=' * 60}")
        print(f"开始训练: {args.epochs} epochs, {len(train_loader)} batches/epoch, batch_size={args.batch_size}")
        print(f"{'=' * 60}")
        print(f"{'Epoch':>6} | {'Train Loss':>10} | {'Val Loss':>9} | {'Time':>8} | {'LR':>10} | {'Status'}")
        print("-" * 60)

        for epoch in range(args.epochs):
            epoch_start = time.time()

            # 训练
            train_loss, train_time = train_epoch(
                model, train_loader, loss_fn, optimizer, scheduler, device,
                epoch + 1, args.epochs
            )

            # 验证
            val_loss, _, _, val_time = evaluate(model, val_loader, loss_fn, device, name="val")

            # 当前学习率
            current_lr = scheduler.get_last_lr()[0]

            if val_loss < best_val_loss:
                best_val_loss = val_loss
                torch.save(model.state_dict(), best_path)
                patience_counter = 0
            else:
                patience_counter += 1

            epoch_time = time.time() - epoch_start
            elapsed_total = time.time() - train_start
            etc = (elapsed_total / (epoch + 1)) * (args.epochs - epoch - 1) if args.epochs > 1 else 0

            print(f"  {epoch + 1:>3}/{args.epochs}  |  {train_loss:.4f}  |  {val_loss:.4f}  |  "
                  f"{epoch_time:.0f}s  |  {current_lr:.2e}  |{'✓' if patience_counter == 0 else f'({args.patience - patience_counter})'}")
            print(f"  {'':>27}Epoch time: {train_time:.0f}s train + {val_time:.0f}s val  "
                  f"| ETC: {etc:.0f}s / {etc/60:.1f}min")

            if patience_counter >= args.patience:
                print(f"\n早停于 epoch {epoch + 1}（{args.patience} 轮未改善）")
                break

        total_time = time.time() - train_start
        print(f"\n训练总用时: {total_time:.0f}s ({total_time/60:.1f}min)")

    # ── 测试集评估 ──
    print(f"\n{'=' * 60}")
    print(f"测试集评估 — {args.label if args.label else '全部 10 标签'}（归一化空间）")
    print(f"{'=' * 60}")

    if not args.eval_only:
        best_path = output_dir / ckpt_name
        if best_path.exists():
            model.load_state_dict(torch.load(best_path, map_location=device))
    else:
        print(f"仅评估模式：跳过 best checkpoint 重载，使用已加载权重")

    _, test_preds, test_labels, test_time = evaluate(model, test_loader, loss_fn, device, name="test")
    print(f"  测试集评估用时: {test_time:.0f}s")

    from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
    try:
        from scipy.stats import spearmanr
    except ImportError:
        def spearmanr(a, b):
            """Fallback if scipy not available — returns 0."""
            return 0

    # 将预测和标签转换回 0-9 原始分数空间
    test_preds_score = test_preds * 9.0
    test_labels_score = test_labels * 9.0

    def compute_metrics(y_true, y_pred):
        """返回归一化和 0-9 空间的指标。"""
        mae_norm = mean_absolute_error(y_true, y_pred)
        mse = mean_squared_error(y_true, y_pred)
        r2 = r2_score(y_true, y_pred)
        mae_score = mean_absolute_error(y_true * 9.0, y_pred * 9.0)
        rmse_score = np.sqrt(mse) * 9.0
        try:
            sp, _ = spearmanr(y_true, y_pred)
        except Exception:
            sp = 0.0
        return mae_norm, mse, r2, mae_score, rmse_score, float(sp)

    # 分域评估容器（单/多标签共用）
    slices = {}
    has_slices = False

    if args.label:
        # ── 单标签评估 ──
        mae_norm, mse, r2, mae_score, rmse_score, sp = compute_metrics(
            test_labels[:, 0], test_preds[:, 0]
        )
        print(f"  {args.label:>25}:")
        print(f"  {'':>25}  MAE(归一化)={mae_norm:.4f}  R²={r2:+.4f}")
        print(f"  {'':>25}  MAE(0-9)={mae_score:.2f}  RMSE(0-9)={rmse_score:.2f}  Spearman={sp:+.4f}")
        per_label = {args.label: {
            "MAE": round(float(mae_norm), 4), "R2": round(float(r2), 4),
            "MAE_score": round(float(mae_score), 2), "RMSE_score": round(float(rmse_score), 2),
            "Spearman": round(float(sp), 4),
        }}
        overall = per_label[args.label]
    else:
        # ── 多标签评估（含 contact-macro）──
        per_label = {}
        for i, label in enumerate(LABELS):
            mae_norm, mse, r2, mae_score, rmse_score, sp = compute_metrics(
                test_labels[:, i], test_preds[:, i]
            )
            per_label[label] = {
                "MAE": round(float(mae_norm), 4), "R2": round(float(r2), 4),
                "MAE_score": round(float(mae_score), 2), "RMSE_score": round(float(rmse_score), 2),
                "Spearman": round(float(sp), 4),
            }
            print(f"  {label:>25}: MAE(0-9)={mae_score:.2f}  R²={r2:+.4f}  Sp={sp:+.4f}")

        overall_mae_norm = mean_absolute_error(test_labels, test_preds)
        overall_mse = mean_squared_error(test_labels, test_preds)
        overall_r2 = r2_score(test_labels, test_preds)
        overall_mae_score = mean_absolute_error(test_labels_score, test_preds_score)
        overall_rmse_score = np.sqrt(overall_mse) * 9.0
        overall = {
            "MAE": round(float(overall_mae_norm), 4),
            "MAE_score": round(float(overall_mae_score), 2),
            "RMSE_score": round(float(overall_rmse_score), 2),
            "R2": round(float(overall_r2), 4),
        }
        print(f"\n  {'Overall':>25}: MAE(0-9)={overall_mae_score:.2f}  RMSE={overall_rmse_score:.2f}  R²={overall_r2:+.4f}")

        # ── contact-macro MAE ──
        from collections import defaultdict
        contact_preds: dict[str, list] = defaultdict(list)
        contact_labels: dict[str, list] = defaultdict(list)
        for d, pred_row, label_row in zip(test_data, test_preds_score, test_labels_score):
            cid = d.get("contact_wxid", "unknown")
            contact_preds[cid].append(pred_row)
            contact_labels[cid].append(label_row)

        for i, label in enumerate(LABELS):
            contact_maes = [
                mean_absolute_error(
                    np.array(contact_labels[cid])[:, i],
                    np.array(contact_preds[cid])[:, i],
                )
                for cid in contact_preds
            ]
            per_label[label]["Contact_MAE_score"] = round(float(np.mean(contact_maes)), 2)

        print(f"\n  {'Contact-Macro MAE(0-9)':>25}:")
        for label in LABELS:
            print(f"  {label:>25}: {per_label[label]['Contact_MAE_score']:.2f}")

        contact_overall_maes = [
            mean_absolute_error(np.array(contact_labels[cid]), np.array(contact_preds[cid]))
            for cid in contact_preds
        ]
        overall["Contact_MAE_score"] = round(float(np.mean(contact_overall_maes)), 2)
        print(f"  {'Overall Contact-Macro MAE':>25}: {overall['Contact_MAE_score']:.2f}")

    # ── 分域评估（clean / external） ──
    for slice_name, slice_mask in [("clean", True), ("external", False)]:
        indices = [i for i, d in enumerate(test_data) if d.get("from_clean_set") == slice_mask]
        if len(indices) < 2:
            slices[slice_name] = {"samples": len(indices), "contacts": 0,
                                  "note": "样本不足，跳过分域评估"}
            continue
        slice_labels = test_labels_score[indices]
        slice_preds = test_preds_score[indices]
        slice_contacts = len(set(test_data[i]["contact_wxid"] for i in indices))

        def _slice_metrics(y_true, y_pred):
            mae = mean_absolute_error(y_true, y_pred)
            mae_norm = mean_absolute_error(y_true / 9.0, y_pred / 9.0)
            r2 = r2_score(y_true, y_pred)
            try:
                sp, _ = spearmanr(y_true.ravel(), y_pred.ravel())
            except Exception:
                sp = 0.0
            return {"MAE_score": round(float(mae), 2),
                    "MAE": round(float(mae_norm), 4),
                    "R2": round(float(r2), 4),
                    "Spearman": round(float(sp), 4)}

        per_label_slice = {}
        for i, label in enumerate(LABELS):
            per_label_slice[label] = {
                "MAE_score": round(float(mean_absolute_error(slice_labels[:, i], slice_preds[:, i])), 2),
            }
        slices[slice_name] = {
            "samples": len(indices),
            "contacts": slice_contacts,
            "overall": _slice_metrics(slice_labels, slice_preds),
            "per_label": per_label_slice,
        }
        has_slices = True

    if has_slices:
        print(f"\n  {'分域评估':─^45}")
        for slice_name in ["clean", "external"]:
            s = slices.get(slice_name, {})
            if "overall" in s:
                o = s["overall"]
                print(f"  {slice_name:>10}: {s['samples']} samples / {s['contacts']} contacts"
                      f"  MAE={o['MAE_score']:.2f}  Sp={o['Spearman']:+.4f}  R²={o['R2']:+.4f}")

    # ── 保存评估报告 + 标签配置 ──
    # 计算划分的指纹（用于跨实验校验）
    train_contacts_sorted = sorted(set(d["contact_wxid"] for d in train_data))
    val_contacts_sorted = sorted(set(d["contact_wxid"] for d in val_data))
    test_contacts_sorted = sorted(set(d["contact_wxid"] for d in test_data))
    test_contacts_sha = hashlib.sha256(json.dumps(test_contacts_sorted).encode()).hexdigest()
    val_contacts_sha = hashlib.sha256(json.dumps(val_contacts_sorted).encode()).hexdigest()
    train_contacts_sha = hashlib.sha256(json.dumps(train_contacts_sorted).encode()).hexdigest()
    # 数据集指纹（所有参与训练的 sample_id 列表）
    all_sids = sorted(d["sample_id"] for d in train_data + val_data + test_data)
    dataset_sha = hashlib.sha256(json.dumps(all_sids).encode()).hexdigest()

    # manifest 文件本身的 SHA256
    if manifest_path.exists():
        with open(manifest_path, "rb") as f:
            manifest_sha = hashlib.sha256(f.read()).hexdigest()
    else:
        manifest_sha = ""

    report_name = f"eval_report_{args.label}.json" if args.label else "eval_report.json"
    report = {
        "label": args.label or "all",
        "overall": overall,
        "per_label": per_label,
        "slices": slices if slices else {},
        "config": {
            "train_samples": len(train_data),
            "val_samples": len(val_data),
            "test_samples": len(test_data),
            "train_contacts": len(train_contacts_sorted),
            "test_contacts": len(test_contacts_sorted),
            "epochs": epoch + 1,
            "batch_size": args.batch_size,
            "lr": args.lr,
        },
        "manifest": {
            "path": str(manifest_path) if manifest_path.exists() else "",
            "split_manifest_sha256": manifest_sha,
            "role_prefix": args.role_prefix,
            "input_schema": "target_other_v1" if args.role_prefix else "roleless_v0",
            "train_contacts_sha256": train_contacts_sha,
            "val_contacts_sha256": val_contacts_sha,
            "test_contacts_sha256": test_contacts_sha,
            "dataset_sha256": dataset_sha,
            "dataset_sample_count": len(all_sids),
        },
    }

    with open(output_dir / report_name, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # 保存标签配置
    if not args.label:
        with open(output_dir / "labels.json", "w", encoding="utf-8") as f:
            json.dump({"labels": LABELS, "num_labels": len(LABELS)}, f, ensure_ascii=False, indent=2)

    # 保存模型元信息
    metadata = {
        "schema_version": "target_other_v1" if args.role_prefix else "roleless_v0",
        "input_format": "roleless (纯文本)" if not args.role_prefix else "target_other_v1",
        "special_tokens": ["[TARGET]", "[OTHER]"] if args.role_prefix else [],
        "labels": [args.label] if args.label else LABELS,
        "num_labels": len([args.label] if args.label else LABELS),
        "value_range": "0-1 (normalized, multiply by 9.0 for 0-9 scores)",
        "role_prefix": args.role_prefix,
    }
    with open(output_dir / "model_metadata.json", "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)

    # 保存 tokenizer（供 ONNX 导出使用）
    tokenizer.save_pretrained(output_dir)

    print(f"\n结果保存至: {output_dir}")
    print("训练完成。")


if __name__ == "__main__":
    main()
