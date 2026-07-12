# 标注工作流指南

## 数据总览

### 原始 batches（`batches/`）

| batch | 状态 | 说明 |
|-------|------|------|
| batch_001~007 | 已标完 | 均已标注完成 |
| batch_008 | 部分标注 | 尾部模板化已清理，剩余约 300 条 |
| batch_009~014 | 未标注 | 待标注，每批约 1000 条 |

### 全局水印清洗

所有 batch 文件已通过 `clean_watermarks.py` 进行全局水印清洗，覆盖以下类型：

- **OCR 语音按钮叠加**："按住说话" 及变体
- **时间戳水印**：导出时间戳及碎片
- **百度云/PUA 广告**：PUA 教程推广块
- **WCD 元数据**：距离/时间/已读回执
- **其他**：表情包占位符、截断 @ 提及、瑞恩情感广告

---

## 核心流程

```
预览 → 全局清洗(已完成) → 特化清洗(可选) → 标注 → 自动校验
```

### 第一步：预览

看看数据长什么样，有没有明显脏数据。

```bash
# 完整内容预览（推荐）
python -X utf8 ml/scripts/read_for_label.py --batch 009 --offset 0 --count 20

# 快速预览（内容截断至 100 字）
python -X utf8 ml/scripts/label_batches.py --batch 009 --count 20
```

### 第二步：全局水印清洗

所有 batch 已经过全局清洗。如需重新执行：

```bash
# 预览影响
python -X utf8 ml/scripts/clean_watermarks.py --dry-run

# 查看具体差异
python -X utf8 ml/scripts/clean_watermarks.py --diff --batch 009

# 执行清洗
python -X utf8 ml/scripts/clean_watermarks.py
```

### 第三步：特化清洗（残留脏数据时）

全局清洗后如果还有残留子串（如教学标签、特定 OCR 碎片），用 `clean_subset.py` 进行行内清洗。

```bash
# 从未标注列表第 40 条开始，移除子串
python -X utf8 ml/scripts/clean_subset.py --batch 009 --offset 40 --count 20 --remove "某文本"

# 删除包含某文本的行
python -X utf8 ml/scripts/clean_subset.py --batch 009 --offset 40 --count 20 --drop-line "残留文本"

# 删除整条消息
python -X utf8 ml/scripts/clean_subset.py --batch 009 --offset 40 --count 20 --drop-msg "完全匹配的消息"
```

### 第四步：标注

```bash
# 单条
python -X utf8 ml/scripts/label_batches.py --batch 009 --submit "7|8|6|1|5|5|3|7|6|1"

# 放弃（质量太差无法判断时，必须写明理由）
python -X utf8 ml/scripts/label_batches.py --batch 009 --submit "-1:乱码过多无法标注"

# 批量
python -X utf8 ml/scripts/label_batches.py --batch 009 --submit "7|8|6|1|5|5|3|7|6|1" "3|8|1|6|0|1|2|0|5|1"
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
- 水印清洗后可能产生少量空消息（原"按住说话"行），这些空行不影响整体判断

---

## 建议标注顺序

```
原始 batches（batch_009 → batch_014 逐个标注）
  └── 每个 batch：预览 → 全局清洗(已完成) → 特化清洗 → 标注 → 下一批
```

每个 batch 标注 1000 条后换下一个 batch，避免混淆。
