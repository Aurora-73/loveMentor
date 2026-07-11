---
name: metrics-system
description: 15+1 维指标体系详解（15个有效加权指标 + 1旧版兼容指标 qscore 权重为0） — 权重、计算方式、解读方法
---

# 15+1维指标体系

> 15 个有效加权指标 + 1 个旧版兼容指标（qscore 权重为 0）。以下表格列出全部。

## 指标总览

| 指标 | 含义 | 权重 | 计算方式 |
|------|------|------|---------|
| fback | 回复字数比（她/你） | 0.10 | 对方消息总字数 / 你的消息总字数 |
| rlatency | 回复速度比（你/她） | 0.10 | 你的平均回复时间 / 对方平均回复时间 |
| fback_quality | 回复质量 | 0.10 | 正向情绪词+追问-敷衍词 |
| qscore_personal | 个人化问题比例 | 0.10 | 个人化问题数 / 总问题数 |
| trend | 周变化趋势 | 0.10 | 本周composite / 上周composite |
| escore_volatility | 情绪波动 | 0.08 | 情绪评分标准差 |
| moments | 朋友圈互动频率 | 0.06 | 互动次数 / 朋友圈总数 |
| qscore_functional | 工具化问题比例 | 0.05 | 工具化问题数 / 总问题数 |
| rlatency_context | 慢回时有解释比例 | 0.05 | 慢回带解释的次数 / 慢回总次数 |
| msg_volume_trend | 消息量周变化率 | 0.05 | 本周消息量 / 上周消息量 |
| latency_trend | 回复速度周变化率 | 0.05 | 本周平均回复时间 / 上周平均回复时间 |
| recent | 最后消息距今天数 | 0.05 | 当前日期 - 最后消息日期 |
| active_days | 活跃天数 | 0.04 | 30天内有消息的天数 |
| escore | 情绪表达比例 | 0.05 | 情绪词数 / 总词数 |
| msg_count | 消息总数 | 0.02 | log(消息总数) |
| qscore | 问号比例（旧版） | 0.00 | 问题数 / 总消息数 |

**MCP工具**：`person_metrics(name)` 【MCP工具】

---

## 乘法惩罚

**neediness_penalty**（0.4-1.0）

触发条件：
- 消息量比 > 2（对方:你）
- 发起频率 > 70%

**影响**：最终 composite = 原始 composite × neediness_penalty

**Wiki参考**：`[[需求感]]`

---

## 信号等级

| 等级 | 阈值 | 含义 | 行动建议 |
|------|------|------|---------|
| 强窗口 | >= 0.70 | 强烈兴趣信号 | 可以推进关系 |
| 中窗口 | >= 0.50 | 中等兴趣信号 | 继续观察 |
| 弱窗口 | >= 0.30 | 微弱兴趣信号 | 需要刺激 |
| 冷淡 | >= 0.15 | 冷淡 | 需要重新吸引 |
| 无信号 | < 0.15 | 无兴趣 | 考虑放弃或重置 |

**MCP工具**：`person_signals(name)` 【MCP工具】— signal_level

---

## 动态信号

| 信号 | 含义 | 解读 |
|------|------|------|
| session_recency | 最近活跃时间 | 越近越好 |
| momentum | 7天动量 | 正动量表示升温 |
| initiation_source | 谁发起对话 | 对方发起是IOI |
| composite_slope | composite趋势斜率 | 回测验证有区分力：>+0.005上升(健康)，<-0.005下降(预警)，之间平稳。取3个时间点(0d/-7d/-14d)线性回归，不参与composite加权，Agent读取作为趋势信号 |

**composite_slope 详解**：在 `compute_slope=True` 时计算（brief_data/agent_metrics/maintain 等单联系人场景自动启用，ranker 不启用）。extra 含 trend_label(上升/下降/平稳) 和 history(各点 composite 值)。不活跃联系人(近30天无消息)返回中性值(normalized=0.5, sample_size=0)。

---

## 指标解读原则

1. **不要孤立看单个指标**：要综合多个指标判断
2. **趋势比绝对值重要**：持续上升比单次高分更有意义
3. **结合 Wiki 知识**：每个指标都有对应的 Wiki 框架解读
4. **不要机械套用阈值**：阈值是参考，不是硬规则