# 回测框架

## 概述

回测框架用于验证 loveMentor 系统参数的合理性。核心思想是：**以已知结果的历史案例作为 ground truth，反向审判系统参数是否合理**。

### 回测不是什么

用系统去分析历史案例，出一份"熹微 composite=0.26 信号冷淡"的报告。这是把回测当成了普通的系统使用，方向完全反了。

### 回测是什么

**用已知结果的历史案例作为标准答案（ground truth），反向审判系统的参数是否合理。**

```
已知：案例 A 实际成功了，案例 B 实际失败了
如果系统的 composite 说 A=0.28，B=0.28
→ 不是"A 和 B 都是 0.28 的水平"
→ 而是"composite 这个指标区分不了成功和失败，指标设计需要改"
```

不是用尺子量东西，是拿已知长度的东西来检验尺子准不准。

### 回测轨道中的优先级：公式 > Agent

本项目总架构中**Wiki/Agent 是推理主轴，公式是辅助参考**——这个定位不变。回测方案不推翻它，而是服务它。

在**可机械验证的校准轨道**中，指标/公式回测是最高优先级——它有明确的输入输出，可以精确计算"预测 vs 实际"的偏差。Agent 的文本分析回测（见第八节）是并行轨道，验证不同层面的东西（Wiki 运用质量、分析逻辑），需要人工评判。

两者的关系：
- **公式回测**：校准参数，让 Agent 看到的数据更可靠
- **Agent 回测**：验证分析质量，让 Wiki 知识库和 Agent 的推理链更可靠

## 核心目标

| 目标 | 描述 |
|------|------|
| 验证指标区分力 | composite/neediness_penalty 是否能有效区分成功/失败案例 |
| 诊断 composite 公式 | 识别公式权重是否合理，阈值是否恰当 |
| 分析信号预警能力 | 系统能否在关系破裂前发出有效预警 |
| 审计 neediness_penalty | 需求感惩罚的触发条件是否符合实际情况 |
| 校准阈值 | 通过描述性统计调整关键参数阈值 |

## 回测要回答的具体问题

| # | 问题 | 主要分析方法 |
|---|------|-------------|
| 1 | 指标在同一个案例的好时期和坏时期有差异吗？ | 案例内时序对比 |
| 2 | 指标的转折点领先于关系结果吗？领先多少天？ | 案例内时序对比 |
| 3 | 多个案例之间，哪些指标的转折模式一致？ | 跨案例模式归纳 |
| 4 | composite 在好时期和坏时期有区别吗？ | 案例内 + 分布重叠 |
| 5 | neediness_penalty 在失败案例中实际触发了没有？ | 逐案例审计 |
| 6 | 信号等级阈值有实证依据吗？ | 全量切片分布 |
| 7 | 不同案例类型的指标曲线形状有什么差异？ | 跨案例归纳 |

## 不做推断统计的原则

组间对比有固有局限——切片不是独立样本（同一个人 10 个切片高度相关），因此采用以下原则：

- **描述性统计**：分布表、重叠区间、均值差异。不做 t 检验、不做 Cohen's d 显著性判断。
- **效应量仅作参考**：Cohen's d 可以算，但解释时标注"切片非独立，d 值可能高估"，且不作为校准建议的主要依据。
- **不依赖统计显著性的结论**：分布完全重叠就是完全重叠，这是肉眼可见的事实，不需要 p 值来证明。

## 端到端工作流

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          完整回测流程                                    │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  Layer 1: 案例定义                                                       │
│  data/backtest/cases.yaml                                        │
│         ↓                                                               │
│  Layer 2: 数据采集                                                       │
│  python -m engine.backtest.collect                                       │
│         ↓                                                               │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │ Phase A: 指标层 (composite/neediness/volume_ratio)              │    │
│  │   → outputs/backtest/{case_id}_phase_a.json                     │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│         ↓                                                               │
│  python -m engine.backtest.collect --phase B [--sensitivity]             │
│         ↓                                                               │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │ Phase B: 公式层 (IVI/SPE/EWS/CS/Action)                         │    │
│  │   → outputs/backtest/{case_id}_phase_b.json                     │    │
│  │   → outputs/backtest/{case_id}_phase_b_sensitivity.json         │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│         ↓                                                               │
│  python -m engine.backtest.validate                                       │
│         ↓                                                               │
│  Layer 3: 分析对比                                                       │
│  python -m engine.backtest.analyze                                       │
│         ↓                                                               │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │ outputs/backtest/calibration_report.md                          │    │
│  │   - 案例内时序分析                                               │    │
│  │   - composite 公式诊断                                          │    │
│  │   - neediness_penalty 审计                                       │    │
│  │   - 跨案例模式归纳                                               │    │
│  │   - 信号领先/滞后分析                                            │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│         ↓                                                               │
│  Layer 4: 校准闭环                                                       │
│  python -m engine.backtest.calibrate                                     │
│         ↓                                                               │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │ outputs/backtest/calibration_log.yaml                           │    │
│  │   - 留一验证结果                                                 │    │
│  │   - 校准候选值                                                   │    │
│  │   - 状态：pending → applied → rolled_back                       │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

## 架构设计

```
┌─────────────────────────────────────────────────────────────────┐
│                        回测框架                                  │
├─────────────────────────────────────────────────────────────────┤
│  Layer 1: 案例定义                                               │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ data/backtest/cases.yaml (案例定义 + stage_labels)              │  │
│  │ - outcome: failure/success/success_to_failure/friendzone/half_success/developing/...  │  │
│  │ - stage_labels: stage/window_state/risk_state 切片级标签  │  │
│  └──────────────────────────────────────────────────────────┘  │
├─────────────────────────────────────────────────────────────────┤
│  Layer 2: 数据采集                                               │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ engine/backtest/collect.py                                │  │
│  │ - Phase A: 指标层（composite/neediness/volume_ratio）    │  │
│  │ - Phase B: 公式层（IVI/SPE/EWS/CS/Action）               │  │
│  │ - 事件对齐窗口（±7/14/30天）                             │  │
│  │ - 派生标签：distance_to_outcome, next_30d_outcome        │  │
│  │ - 敏感性分析模式（--sensitivity）                         │  │
│  └──────────────────────────────────────────────────────────┘  │
├─────────────────────────────────────────────────────────────────┤
│  Layer 3: 分析对比                                               │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ engine/backtest/analyze.py                                │  │
│  │ - 维度1: 案例内时序分析（时间曲线 + 转折点 + 预警评估）   │  │
│  │ - 维度2: composite 公式诊断（分布 + 重叠区间 + 阈值）    │  │
│  │ - 维度3: neediness_penalty 专项审计（volume/initiation） │  │
│  │ - 维度4: 跨案例模式归纳                                   │  │
│  │ - 维度5: 信号领先/滞后分析                                │  │
│  └──────────────────────────────────────────────────────────┘  │
│  ↓                                                               │
│  outputs/backtest/calibration_report.md                          │
├─────────────────────────────────────────────────────────────────┤
│  Layer 4: 校准闭环                                               │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ engine/backtest/calibrate.py                              │  │
│  │ - 留一验证（Leave-One-Case-Out）防止过拟合               │  │
│  │ - 校准候选值生成（基于描述性统计）                        │  │
│  │ - 校准日志记录（calibration_log.yaml）                    │  │
│  └──────────────────────────────────────────────────────────┘  │
│  ↓                                                               │
│  outputs/backtest/calibration_log.yaml                          │
└─────────────────────────────────────────────────────────────────┘
```

## 核心文件

| 文件 | 路径 | 功能 | 输出位置 |
|------|------|------|---------|
| 案例定义 | `data/backtest/cases.yaml` | 定义回测案例及其切片级标签 | - |
| 案例加载 | `engine/backtest/load_cases.py` | 统一案例加载基础设施（被 validate/retrospective/timeseries 等导入） | - |
| 数据采集 | `engine/backtest/collect.py` | Phase A/B 数据采集，事件对齐窗口，敏感性分析 | `outputs/backtest/{case_id}_phase_a.json` <br> `outputs/backtest/{case_id}_phase_b.json` |
| 数据验证 | `engine/backtest/validate.py` | 测试 ref_date/to_ts 参数正确性（防止数据泄漏） | 控制台输出 |
| 分析对比 | `engine/backtest/analyze.py` | 案例内时序分析，跨案例归纳，描述性统计报告 | `outputs/backtest/calibration_report.md` |
| 校准闭环 | `engine/backtest/calibrate.py` | 留一验证，校准候选值，校准日志 | `outputs/backtest/calibration_log.yaml` |
| 语义回测 | `engine/backtest/semantic_backtest.py` | B0'/B2 双模型三趟对比语义回测 | 控制台输出 |
| 标注分析 | `engine/backtest/analyze_annotated.py` | 基于用户标注分析 v2 指标区分度 | 控制台输出 |
| 时序分析 | `engine/backtest/timeseries.py` | composite 时间序列趋势分析 | 控制台输出 |
| 回溯分析 | `engine/backtest/retrospective.py` | 时间点回溯分析 | 控制台输出 |
| 全量扫描 | `engine/backtest/full_scan.py` | 全量联系人指标扫描 | 控制台输出 |
| 扫描分析 | `engine/backtest/analyze_scan.py` | 全量扫描结果分析 | 控制台输出 |
| 消息统计 | `engine/backtest/msg_count_stats.py` | 联系人消息数统计 | 控制台输出 |
| 回测方案 | `plan/回测方案.md` | 框架设计文档（核心方法、标签体系、分析维度） | - |
| 回测案例 | `plan/回测案例.md` | 案例分类定义（wxid 级别） | - |

## 端到端使用流程

### 第一步：准备案例定义

确保 `data/backtest/cases.yaml` 中所有案例都有完整的 `stage_labels`。

```bash
# 查看当前案例定义
cat data/backtest/cases.yaml
```

### 第二步：采集数据

#### Phase A：指标层采集

**用途**：快速验证指标层面的区分力，不涉及公式层的 manual 参数。适用于：
- 初步筛查 composite/neediness_penalty 是否能区分成功/失败案例
- 分析 volume_ratio/initiation_ratio 的实际分布
- 不需要公式层（IVI/SPE/EWS）分析的场景

```bash
# 采集所有案例的 Phase A 数据
python -m engine.backtest.collect

# 只采集指定案例
python -m engine.backtest.collect --case case_004

# 修改切片间隔（默认14天）
python -m engine.backtest.collect --slice-days 7
```

**输出**：`outputs/backtest/{case_id}_phase_a.json`

#### Phase B：公式层采集

**用途**：验证公式层的预警能力，涉及 manual 参数的敏感性分析。适用于：
- 需要分析 IVI/SPE/EWS/CS/Action 公式输出的场景
- 需要对比 default round（默认参数）和 truth round（手动参数）差异的场景
- 需要做敏感性分析的场景

**round 说明**：
- **default round**：使用 `formula_params` 返回的默认参数值
- **truth round**：使用 `data/backtest/cases.yaml` 中 `manual_truth` 字段指定的值（如果未配置，则与 default round 相同。当前所有案例均未配置 manual_truth，truth round 结果与 default round 相同）

**使用策略**：
1. **先用默认值跑全量**：对所有案例运行 Phase B（不带 --sensitivity），获取 baseline
2. **选代表性案例做敏感性分析**：选择 1-2 个典型案例（如 success_to_failure 案例"test_case_contact_A"），用 --sensitivity 模式做参数扫描
3. **对比分析**：根据敏感性分析结果，找出对公式输出影响最大的参数，重点校准

```bash
# 第一步：用默认值跑全量 Phase B
python -m engine.backtest.collect --phase B

# 第二步：选代表性案例做敏感性分析
python -m engine.backtest.collect --phase B --case case_004 --sensitivity
```

**输出**：
- `outputs/backtest/{case_id}_phase_b.json`
- `outputs/backtest/{case_id}_phase_b_sensitivity.json`（仅 --sensitivity 模式）

#### 何时只用 Phase A，何时需要 Phase B？

| 场景 | 只用 Phase A | 需要 Phase B |
|------|-------------|-------------|
| 验证 composite 区分力 | ✅ | - |
| 审计 neediness_penalty | ✅ | - |
| 分析案例内时序变化 | ✅ | - |
| 分析公式预警能力 | - | ✅ |
| 对比 manual 参数影响 | - | ✅ |
| 参数敏感性分析 | - | ✅ |

### 第三步：验证时间切片正确性

```bash
python -m engine.backtest.validate
```

**功能**：测试 `ref_date` 和 `to_ts` 参数是否正确生效（防止"偷看未来"数据泄漏），对少量案例做实时 vs 历史时间切片的指标对比打印。

### 第四步：生成校准报告

```bash
python -m engine.backtest.analyze
```

**输出**：`outputs/backtest/calibration_report.md`

### 第五步：运行校准闭环

```bash
# 运行留一验证，生成校准候选值，写入日志
python -m engine.backtest.calibrate

# 模拟模式（不写日志，仅在控制台输出）
python -m engine.backtest.calibrate --dry-run
```

**输出**：`outputs/backtest/calibration_log.yaml`

### 第六步：应用校准（手动）

1. **审核校准候选值**：查看 `calibration_log.yaml` 中的 `candidates` 字段
2. **修改参数**：
   - neediness_penalty 阈值：修改 `engine/analyzers/metrics.py`
   - composite 信号阈值：修改 `engine/config.py` 或相关配置
3. **重新采集**：运行 `python -m engine.backtest.collect`（或仅重新分析）
4. **效果对比**：运行 `python -m engine.backtest.analyze` 查看效果变化
5. **更新状态**：手动修改 `calibration_log.yaml` 中对应 entry 的 `status` 字段

## 案例定义

### 案例结构

```yaml
cases:
  - id: "case_004"
    display_name: "[REDACTED]"
    outcome: "success_to_failure"  # failure/success/success_to_failure/friendzone/half_success/developing/active_giveup/passive_giveup/awkward/topic_mismatch/lost_contact
    outcome_date: "2025-08-22"
    started: "2025-03-17"
    notes: "刚开始她主动，后期我暴露需求感太多"
    
    # 切片级标签（关键）
    stage_labels:
      - from: "2025-03-17"
        to: "2025-05-01"
        stage: "热恋期"
        window_state: "open"      # open/closing/closed
        risk_state: "low"         # low/medium/high
      - from: "2025-05-01"
        to: "2025-07-01"
        stage: "降温期"
        window_state: "closing"
        risk_state: "medium"
    
    # 手动参数（可选，用于 truth round）
    manual_truth:
      Pface: 0.7
      Ddepth: 0.5
```

### 切片级标签体系

| 字段 | 取值 | 含义 |
|------|------|------|
| `stage` | 初识期/互动期/暧昧期/热恋期/稳定期/降温期/冷淡期/破裂前/分手前/友谊区 | 关系阶段 |
| `window_state` | open/closing/closed | 关系窗口状态 |
| `risk_state` | low/medium/high | 风险等级 |

### 派生标签

采集时自动计算：

| 字段 | 含义 |
|------|------|
| `distance_to_outcome_days` | 距离最终结果的天数 |
| `next_30d_outcome` | 未来30天的预期结果（基于 stage_labels） |
| `distance_to_next_event_days` | 距离下一个关键事件的天数 |

## 分析维度

### 维度1：案例内时序分析（主分析）

对每个案例分析指标随时间的变化，识别转折点和预警能力。

**输出内容**：
- 时间曲线：composite / fback / neediness_penalty / signal_level
- 阶段标注：基于 stage_labels 标注每个时间点的阶段和风险状态
- 预警评估：系统在风险升级前是否发出了有效预警

### 维度2：Composite 公式诊断

**输出内容**：
- 全量切片分布：min/max/mean/p25/p50/p75
- 分组对比：成功组 vs 失败组的分布差异
- 重叠区间：两组的分布重叠程度
- 信号等级阈值诊断：当前阈值（0.50/0.30）是否合理

### 维度3：Neediness_Penalty 专项审计

分析需求感惩罚的实际触发情况。

**输出内容**：
- 逐案例触发情况：哪些案例触发了惩罚，触发时的指标值
- volume_ratio 分布：我的消息数/她的消息数的实际分布
- initiation_ratio 分布：我发起/总发起的实际分布
- 触发条件评估：当前阈值（volume_ratio > 1.3）是否合理

### 维度4：跨案例模式归纳

汇总各案例的时序分析结果，识别共性模式。

**输出内容**：
- 成功案例的共同特征
- 失败案例的共同特征
- 成功→失败案例的转折点特征
- 友谊区案例的特征

### 维度5：信号领先/滞后分析

评估公式的预警能力。

**输出内容**：
- 信号领先天数：预警信号比实际破裂提前了多少天
- rounds_differ 警告：当 truth round 和 default round 结果不同时标记
- 基于默认参数的分析警告

## 报告模板

`outputs/backtest/calibration_report.md` 格式：

```markdown
# 回测校准报告

> 用 N 个案例 × M 个时间切片 = X 个数据点
> 对系统 K 个参数进行 ground truth 审判
> 分析方法：案例内时序分析（主） + 描述性组间对比（辅），不做推断统计

## 一、案例内时序分析（每个案例一条曲线）

### 案例1: XXX (outcome)
- 时间曲线图（composite/fback/neediness 三条线 + key_events 标注）
- 转折点分析：哪些指标在转折点前后有变化？领先多少天？
- 预警评估

## 二、跨案例模式归纳
- 哪些指标在多个案例中表现一致？
- 成功案例的曲线形状 vs 失败案例的曲线形状

## 三、composite 公式诊断
- 全量切片分布
- 信号等级阈值诊断
- 诊断问题清单

## 四、neediness_penalty 专项审计
- 逐案例触发情况
- 触发条件实际分布（volume_ratio 和 initiation_ratio）
- 审计结论

## 五、阈值校准建议
### 5.1 高置信度（描述性证据充分）
### 5.2 低置信度（需要更多案例或数据）
### 5.3 需要重构的参数
```

## 成功判据（量化目标）

校准闭环需要明确的验收标准，否则就是"看图说话"。

| 判据 | 含义 | 测量方法 | 当前基线 | 目标 |
|------|------|---------|---------|------|
| **转折预警 lead time** | 指标恶化领先关系破裂多少天 | 对每个失败/先成后败案例，计算最早出现指标恶化的切片距 outcome_date 的天数 | 待测 | > 14 天（有实操价值） |
| **warning precision** | 系统发出预警时，有多少是真正需要警惕的？ | TP / (TP + FP)，预警 = composite 下降 + neediness 触发 + signal 降级 | 待测 | > 0.6（不过多误报） |
| **warning recall** | 真正需要警惕的关系中，系统发出了多少预警？ | TP / (TP + FN)，分母 = 所有失败/先成后败案例的关键切片 | 当前 0%（neediness 0 触发） | > 0.5 |
| **rank correlation** | 成功/失败阶段排序是否改善 | 校准前后，用 stage_label（好时期 vs 坏时期）检验 composite 排序一致性 | 当前：成功&失败 composite 重叠 | 校准后：分布拉开且不牺牲案例内趋势解释 |
| **calibration delta** | 调参后 composite 分布拉开多少 | 校准前/后成功组 vs 失败组 composite 重叠比例的变化 | 当前重叠 ~95% | 重叠 < 70%（有可见区分） |

**注意**：这些判据在当前案例数上只能做初步估计。precision/recall 需要更多案例（尤其是失败案例）才能稳定。目标值标记为"期望方向"，具体数值需要在第一轮校准后根据实际改善幅度重新设定。

## 结果解读指南

### Composite 分析解读

| 指标 | 判定标准 | 解读 |
|------|---------|------|
| 重叠比例 | < 30% | 优秀：成功/失败组区分度好 |
| 重叠比例 | 30%-50% | 一般：有区分力但不明显 |
| 重叠比例 | > 50% | 差：composite 无法有效区分 |
| 风险差异 gap | > 0.15 | 优秀：高/低风险组有显著差异 |
| 风险差异 gap | 0.05-0.15 | 一般：有差异但较小 |
| 风险差异 gap | < 0.05 | 差：composite 对风险不敏感 |

### Neediness_Penalty 审计解读

| 指标 | 判定标准 | 解读 |
|------|---------|------|
| 触发率 | 0% | 阈值过高，需要下调 |
| 触发率 | 5%-20% | 合理：惩罚只在极端情况触发 |
| 触发率 | > 20% | 阈值过低，需要上调 |
| volume_ratio > 1.3 | < 5% | 阈值 1.3 可能仍偏高 |
| volume_ratio > 1.3 | 5%-15% | 阈值 1.3 合理 |
| initiation_ratio > 0.6 | 0% | 可考虑降至 0.55 |

### 校准候选值解读

| confidence | loco_confidence | 建议 |
|------------|-----------------|------|
| high | high | 强烈建议采纳 |
| high | medium | 可考虑采纳，需进一步验证 |
| high | low | 谨慎采纳，留一验证未通过 |
| medium | high | 可采纳，优先级低于 high/high |
| medium | medium | 建议观察，不急于采纳 |
| medium | low | 不建议采纳 |

### 留一验证解读

| 通过比例 | 解读 |
|---------|------|
| >= 70% | 优秀：模型稳定性好，参数可推广 |
| 50%-70% | 一般：模型有一定稳定性，建议增加案例数 |
| < 50% | 差：模型不稳定，过拟合风险高 |

## 校准闭环

### 留一验证（Leave-One-Case-Out）

对每个案例留出，用其余案例计算阈值，在留出案例上验证效果。

**评估指标**：
- 训练集/测试集的重叠比例变化
- 训练集/测试集的风险差异变化
- 是否通过验证（overlap_ratio 降低 或 risk_gap 保持 > 50%）

### 校准候选值生成

基于描述性统计自动生成参数调整建议：

| 参数 | 当前值 | 候选值来源 |
|------|--------|-----------|
| neediness_penalty.volume_ratio_threshold | >1.3 | volume_ratio 分布的 pct_gt_13/pct_gt_15 |
| neediness_penalty.initiation_ratio_threshold | >0.6 | initiation_ratio 分布的 pct_gt_06/pct_gt_07 |
| composite.signal_medium_threshold | >=0.50 | composite 分布的 p75 |

### 校准流程详解

```
1. 参数调整
   └─→ 修改文件：engine/analyzers/metrics.py（neediness 阈值）
       修改文件：engine/config.py（信号阈值）
       修改文件：engine/formulas.py（公式参数）

2. 重新采集（可选）
   └─→ python -m engine.backtest.collect        # 如果修改了指标计算逻辑
       python -m engine.backtest.collect --phase B  # 如果修改了公式参数

3. 效果对比
   └─→ python -m engine.backtest.analyze
       └─→ 查看重叠比例是否降低
       └─→ 查看风险差异是否增大

4. 留一验证
   └─→ python -m engine.backtest.calibrate
       └─→ 查看通过比例是否 >= 50%

5. 确认/回滚
   └─→ 通过：手动修改 calibration_log.yaml 中 status 为 "applied"
       未通过：恢复原参数，手动修改 status 为 "rolled_back"
```

### 校准日志状态生命周期

| 状态 | 触发条件 | 操作人 | 说明 |
|------|---------|--------|------|
| `pending` | 运行 calibrate.py 生成候选值后 | 系统自动 | 候选值已生成，等待审核 |
| `applied` | 审核通过并修改了参数后 | 用户手动 | 参数已应用到代码中 |
| `rolled_back` | 参数应用后验证失败，恢复原参数 | 用户手动 | 参数已回滚，不生效 |

### 校准日志结构

每次校准记录：

| 字段 | 内容 |
|------|------|
| date/timestamp | 校准时间 |
| cases_used | 使用的案例列表 |
| total_slices | 切片总数 |
| baseline_metrics | 当前基线指标（重叠比例、风险差异等） |
| loco_validation | 留一验证结果（通过/失败数、详细结果） |
| candidates | 校准候选值（参数名、当前值、候选值、理由、置信度） |
| status | pending/applied/rolled_back |

### 校准日志 YAML 示例

```yaml
- date: 2026-07-20
  timestamp: "2026-07-20T14:30:00"
  cases_used: ["case_001", "case_002", "case_003", "case_004"]
  total_slices: 48
  baseline_metrics:
    overlap_ratio: 0.95
    risk_gap: 0.02
  loco_validation:
    passes: 6
    total: 8
    results:
      - case: "case_001"
        passed: true
      - case: "case_004"
        passed: false
  candidates:
    - param: neediness_penalty.volume_ratio_threshold
      current: ">=0.35"
      candidate: 1.3
      reason: "volume_ratio 分布显示 pct_gt_13=15%"
      confidence: medium
      loco_confidence: medium
    - param: composite.signal_medium_threshold
      current: ">=0.50"
      candidate: 0.35
      reason: "中窗口阈值 0.50 无切片达到"
      confidence: low
      loco_confidence: low
  status: pending
```

## 敏感性分析

对9个关键 manual 参数做扫描（0.1→0.9，步长0.2）：

| 参数 | 扫描范围 | 影响公式 |
|------|---------|---------|
| Pface | 0.1, 0.3, 0.5, 0.7, 0.9 | IVI, IS |
| Ddepth | 0.1, 0.3, 0.5, 0.7, 0.9 | SPE |
| Target_Ddepth | 0.1, 0.3, 0.5, 0.7, 0.9 | SPE |
| Cp_Index | 0.0, 0.2, 0.4, 0.6, 0.8, 1.0 | EWS |
| Backstage | 0.1, 0.3, 0.5, 0.7, 0.9 | IS |
| Internal_D | 0.1, 0.3, 0.5, 0.7, 0.9 | CS |
| External_R | 0.1, 0.3, 0.5, 0.7, 0.9 | CS |
| P_succ | 0.1, 0.3, 0.5, 0.7, 0.9 | EEV, Action |
| P_fail | 0.1, 0.3, 0.5, 0.7, 0.9 | EEV, Action |

**输出**：每个参数的扫描结果 + 敏感性范围（ivi_range/spe_range/ews_range）

**敏感性解读**：

| 范围 | 解读 |
|------|------|
| > 0.3 | 高敏感：参数变化对输出影响大，需要精确校准 |
| 0.1-0.3 | 中敏感：参数变化有一定影响，但不需要太精确 |
| < 0.1 | 低敏感：参数变化影响小，默认值即可 |

## Agent 分析回测（并行轨道）

### 为什么 Agent 回测不需要等公式校准

Agent 分析的输入是 `brief_data` + `chat_data` + Wiki 知识库——这些都是**原始数据**，不是公式输出的 composite。公式不准不影响 Agent 判断。实际上，即使 composite=0.28（"冷淡"），Agent 读了聊天记录后可以判断"这个人在主动延续话题、分享日常，关系其实不错"——Agent 应该能纠正公式的误判。

反过来，Agent 回测能直接验证**刚实现的 wiki_context 工具**是否提升了分析质量。这是公式回测做不到的：在同一切片时间点，给 Agent 两组 wiki 参数（旧：discrete wiki_search/wiki_read vs 新：wiki_context with stage/focus），看分析结论的差异。

### 防泄漏措施（as-of 数据隔离）

Agent 回放最严重的风险不是公式参数，而是**数据泄漏**——Agent 不小心读到了切片时间点之后的数据。

**SQL 层面的泄漏**已在 Layer 2 通过 `ref_date` + `to_ts` 解决。

**事实档案层面的泄漏**需要额外处理：`person_evidence` 返回的事实档案中，notes/events/dates 有写入时间（`[YYYY-MM-DD]` 前缀），evaluations 和 analysis 也有时间戳。Agent 回放切片 Ti 时，必须只看到 Ti 之前写入的事实。需要：
- `engine/facts/people_archive.py` 的事实档案读取需要增加 `before_date` 参数，只返回该日期之前写入的内容
- Agent 回放脚本调用 `person_evidence(name, before_date=Ti)`
- **严禁** Agent 在回放中读取 `data/outputs/analysis/` 下的历史分析报告（那是事后写的）

### 方案：Agent 回放（离线脚本，不经过 MCP）

Agent 回放需要一个独立的离线脚本 `engine/backtest/agent_replay.py`，**不经过 MCP 工具**。原因：
- MCP 工具（person_brief/person_chat/person_evidence 等）返回的是当前状态的数据，无法注入 `ref_date`/`before_date`
- 离线脚本直接调用 engine 层函数，可以精确控制数据的时间范围
- `mcp_server/` 不需要为此改造——公式回测轨道和 Agent 回放轨道使用不同的数据入口

```
engine/backtest/agent_replay.py 的数据组装流程：

对每个时间切片 Ti：
  1. brief_data(name, ref_date=Ti, to_ts=to_timestamp(Ti))
  2. chat_data(name, recent=50, to_ts=to_timestamp(Ti))
  3. person_evidence(name, before_date=Ti)  ← 新增参数
  4. wiki_context(queries, stage=..., focus=...)
  5. 组装为 prompt，让 Agent 在只看到上述数据的条件下分析
  6. 人工对比 Agent 结论 vs 后来实际的走向
```

### 评判维度

| 维度 | 问题 |
|------|------|
| 阶段判断 | Agent 当时对关系阶段的判断是否准确？ |
| 信号敏感度 | 是否捕捉到了关键信号（如降温的早期迹象）？ |
| 策略质量 | 给出的建议在当时是否合理？ |
| Wiki 运用 | 是否引用了合适的 Wiki 框架？wiki_context 的 stage/focus 参数是否提升了检索质量？ |
| 风险预警 | 是否提前识别了风险？ |

### 实现状态

**尚未实现**。Agent 回测是并行轨道，当前优先完成公式回测轨道。待公式回测稳定后，再开发 `agent_replay.py` 和事实档案读取的 `before_date` 参数。

## 数据流程

### Phase A 数据链路

```
compute_metrics_for_contact()
    → Metrics.composite
    → Metrics.neediness_penalty
    → Metrics.volume_ratio
    → Metrics.initiation_ratio
    → Metrics.all_metrics() → dict
    → 切片级标签（stage/window_state/risk_state）
    → 派生标签（distance_to_outcome, next_30d_outcome）
    → JSON 文件：outputs/backtest/{case_id}_phase_a.json
```

### Phase B 数据链路

```
formula_params()
    → auto 参数（Sp/Fback/User_Investment/Ve/Exp等）
    → raw_metrics（composite/avg_her_seconds/rlatency_raw等）
    → manual 参数（Pface/Ddepth/Cp_Index等）
    → formula_ivi/formula_spe/formula_ews/formula_cs/formula_action
    → rounds: [default, truth]
    → sensitivity_scan（可选，仅 --sensitivity 模式）
    → JSON 文件：outputs/backtest/{case_id}_phase_b.json
```

## 关键修复记录

| 问题 | 修复方式 | 影响 |
|------|---------|------|
| Cohen's d 公式缺少平方根 | 移除推断统计，改用描述性统计 | 效应量不再被放大10-100倍 |
| neediness audit 用错指标 | 使用 volume_ratio 而非 fback_raw | 阈值建议基于正确数据 |
| SPE target_latency 语义错误 | 使用 avg_her_seconds（绝对秒数）而非 rlatency_raw（比值） | SPE 不再恒等于0.5 |
| 信号领先分析只用 default round | 优先使用 truth round，标记参数差异 | 分析结果可信 |
| pct_gt_06 死代码 | 在 analyze_neediness_audit 中新增该字段 | calibration 不再永远返回0 |
| __round_name 未注入 | 在 rounds_config 循环中注入 round_name | round name 字段正确 |

## 注意事项

1. **数据采集前需同步**：确保数据库中有最新的聊天记录
2. **案例定义需准确**：stage_labels 的时间范围必须覆盖整个案例周期
3. **敏感性分析耗时**：--sensitivity 模式对每个切片扫描9个参数×5-6个值，耗时较长
4. **留一验证需要足够案例数**：建议至少5个案例才能进行有效验证
5. **校准日志需定期审核**：跟踪参数调整历史，避免过度拟合
6. **Phase B 依赖 Phase A**：运行 Phase B 前必须先完成 Phase A 采集
7. **参数修改后需重新采集**：如果修改了指标计算逻辑，需要重新采集数据
8. **回测频率**：建议每次修改参数后运行回测；每周至少运行一次；每次有新案例后运行一次
9. **维护成本**：每个案例的 stage_labels 标注约需 10-15 分钟；案例有新进展后需要更新 labels