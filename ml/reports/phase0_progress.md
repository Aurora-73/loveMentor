# Phase 0 Baseline 中间进展报告

> 日期：2026-07-09
> 状态：**进行中** — 等待人工标注完成后补充精度评估

---

## 一、数据概况

| 指标 | 值 |
|------|-----|
| 数据源 | data/raw/core.db |
| 私聊会话数 | 335 |
| 合格会话数（>=20条文本消息） | 47 |
| 窗口大小 | 10 轮 / 5 步 |
| 总窗口数 | 910 |
| 平均每窗口轮数 | 9.9 |

> **注**：规划假设 5000 样本，实际只有 910 个，原因是个人聊天数据集规模有限。
> 不影响方法验证，后续可以通过增加窗口密度（更小步长）、扩大会话范围（公众号等）等方式补充。

---

## 二、三种 Baseline 方法对比

### 2.1 标签分布对比

| 标签 | 规则基线 | Embedding Zero-Shot | 弱监督（规则+LR） |
|------|---------|---------------------|-------------------|
| question_asking | 183 (20.1%) | 285 (31.3%) | 252 (27.7%) |
| self_disclosure | 2 (0.2%) | 388 (42.6%) | 2 (0.2%)* |
| emotional_expression | 315 (34.6%) | 410 (45.1%) | 376 (41.3%) |
| initiative_response | 4 (0.4%) | 666 (73.2%) | 4 (0.4%)* |
| flirt | 53 (5.8%) | 247 (27.1%) | 127 (14.0%) |
| intimacy | 15 (1.6%) | 355 (39.0%) | 35 (3.8%) |
| cold_conflict | 20 (2.2%) | 627 (68.9%) | 57 (6.3%) |
| perfunctory | 16 (1.8%) | 234 (25.7%) | 39 (4.3%) |
| investment | 7 (0.8%) | 459 (50.4%) | 29 (3.2%) |
| willingness | 15 (1.6%) | 675 (74.2%) | 43 (4.7%) |

> *self_disclosure 和 initiative_response 规则正例太少（<5），弱监督跳过训练，直接用规则结果。

### 2.2 方法特点

| 方法 | 优点 | 缺点 | 适用场景 |
|------|------|------|---------|
| 规则基线 | 精确、可控、可解释 | 召回率低（保守），需要人工调阈值 | 高置信度正例筛选 |
| Embedding Zero-Shot | 召回率高、泛化好 | 精度低（偏松），阈值难调 | 初步筛选、召回导向 |
| 弱监督（规则+LR） | 平衡精度和召回 | 受规则标签质量限制 | 综合基线 |

---

## 三、规则 vs Embedding 一致性

平均 Kappa: **0.054**（几乎没有一致性）

这说明两个方法捕捉的信号差异很大：
- 规则偏保守，只捕捉明确的关键词模式
- Embedding zero-shot 偏宽松，语义相似度高就判正
- 两者互补性强，结合使用效果更好

详细分析见：[rule_vs_embedding_consistency.md](file:///E:/Code/loveMentor/ml/reports/rule_vs_embedding_consistency.md)

---

## 四、等待人工标注的部分

### 4.1 Pre-check 验证（60 样本 × 3 标签）
- 目的：验证规则检测可观测行为的可行性
- 标签：question_asking, flirt, perfunctory
- 模板：[ml/pre_check/annotation_template.md](file:///E:/Code/loveMentor/ml/pre_check/annotation_template.md)
- 决策门：kappa > 0.6 → 路线可行；kappa < 0.4 → 需要调整

### 4.2 Baseline 精度评估（150 样本 × 10 标签）
- 目的：评估三种 baseline 方法的实际精度
- 标签：全部 10 个语义标签
- 模板：[ml/outputs/annotation_template_150.md](file:///E:/Code/loveMentor/ml/outputs/annotation_template_150.md)
- 产出：各方法 precision/recall/F1/kappa

### 4.3 标注规范
- [ml/docs/annotation_guideline.md](file:///E:/Code/loveMentor/ml/docs/annotation_guideline.md)

---

## 五、文件清单

### 核心模块
- [ml/dataset/data_loader.py](file:///E:/Code/loveMentor/ml/dataset/data_loader.py) — 数据加载与窗口构建
- [ml/rules/baseline_classifier.py](file:///E:/Code/loveMentor/ml/rules/baseline_classifier.py) — 规则基线分类器
- [ml/embedding/embedder.py](file:///E:/Code/loveMentor/ml/embedding/embedder.py) — Embedding 封装
- [ml/embedding/embedding_classifier.py](file:///E:/Code/loveMentor/ml/embedding/embedding_classifier.py) — Zero-Shot 分类器
- [ml/embedding/weak_supervised.py](file:///E:/Code/loveMentor/ml/embedding/weak_supervised.py) — 弱监督分类器
- [ml/evaluation/evaluate.py](file:///E:/Code/loveMentor/ml/evaluation/evaluate.py) — 评估工具

### 词典库（10 个）
- [ml/lexicons/](file:///E:/Code/loveMentor/ml/lexicons/) 目录下 10 个 .yaml 文件

### 数据产出
- [ml/dataset/samples_5000.jsonl](file:///E:/Code/loveMentor/ml/dataset/samples_5000.jsonl) — 910 个样本
- [ml/outputs/baseline_results.jsonl](file:///E:/Code/loveMentor/ml/outputs/baseline_results.jsonl) — 规则预测
- [ml/outputs/embedding_results.jsonl](file:///E:/Code/loveMentor/ml/outputs/embedding_results.jsonl) — Embedding 预测
- [ml/outputs/weak_supervised_results.jsonl](file:///E:/Code/loveMentor/ml/outputs/weak_supervised_results.jsonl) — 弱监督预测

---

## 六、下一步计划

1. **人工标注**（需用户参与）
   - 标注 150 条抽检样本的 10 个标签
   - 预计耗时：1-2 小时

2. **运行评估**（标注完成后）
   ```bash
   # 1. 把填好的模板转成 JSONL
   python ml/evaluation/evaluate.py convert --template ml/outputs/annotation_template_150.md --output ml/outputs/gold_150.jsonl

   # 2. 评估规则基线
   python ml/evaluation/evaluate.py evaluate --pred ml/outputs/baseline_results.jsonl --gold ml/outputs/gold_150.jsonl

   # 3. 评估 embedding
   python ml/evaluation/evaluate.py evaluate --pred ml/outputs/embedding_results.jsonl --gold ml/outputs/gold_150.jsonl

   # 4. 评估弱监督
   python ml/evaluation/evaluate.py evaluate --pred ml/outputs/weak_supervised_results.jsonl --gold ml/outputs/gold_150.jsonl
   ```

3. **生成最终报告**
   - 填入 precision/recall/F1 数据
   - 选出最佳 baseline 方法
   - 决定是否进入 Phase 1（A100 批量标注）
