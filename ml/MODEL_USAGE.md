# Conversation Behavior Analyzer — 模型使用说明

> 最后更新：2026-07-10 | 标注者：Claude Code (deepseek-v4-pro)

---

## 一、模型概述

**功能：** 输入一段微信聊天记录，对「她」的 10 个行为维度输出 0-9 强度分数。

**架构：** MacBERT base（hfl/chinese-macbert-base）+ Linear + Sigmoid

**ONNX 文件：** `models/macbert.onnx`（389 MB, opset=14）

---

## 二、标签定义（按输出顺序）

| 序号 | 标签 | 含义 |
|------|------|------|
| 1 | information_exchange | 她陈述事实信息 |
| 2 | opinion_expression | 她表达观点或评价 |
| 3 | emotion_positive | 她表现出正向情绪 |
| 4 | emotion_negative | 她表现出负向情绪 |
| 5 | flirt | 她有暧昧、调侃或撒娇 |
| 6 | question_asking | 她主动提问 |
| 7 | self_disclosure | 她主动分享个人信息 |
| 8 | invitation | 她邀约或积极回应邀约 |
| 9 | framing_boundary | 她使用朋友/兄弟等关系框架词汇 |
| 10 | perfunctory | 她敷衍回应 |

---

## 三、评分标准（0-9 整数）

标注时使用的强度锚点：

| 分数 | 含义 |
|------|------|
| 0 | 完全不存在，没有任何迹象 |
| 1-2 | 极弱，勉强能感受到一丁点 |
| 3-4 | 较弱，偶尔出现一两处 |
| 5-6 | 中等，明确出现但不是全程贯穿 |
| 7-8 | 较强，多次明显体现 |
| 9 | 极强，非常典型或贯穿整个对话 |

**评分原则：**
- 每标签独立评分，互不影响（一个样本可全高或全低）
- 综合「出现频率」和「典型程度」：频率高且典型 → 高分
- 上下文：**微信聊天记录**（区别于面对面交流）

---

## 四、推理接口

### 输入

```
input_ids: int64[batch, 512]    # tokenize 后的对话文本
attention_mask: int64[batch, 512]
```

### 输出

```
scores: float32[batch, 10]      # 值域 [0, 1]，已过 sigmoid
```

### 还原到 0-9

```python
scores_0_9 = scores * 9.0  # 范围恢复到 0-9
```

### Tokenizer

使用 `hfl/chinese-macbert-base` 的 tokenizer（已保存在 `models/` 目录）。

### 预处理

对话消息按以下格式拼接后送入 tokenizer：

```python
text = "\n".join(m["content"] for m in messages)
# tokenize: max_length=512, padding="max_length", truncation=True
```

---

## 五、训练数据

- **来源：** `ml/dataset/batches/batch_*.jsonl`（约 14000 个对话窗口，20 条消息/窗口）
- **标注：** Claude Code 手动标注（2026-07-10），使用上述 0-9 标准
- **标注文件：** `ml/dataset/annotations/annotations_XXX.jsonl`（按 batch 分文件）
- **训练集：** 由 `ml/scripts/train.py` 从标注文件动态构建

### 标签分布

| 标签 | 非零占比 | 说明 |
|------|----------|------|
| information_exchange | 46.3% | 常见 |
| opinion_expression | 43.8% | 常见 |
| emotion_positive | 39.4% | 常见 |
| question_asking | 42.5% | 常见 |
| self_disclosure | 36.8% | 较常见 |
| emotion_negative | 19.0% | 较少 |
| invitation | 11.4% | 稀有 |
| flirt | 8.6% | 稀有 |
| framing_boundary | 7.9% | 稀有 |
| perfunctory | 1.9% | 极稀有 |

---

## 六、训练详情

- **划分：** 按 contact_wxid 分层（38 个联系人，train 30 / test 8）
- **损失函数：** MSELoss（回归，标签除以 9.0 归一化到 [0,1]）
- **优化器：** AdamW, lr=2e-5, batch_size=16
- **早停：** patience=3, 最佳 epoch=3
- **训练时长：** < 1 分钟（A40 GPU）

### 评估结果（归一化空间）

| 指标 | 值 |
|------|-----|
| Overall MAE | 0.108（≈ 1.0 / 9 刻度） |
| Overall MSE | 0.022 |
| Overall R² | -0.151 |

**最佳标签（MAE）：**
- emotion_negative: 0.066
- perfunctory: 0.074
- framing_boundary: 0.084

**注意：** 315 条样本对 10 标签回归偏少，稀有标签（flirt/invitation/perfunctory）模型学习不充分。实际使用时建议将输出作为参考而非绝对判断。

---

## 七、文件清单

```
ml/
├── models/
│   ├── macbert.onnx              # ONNX 模型（389 MB）
│   ├── macbert_best.pt           # PyTorch 权重
│   ├── labels.json               # 标签配置
│   ├── config.json               # BERT 配置
│   ├── vocab.txt                 # 词表
│   ├── tokenizer.json            # Tokenizer
│   ├── tokenizer_config.json     # Tokenizer 配置
│   └── eval_report.json          # 评估报告
├── dataset/
│   ├── batches/                  # 原始 batch 文件（约 14000 条）
│   │   ├── batch_001.jsonl
│   │   ├── batch_002.jsonl
│   │   ├── ...
│   │   └── README.md
│   └── annotations/              # 标注结果（按 batch 分文件）
│       ├── annotations_001.jsonl
│       ├── annotations_002.jsonl
│       ├── ...
│       └── predictions.jsonl     # 模型预测结果
├── scripts/
│   ├── label_batches.py          # 标注提交工具（当前使用）
│   ├── clean_watermarks.py       # 全局水印清洗
│   ├── clean_subset.py           # 特化清洗
│   ├── read_for_label.py         # 未标注样本预览
│   ├── batch_predict.py          # 批量推理
│   ├── quality_audit.py          # 标注质量审计
│   ├── phase2_train.py           # 训练脚本
│   └── export_onnx.py            # ONNX 导出脚本
├── rules/                        # 规则基线分类器
│   ├── baseline_classifier.py
│   └── lexicons/                 # YAML 词典
├── LABELING_GUIDE.md             # 标注标准
├── ANNOTATION_PROMPT.md          # LLM 标注指令
├── ANNOTATION_GUIDE.md           # 标注工作流
└── MODEL_USAGE.md                # 模型使用说明
```

---

## 八、使用示例

```python
import onnxruntime as ort
import numpy as np
from transformers import AutoTokenizer

# 加载
tokenizer = AutoTokenizer.from_pretrained("models/")
session = ort.InferenceSession("models/macbert.onnx")

# 准备输入
messages = [
    {"role": "her", "content": "你咋私聊"},
    {"role": "me", "content": "我问一下wiki"},
    {"role": "her", "content": "屎一样 要是你 你咋会"},
]
text = "\n".join(m["content"] for m in messages)
encoded = tokenizer(text, max_length=512, padding="max_length",
                    truncation=True, return_tensors="np")

# 推理
outputs = session.run(None, {
    "input_ids": encoded["input_ids"],
    "attention_mask": encoded["attention_mask"],
})
scores = outputs[0][0] * 9.0  # [10] shape, 0-9 range

# 结果
labels = ["information_exchange", "opinion_expression", "emotion_positive",
          "emotion_negative", "flirt", "question_asking", "self_disclosure",
          "invitation", "framing_boundary", "perfunctory"]
for label, score in zip(labels, scores):
    print(f"{label}: {score:.1f}")
```

---

## 九、Engine 层集成（Layer 2 融合）

模型已集成到 engine 层，通过 `engine/analyzers/semantic.py` 提供 Layer 2 关系解读融合。

### 双参考机制

系统保留两套行为检测源，可自由切换：

| source | 推理类 | 特点 |
|--------|--------|------|
| `"macbert"` | `ml/rules/classifier_onnx.py` | 语义覆盖全面，推理约 0.5s/窗口 |
| `"rule"` | `ml/rules/baseline_classifier.py` | 词典匹配，可解释性强，推理约 0.02s/窗口 |

### 工具函数（`engine/tools.py`）

```python
# 返回 Markdown 格式的语义分析报告
behaviors(name, window_days=30, source="macbert") -> str

# 返回结构化数据（含标签均值、派生指标、窗口序列）
behaviors_data(name, window_days=30, source="macbert") -> dict
```

### Layer 2 派生指标

`behaviors_data()` 返回的 `derived_metrics` 包含以下关系解读指标：

| 指标 | 计算方式 | 含义 |
|------|----------|------|
| `emotion_balance` | pos / (pos + neg) | 正负情绪比，>0.7 为健康 |
| `interest_signal` | question_asking + self_disclosure + invitation + flirt | 兴趣信号强度 |
| `friendzone_indicator` | framing_boundary + perfunctory | 友谊区/敷衍信号 |
| `engagement_depth` | opinion_expression + self_disclosure + flirt | 互动深度（vs 纯信息交换） |
| `info_vs_emotion_ratio` | information_exchange / (emotion_positive + emotion_negative + 1) | 信息交换 vs 情感交流比 |

### 架构设计原则

- **Layer 1（模型）** 只输出 10 个可观测行为标签（0-9 分），不猜"她喜不喜欢我"
- **Layer 2（engine）** 将行为标签融合为关系解读指标
- **关系判断** 交给 Agent，结合 Wiki 方法论和上下文做最终决策

### 滑动窗口参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| window_size | 20 条消息 | 每个分析窗口的消息数 |
| slide_step | 10 条消息 | 窗口滑动步长 |
| min_turns | 10 | 最少对话轮次，不足则跳过 |
