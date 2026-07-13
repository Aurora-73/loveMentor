# -*- coding: utf-8 -*-
import json
import argparse
from pathlib import Path
import torch
import torch.nn as nn
from transformers import AutoTokenizer, AutoModel

LABELS = ["information_exchange", "opinion_expression", "emotion_positive", "emotion_negative", "flirt", "question_asking", "self_disclosure", "invitation", "framing_boundary", "perfunctory"]


class MacBERTRegressor(nn.Module):
    """多标签回归模型：输出 sigmoid 约束到 [0,1]"""
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
        return torch.sigmoid(logits)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model_dir", default=None)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    cwd = Path.cwd()
    model_dir = Path(args.model_dir) if args.model_dir else cwd / "models"
    output_path = Path(args.output) if args.output else model_dir / "macbert.onnx"

    # tokenizer 从本地加载
    tokenizer = AutoTokenizer.from_pretrained(str(model_dir))
    # 模型架构从 HF 加载，然后用 fine-tuned 权重覆盖
    model = MacBERTRegressor(model_name="/home2/cme_code/convert/hf_cache/hfl_chinese-macbert-base")
    # 确保 embedding 与 tokenizer 一致（训练时添加了 [TARGET]/[OTHER] 特殊 token）
    model.bert.resize_token_embeddings(len(tokenizer))
    state_dict = torch.load(model_dir / "macbert_best.pt", map_location="cpu", weights_only=True)
    model.load_state_dict(state_dict)
    model.eval()

    dummy_input_ids = torch.randint(0, 1000, (1, 512))
    dummy_attention_mask = torch.ones((1, 512), dtype=torch.int64)

    from torch.onnx import TrainingMode
    torch.onnx.export(
        model,
        (dummy_input_ids, dummy_attention_mask),
        str(output_path),
        export_params=True,
        opset_version=14,
        do_constant_folding=True,
        input_names=["input_ids", "attention_mask"],
        output_names=["scores"],
        dynamic_axes={
            "input_ids": {0: "batch_size"},
            "attention_mask": {0: "batch_size"},
            "scores": {0: "batch_size"},
        },
        training=TrainingMode.EVAL,
    )

    label_config = {"labels": LABELS, "value_range": "0-9 (normalized to 0-1 in ONNX, multiply by 9 to recover)"}
    with open(model_dir / "labels.json", "w", encoding="utf-8") as f:
        json.dump(label_config, f, ensure_ascii=False, indent=2)

    # 保存模型元信息——从 tokenizer 自动判断是否 role-aware
    has_special = "[TARGET]" in (tokenizer.additional_special_tokens or [])
    metadata = {
        "schema_version": "target_other_v1" if has_special else "roleless_v0",
        "input_format": "target_other_v1" if has_special else "roleless (纯文本)",
        "special_tokens": ["[TARGET]", "[OTHER]"] if has_special else [],
        "labels": LABELS,
        "num_labels": len(LABELS),
        "value_range": "0-1 (normalized in ONNX, multiply by 9.0 for 0-9 scores)",
    }
    with open(model_dir / "model_metadata.json", "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)

    tokenizer.save_pretrained(str(model_dir))
    print(f"ONNX exported: {output_path}")
    print(f"Labels saved: {model_dir / 'labels.json'}")
    print(f"Metadata saved: {model_dir / 'model_metadata.json'}")


if __name__ == "__main__":
    main()
