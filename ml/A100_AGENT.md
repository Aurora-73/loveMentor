# A100 Agent 操作手册

> 挂载路径：`/home2/cme_code/loveMentor_ml/`（samba 共享，与本地 `<project_root>\ml\` 同步）
> GPU：NVIDIA A100 PCIe 40GB | OS：Ubuntu 22.04

---

## 一、环境准备

### 1.1 安装依赖

```bash
cd /home2/cme_code/loveMentor_ml

# Phase 1 依赖（Ollama 方式）
pip install requests

# Phase 1 依赖（HuggingFace 方式）
pip install torch transformers accelerate

# Phase 2 依赖
pip install torch transformers scikit-learn onnx onnxruntime
```

### 1.2 下载模型

```bash
# 方式 A（推荐）：Ollama
ollama pull qwen3:14b

# 方式 B：HuggingFace（仅当 Ollama 不可用时）
python -c "from transformers import AutoModelForCausalLM, AutoTokenizer; AutoModelForCausalLM.from_pretrained('Qwen/Qwen3-14B', torch_dtype='auto'); AutoTokenizer.from_pretrained('Qwen/Qwen3-14B')"
```

### 1.3 验证环境

```bash
python -c "import torch; print(f'CUDA: {torch.cuda.is_available()}, GPU: {torch.cuda.get_device_name(0)}')"
python scripts/phase1_annotate.py --help
```

---

## 二、Phase 1：Qwen3 批量标注

### 2.1 运行标注

```bash
cd /home2/cme_code/loveMentor_ml

# 方式 A（推荐，如果 Ollama 可用）
python scripts/phase1_annotate.py

# 方式 B（HuggingFace Transformers）
python scripts/phase1_annotate.py --hf
```

**参数说明**：
- `--input`：输入样本文件（默认 `dataset/samples_phase0.jsonl`）
- `--output`：输出标注文件（默认 `dataset/annotations_phase1.jsonl`）
- `--hf`：使用 HuggingFace 而非 Ollama
- `--start` / `--end`：指定样本区间（断点续传用）

**进度**：315 个样本，每条约 2-5 秒，总计约 10-25 分钟。支持断点续传（已标注的自动跳过）。

### 2.2 质量检查

```bash
# 对比 Qwen3 标注 vs 人工金标
python scripts/phase1_quality_check.py
```

输出 per-label kappa，关注：
- kappa ≥ 0.6：高质量标签，直接用于训练
- 0.4 ≤ kappa < 0.6：可用，但训练时需降低权重
- kappa < 0.4：该标签用规则 baseline 替代

### 2.3 合并标注

```bash
# Qwen3 标注 + 人工金标合并为最终训练集
python scripts/phase1_merge.py
```

输出：`dataset/training_set.jsonl`

---

## 三、Phase 2：MacBERT 训练

### 3.1 准备数据

```bash
python scripts/phase2_train.py --prepare_only
```

联系人级别划分（按 contact_wxid）：train 80% / val 10% / test 10%。一个联系人不会跨集合。

### 3.2 训练

```bash
# 默认 20 epochs，早停 patience=3
python scripts/phase2_train.py --epochs 20 --batch_size 32

# 低 epoch 快速验证（确认代码能跑通）
python scripts/phase2_train.py --epochs 3 --batch_size 16
```

输出：
- `models/best_model.pt`（最佳 checkpoint）
- `reports/phase2_vs_baseline.md`（与规则 baseline 对比报告）

### 3.3 导出 ONNX

```bash
python scripts/export_onnx.py
```

输出：`models/conversation_behavior_analyzer.onnx`

ONNX 文件在 samba 上，本地 `<project_root>\ml\models\` 可直接读取。

---

## 四、文件结构

```
/home2/cme_code/loveMentor_ml/
├── dataset/
│   ├── samples_phase0.jsonl       # 315 个原始窗口
│   ├── annotations_phase1.jsonl   # Qwen3 标注结果（Phase 1 产出）
│   └── training_set.jsonl         # 合并后训练集（Phase 1 产出）
├── scripts/
│   ├── phase1_annotate.py         # Qwen3 批量标注
│   ├── phase1_quality_check.py    # 质量检查
│   ├── phase1_merge.py           # 合并标注
│   ├── phase2_train.py           # MacBERT 训练
│   └── export_onnx.py            # ONNX 导出
├── models/
│   └── conversation_behavior_analyzer.onnx  # 最终模型
├── reports/
│   └── phase2_vs_baseline.md      # 对比报告
├── evaluation/
│   └── evaluate.py                # 评估工具（kappa, F1）
├── lexicons/                      # 10 个 YAML 词典（规则 baseline）
└── docs/
    └── annotation_guideline.md    # 标注规范
```

---

## 五、推荐执行顺序

```bash
# Step 1: 环境准备
pip install torch transformers accelerate scikit-learn requests

# Step 2: 下载 Qwen3（约 30GB）
ollama pull qwen3:14b

# Step 3: 批量标注（10-25 分钟）
cd /home2/cme_code/loveMentor_ml && python scripts/phase1_annotate.py

# Step 4: 质量检查（1 分钟）
python scripts/phase1_quality_check.py

# Step 5: 合并标注（几秒）
python scripts/phase1_merge.py

# Step 6: 快速验证训练（确认代码正常）
python scripts/phase2_train.py --epochs 3 --batch_size 16

# Step 7: 正式训练（10-20 分钟）
python scripts/phase2_train.py --epochs 20 --batch_size 32

# Step 8: 导出 ONNX（几秒）
python scripts/export_onnx.py
```

---

## 六、注意事项

1. **Ollama 方式 vs HuggingFace 方式**：优先用 Ollama（`phase1_annotate.py` 默认），Ollama 不支持 Qwen3 时改用 `--hf`
2. **断点续传**：标注脚本会自动跳过已标注的 sample_id，中断后重新运行即可继续
3. **显存**：Qwen3-14B 约占用 28GB，A100 40G 足够；MacBERT 训练仅需 8-12GB
4. **文件共享**：A100 上修改的文件本地直接可见，不需要手动传输
5. **Ollama 默认端口**：`http://localhost:11434`，标注脚本默认连此地址
