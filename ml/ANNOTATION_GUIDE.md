# 标注工作流指南

## 数据总览

### 原始 batches（`batches/`）

| batch | 状态 | 说明 |
|-------|------|------|
| batch_001~007 | 已标完 | 旧流程，均已标注完成 |
| batch_008 | 部分标注 | 尾部模板化已清理，剩余 300 条 |
| batch_009~014 | 未标注 | 待标注，每批约 1000 条 |

### 清洗后 rerun（`batches/rerun/cleaned/`）

| batch | 状态 | 说明 |
|-------|------|------|
| batch_001~009 | 未标注 | 从被放弃样本清洗后重新捞出，待标注 |

---

## 核心流程

```
预览 → 泛用清洗 → 特化清洗(可选) → 标注 → 自动校验
```

### 第一步：预览

看看数据长什么样，有没有明显脏数据。

```bash
# 原始 batch
python -X utf8 ml/scripts/label_batches.py --batch 009 --count 20

# 清洗后 batch
python -X utf8 ml/scripts/label_batches.py --batch 001 --source cleaned --count 20
```

### 第二步：泛用清洗（有脏数据时）

预览发现水印/时间戳/OCR 碎片/教学旁白时执行。

```bash
# 清洗窗口（只影响 --offset 开始的 --count 条）
python -X utf8 ml/scripts/clean_batch.py --batch 009 --count 20 --offset 40 --inplace
```

参数：

| 参数 | 说明 |
|------|------|
| `--batch 009` | batch 编号 |
| `--source cleaned` | 数据源（省略=原始 batches） |
| `--count 20` | 操作条数 |
| `--offset 40` | 起始偏移 |
| `--inplace` | 写回原文件 |
| `--prune "短语1,短语2"` | 特化清洗（见第三步） |

### 第三步：特化清洗（残留教学标签时）

泛用清洗后如果还有教学标签（"展示价值"、"测试窗口"等），用 `--prune` 指定短语行内删除。

```bash
python -X utf8 ml/scripts/clean_batch.py --batch 009 --count 20 --offset 40 --prune "展示价值,测试窗口,操盘手" --inplace
```

`--prune` 不会删整行，只删除匹配的短语本身，保留对话内容。

### 第四步：标注

```bash
# 单条
python -X utf8 ml/scripts/label_batches.py --batch 009 --submit "7|8|6|1|5|5|3|7|6|1"

# 放弃（质量太差无法判断时）
python -X utf8 ml/scripts/label_batches.py --batch 009 --submit "-1"

# 批量
python -X utf8 ml/scripts/label_batches.py --batch 009 --submit "7|8|6|1|5|5|3|7|6|1" "3|8|1|6|0|1|2|0|5|1" "-1"
```

#### ⚠️ 自动校验

每次 `--submit` 后系统会自动检查最近 20 条标注的模式：
- 如果 **连续 5 条分数完全相同** → 警告
- 如果 **最近 20 条只有 ≤3 种分数模式** → 警告

**看到警告后**：请检查是否认真逐条标注了，不要跳着标。如果确实数据相似度高，可以忽略警告继续。

### 第五步：查看进度

```bash
python -X utf8 ml/scripts/label_batches.py --progress
```

---

## 10 个标签维度

| # | 标签 | 短名 | 说明 |
|---|------|------|------|
| 1 | information_exchange | 信息交换 | 查户口、报备行踪、事实问答 |
| 2 | opinion_expression | 观点表达 | 表达看法/评价 |
| 3 | emotion_positive | 积极情绪 | 开心、热情、期待 |
| 4 | emotion_negative | 消极情绪 | 生气、失望、冷淡 |
| 5 | flirt | 调情 | 暧昧、调侃、性张力 |
| 6 | question_asking | 提问 | 问问题了解对方 |
| 7 | self_disclosure | 自我披露 | 分享自己经历/感受 |
| 8 | invitation | 邀约 | 约见面、试探邀约 |
| 9 | framing_boundary | 框架/边界 | 立规矩、推拉 |
| 10 | perfunctory | 敷衍 | 嗯、哦、表情包打发 |

每题 **0-9**，0=完全没有，9=非常强。-1=质量太差放弃。

---

## 标注规则

- **逐条看对话内容再打分**，不要跳着标
- 可以不完美但能判断就正常标分，只有完全无法判断对话内容时才标 -1
- **标 -1 只应在数据确实无法标注时使用**，不要因为嫌麻烦就放弃
- 分数应该多样化：同一个人的对话在不同轮次有不同行为
- **如果连续多条分数完全一样**，说明没有认真看数据

---

## 建议标注顺序

```
原始 batches（batch_009 → batch_014 逐个标注）
  └── 每个 batch：预览 → 清洗 → 标注 → 下一批

清洗后 rerun（batch_001 → batch_009 逐个标注）
  └── 每个 batch 约 100~900 条
```

每个 branch 只处理一个 batch，标注 1000 条后换下一个 branch，避免混淆。
