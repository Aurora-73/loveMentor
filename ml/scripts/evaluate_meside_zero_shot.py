#!/usr/bin/env python3
"""me-side zero-shot 评估 — B1′ 不改权重，只切换 target_role。

用法（A100）:
  cd /home2/cme_code/lm/ml
  PY=/home2/cme_code/convert/python_env/bin/python3

  # B1′ target_role="me"（主结果）
  $PY scripts/evaluate_meside_zero_shot.py \
    --model-dir models/role_aware_b1_prime \
    --candidates dataset/annotations/me_side_pilot_v1_candidates.jsonl \
    --annotations dataset/annotations/annotations_meside_000.jsonl \
    --split held_out --target-role me \
    --output models/role_aware_b1_prime/me_side_zero_shot_report.json

  # B0′ roleless 弱对照
  $PY scripts/evaluate_meside_zero_shot.py \
    --model-dir models/baseline_b0_prime \
    --candidates dataset/annotations/me_side_pilot_v1_candidates.jsonl \
    --annotations dataset/annotations/annotations_meside_000.jsonl \
    --split held_out --roleless \
    --output models/baseline_b0_prime/me_side_zero_shot_comparison.json

评估报告含:
  - Overall: MAE / RMSE / R² / Contact-Macro MAE
  - Per label: MAE / R² / Spearman / Contact-Macro MAE
  - 常数基线（pilot-train 每标签均值作为参照）
  - 预测明细（sample_id / contact_wxid / prediction / gold）
"""
from __future__ import annotations

import json
import sys
import argparse
import numpy as np
from pathlib import Path
from collections import defaultdict
from scipy.stats import spearmanr
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

import torch
from torch.utils.data import Dataset, DataLoader
from transformers import AutoTokenizer

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from ml.input_format import format_behavior_input

LABELS = [
    "information_exchange", "opinion_expression", "emotion_positive",
    "emotion_negative", "flirt", "question_asking", "self_disclosure",
    "invitation", "framing_boundary", "perfunctory",
]

# ── 模型定义（与 train_macbert.py 一致） ──


class MacBERTRegressor(torch.nn.Module):
    def __init__(self, model_name: str = "/home2/cme_code/convert/hf_cache/hfl_chinese-macbert-base", num_labels: int = 10):
        super().__init__()
        from transformers import AutoModel
        self.bert = AutoModel.from_pretrained(model_name)
        self.dropout = torch.nn.Dropout(0.3)
        self.regressor = torch.nn.Linear(self.bert.config.hidden_size, num_labels)

    def forward(self, input_ids, attention_mask):
        outputs = self.bert(input_ids=input_ids, attention_mask=attention_mask)
        cls_output = outputs.last_hidden_state[:, 0, :]
        cls_output = self.dropout(cls_output)
        logits = self.regressor(cls_output)
        return torch.sigmoid(logits)  # [0, 1]


# ── 数据集 ──


class MesideEvalDataset(Dataset):
    """me-side 零样本评估数据集。

    与 ConversationDataset 的区别：target_role 可配置（不硬编码 "her"）。
    """

    def __init__(self, samples: list[dict], tokenizer,
                 target_role: str, roleless: bool = False,
                 max_len: int = 512):
        self.samples = samples
        self.tokenizer = tokenizer
        self.target_role = target_role
        self.roleless = roleless
        self.max_len = max_len

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        msgs = self.samples[idx]["messages"]
        if self.roleless:
            lines = [m["content"] if isinstance(m, dict) else str(m) for m in msgs]
            text = "\n".join(lines)
        else:
            text = format_behavior_input(msgs, target_role=self.target_role)

        tokens = self.tokenizer(
            text, max_length=self.max_len, truncation=True, padding="max_length",
            return_tensors="pt",
        )
        return {
            "input_ids": tokens["input_ids"].squeeze(0),
            "attention_mask": tokens["attention_mask"].squeeze(0),
        }


# ── 数据加载与去重 ──


def load_meside_data(candidates_path: Path, annotations_path: Path,
                     split: str) -> tuple[list[dict], np.ndarray, list[str]]:
    """加载 me-side 评估数据。

    Returns:
        (samples, gold_labels_array, sample_ids)
    """
    # 1. 读取候选，去重
    cands = {}
    with open(candidates_path, encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            cands.setdefault(d["sample_id"], d)  # 重复保留第一个

    # 2. 筛选 split
    split_samples = [s for s in cands.values() if s.get("split") == split]
    if not split_samples:
        print(f"错误: split='{split}' 无匹配样本")
        sys.exit(1)

    # 3. 读取标注，去重
    anns = {}
    with open(annotations_path, encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            sid = d["sample_id"]
            if sid in anns:
                continue
            if d.get("discard"):
                continue
            if d.get("target") != "me":
                continue
            labels = d.get("labels", {})
            if all(k in labels for k in LABELS):
                anns[sid] = labels

    # 4. 合并
    merged = []
    for s in split_samples:
        sid = s["sample_id"]
        labels = anns.get(sid)
        if labels is not None:
            merged.append((s, labels))

    samples = [m[0] for m in merged]
    gold = np.array([[m[1][k] for k in LABELS] for m in merged], dtype=np.float32)
    sample_ids = [m[0]["sample_id"] for m in merged]
    contacts = [m[0].get("contact_wxid", "?") for m in merged]

    print(f"  候选: {len(cands)} 唯一样本")
    print(f"  筛选 split='{split}': {len(split_samples)} 条")
    print(f"  标注匹配: {len(merged)} 条 / {len(set(contacts))} 联系人")

    return samples, gold, sample_ids, contacts


def load_pilot_train_labels(annotations_path: Path,
                            candidates_path: Path) -> np.ndarray:
    """加载 pilot-train 的每标签均值（用作常数基线）。"""
    cands = {}
    with open(candidates_path, encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            cands.setdefault(d["sample_id"], d)

    train_ids = {sid for sid, s in cands.items() if s.get("split") == "train"}

    all_labels = []
    with open(annotations_path, encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            if d["sample_id"] in train_ids and not d.get("discard"):
                labels = d.get("labels", {})
                if all(k in labels for k in LABELS):
                    all_labels.append([labels[k] for k in LABELS])

    if not all_labels:
        return np.zeros(len(LABELS), dtype=np.float32)

    means = np.mean(all_labels, axis=0)
    return means.astype(np.float32)


# ── 评估指标 ──


def compute_metrics(y_true: np.ndarray, y_pred: np.ndarray,
                    contacts: list[str]) -> dict:
    """计算评估指标。y_true / y_pred 形状均为 (N, 10) 0-9 分数。"""
    results = {}

    # Overall
    mae_score = float(mean_absolute_error(y_true, y_pred))
    mse = float(mean_squared_error(y_true, y_pred))
    rmse_score = float(np.sqrt(mse))
    r2 = float(r2_score(y_true, y_pred))
    try:
        sp, _ = spearmanr(y_true.ravel(), y_pred.ravel())
    except Exception:
        sp = 0.0

    results["overall"] = {
        "MAE_score": round(mae_score, 2),
        "RMSE_score": round(rmse_score, 2),
        "R2": round(r2, 4),
        "Spearman": round(float(sp), 4),
    }

    # Contact-Macro MAE
    contact_preds = defaultdict(list)
    contact_labels = defaultdict(list)
    for i, cid in enumerate(contacts):
        contact_preds[cid].append(y_pred[i])
        contact_labels[cid].append(y_true[i])

    contact_maes = [
        float(mean_absolute_error(np.array(contact_labels[cid]), np.array(contact_preds[cid])))
        for cid in contact_preds
    ]
    results["overall"]["Contact_MAE_score"] = round(float(np.mean(contact_maes)), 2)

    # Per label
    per_label = {}
    for i, label in enumerate(LABELS):
        yt = y_true[:, i]
        yp = y_pred[:, i]
        mae_l = float(mean_absolute_error(yt, yp))
        r2_l = float(r2_score(yt, yp))
        try:
            sp_l, _ = spearmanr(yt, yp)
        except Exception:
            sp_l = 0.0

        # Contact-Macro per label
        c_maes = []
        for cid in contact_preds:
            cp = np.array(contact_preds[cid])[:, i]
            cl = np.array(contact_labels[cid])[:, i]
            c_maes.append(float(mean_absolute_error(cl, cp)))
        c_mae = float(np.mean(c_maes)) if c_maes else 0.0

        per_label[label] = {
            "MAE_score": round(mae_l, 2),
            "R2": round(r2_l, 4),
            "Spearman": round(sp_l, 4),
            "Contact_MAE_score": round(c_mae, 2),
        }

    results["per_label"] = per_label
    return results


# ── 模型加载 ──


def load_model(model_dir: Path, device: torch.device, roleless: bool = False):
    """加载 MacBERT checkpoint，支持 B0 (roleless) 和 B1 (role-prefix)。"""
    ckpt_path = model_dir / "macbert_best.pt"
    if not ckpt_path.exists():
        print(f"错误: checkpoint 不存在 {ckpt_path}")
        sys.exit(1)

    model = MacBERTRegressor(num_labels=len(LABELS))

    # 始终加载 tokenizer
    tokenizer = AutoTokenizer.from_pretrained(str(model_dir))

    if not roleless:
        # B1'：扩展 embedding（[TARGET]/[OTHER] 在训练时添加到了 tokenizer）
        model.bert.resize_token_embeddings(len(tokenizer))

    checkpoint = torch.load(ckpt_path, map_location="cpu", weights_only=True)
    model.load_state_dict(checkpoint, strict=False)
    model = model.to(device)
    model.eval()
    return model, tokenizer


def load_roleless_model(model_dir: Path, device: torch.device):
    """加载 B0' roleless 模型。"""
    return load_model(model_dir, device, roleless=True)


# ── 主流程 ──


def main():
    parser = argparse.ArgumentParser(description="me-side zero-shot 评估")
    parser.add_argument("--model-dir", required=True,
                        help="模型目录（含 macbert_best.pt + tokenizer 文件）")
    parser.add_argument("--candidates", required=True,
                        help="me-side 候选集 JSONL")
    parser.add_argument("--annotations", required=True,
                        help="me-side 标注 JSONL")
    parser.add_argument("--split", default="held_out",
                        help="评估哪个 split（held_out / train）")
    parser.add_argument("--target-role", default="me",
                        help="B1' 的 target_role（me / her）")
    parser.add_argument("--roleless", action="store_true",
                        help="使用 B0' roleless 模式（忽略 --target-role）")
    parser.add_argument("--output", required=True,
                        help="评估报告输出路径")
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--predictions", default="",
                        help="预测明细输出路径（可选，默认同目录下的 predictions.jsonl）")
    args = parser.parse_args()

    model_dir = Path(args.model_dir)
    candidates_path = Path(args.candidates)
    annotations_path = Path(args.annotations)
    output_path = Path(args.output)

    # ── 加载数据 ──
    print(f"\n{'='*50}")
    print(f"me-side zero-shot 评估")
    print(f"  模型: {model_dir.name}")
    if args.roleless:
        print(f"  模式: roleless (B0')")
    else:
        print(f"  模式: target_role='{args.target_role}'")
    print(f"  split: {args.split}")
    print(f"{'='*50}\n")

    print("加载数据...")
    samples, gold, sample_ids, contacts = load_meside_data(
        candidates_path, annotations_path, args.split,
    )
    num_labels = len(LABELS)

    # ── 加载模型 ──
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"设备: {device}")

    if args.roleless:
        model, tokenizer = load_roleless_model(model_dir, device)
    else:
        model, tokenizer = load_model(model_dir, device)

    # ── 推理 ──
    dataset = MesideEvalDataset(
        samples, tokenizer,
        target_role=args.target_role,
        roleless=args.roleless,
    )
    loader = DataLoader(dataset, batch_size=args.batch_size)

    all_preds = []
    print("推理中...")
    with torch.no_grad():
        for batch in loader:
            input_ids = batch["input_ids"].to(device)
            attention_mask = batch["attention_mask"].to(device)
            preds = model(input_ids, attention_mask)  # [0, 1]
            all_preds.append(preds.cpu().numpy())

    preds = np.concatenate(all_preds, axis=0)  # [0, 1]
    preds_score = preds * 9.0  # 还原到 0-9

    # ── 常数基线（pilot-train 每标签均值） ──
    train_means = load_pilot_train_labels(annotations_path, candidates_path)
    constant_preds = np.tile(train_means, (len(samples), 1))

    # ── 评估 ──
    print("计算指标...")
    main_results = compute_metrics(gold, preds_score, contacts)
    baseline_results = compute_metrics(gold, constant_preds, contacts)

    # ── 输出 ──
    report = {
        "evaluation_type": "me_side_zero_shot",
        "model": {
            "dir": str(model_dir),
            "role_prefix": not args.roleless,
            "target_role": args.target_role if not args.roleless else None,
            "input_schema": "roleless_v0" if args.roleless else "target_other_v1",
        },
        "data": {
            "split": args.split,
            "samples": len(samples),
            "contacts": len(set(contacts)),
            "candidates_file": str(candidates_path),
            "annotations_file": str(annotations_path),
        },
        "training_used_me_labels": False,
        "heldout_type": "me-label-heldout",
        "caveat": (
            "部分 held-out 对话的 her-side 文本已存在于主训练集；"
            "这是角色切换诊断，不是严格未见文本泛化评估。"
        ),
        "results": {
            "model": main_results,
            "baseline_constant": baseline_results,
        },
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n报告已保存: {output_path}")

    # ── 预测明细 ──
    preds_path = args.predictions or str(output_path.with_name("predictions.jsonl"))
    with open(preds_path, "w", encoding="utf-8") as f:
        for i, sid in enumerate(sample_ids):
            record = {
                "sample_id": sid,
                "contact_wxid": contacts[i],
                "target_role": args.target_role,
                "prediction": {k: round(float(preds_score[i][j]), 2) for j, k in enumerate(LABELS)},
                "gold": {k: int(gold[i][j]) for j, k in enumerate(LABELS)},
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"预测明细已保存: {preds_path}")

    # ── 控制台摘要 ──
    o = main_results["overall"]
    print(f"\n{'='*50}")
    print(f"  主结果（B1' target_role={args.target_role}）：")
    print(f"  MAE={o['MAE_score']:.2f}  RMSE={o['RMSE_score']:.2f}  "
          f"R²={o['R2']:+.4f}  Sp={o['Spearman']:+.4f}  "
          f"Contact-MAE={o['Contact_MAE_score']:.2f}")

    bo = baseline_results["overall"]
    print(f"  常数基线（train 均值）：")
    print(f"  MAE={bo['MAE_score']:.2f}  RMSE={bo['RMSE_score']:.2f}")

    print(f"\n  每标签 MAE:")
    for label in LABELS:
        m = main_results["per_label"][label]
        b = baseline_results["per_label"][label]
        arrow = "←" if m["MAE_score"] < b["MAE_score"] else "→"
        print(f"  {label:>25}: model MAE={m['MAE_score']:.2f}  "
              f"Sp={m['Spearman']:+.2f}  "
              f"const={b['MAE_score']:.2f} {arrow}")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
