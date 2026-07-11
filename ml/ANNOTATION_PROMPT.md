# 对话行为标注任务

> 给 LLM 的标注指令。使用 `ml/LABELING_GUIDE.md` 的评分标准标注 10 个行为维度。

---

## 输出格式

每条对话输出一行 JSON，写入 `annotations_XXX.jsonl`。

### 正常样本

```
3|8|1|6|0|1|2|0|5|1
```

对应 10 个标签（严格按此顺序）：
`information_exchange | opinion_expression | emotion_positive | emotion_negative | flirt | question_asking | self_disclosure | invitation | framing_boundary | perfunctory`

每条分数 0-9 整数，评分标准见 `LABELING_GUIDE.md`。

### 质量过低 - 放弃

```
-1
```

当对话质量低到无法判断时（乱码过多、角色混乱、非对话内容等），直接写 `-1`，不需要说明原因。

### 判定标准（任一即放弃）

1. 超过一半消息是乱码
2. 对话不完整，无法判断行为
3. 不是男女对话
4. 角色混乱，无法确定谁是 "her"

---

## 注意事项

1. **OCR 噪声**：明显乱码跳过即可，不完全影响理解就正常标
2. **英文对话**：同样适用 10 个标签
3. **教学案例**：按实际对话行为标分，不需要判断案例本身
4. **评分区间**：充分利用 0-9，大部分在 2-6 之间
