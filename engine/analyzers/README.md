# Analyzers 分析引擎

## 概述

`engine/analyzers/` 是数据**分析计算层**，负责从原始聊天数据中提取量化指标、识别关系阶段、检测关键事件、生成排名和周报。所有分析器都是纯计算函数，无副作用，通过 `engine/agent/` 层被 Agent 工具调用。

## 架构定位

```
data/raw/core.db（原始消息数据）
    │
    └── engine/analyzers/（分析计算）
            │
            ├── metrics.py          → 15维指标计算
            ├── ranker.py           → 联系人排名
            ├── events.py           → 关系事件检测
            ├── stage_recognizer.py → 关系阶段识别
            ├── weekly_report.py    → 周报生成
            ├── chat_history.py     → 聊天记录查询
            └── exclude.py          → 排除逻辑
```

## 模块清单

| 文件 | 职责 | 核心功能 |
|------|------|---------|
| `metrics.py` | 指标计算引擎 | 15维加权指标、乘法惩罚、信号等级、互动模式、动态信号 |
| `ranker.py` | 排名引擎 | 按 composite 分数排序、数据可信度计算、快照管理 |
| `events.py` | 事件检测 | 首次聊天、断联、恢复联系、频率变化检测 |
| `stage_recognizer.py` | 关系阶段识别 | 9个阶段自动识别（初识→有基本互动→高频聊天→已约见→持续接触→暧昧推进→关系确认→冷淡→退出） |
| `weekly_report.py` | 周报生成 | 排名快照 + 趋势 + Markdown 报告 |
| `chat_history.py` | 聊天记录查询 | 按时间/关键词/发送者过滤消息 |
| `exclude.py` | 排除逻辑 | 硬排除、标签排除、手动排除管理 |

## 核心分析器详解

### metrics.py — 指标计算引擎

**15维有效加权指标**：

| 指标 | 含义 | 权重 |
|------|------|------|
| fback | 回复字数比（她/你） | 0.10 |
| rlatency | 回复速度比（你/她） | 0.10 |
| fback_quality | 回复质量（正向情绪+追问-敷衍） | 0.10 |
| qscore_personal | 个人化问题比例（IOI） | 0.10 |
| trend | composite 周变化 | 0.10 |
| escore_volatility | 情绪波动（会话间标准差） | 0.08 |
| moments | 朋友圈互动频率 | 0.06 |
| qscore_functional | 工具化问题比例（供养者信号） | 0.05 |
| rlatency_context | 慢回时有解释的比例 | 0.05 |
| msg_volume_trend | 消息量周变化率 | 0.05 |
| latency_trend | 回复速度周变化率 | 0.05 |
| recent | 最后消息距今天数 | 0.05 |
| active_days | 活跃天数（30天窗口） | 0.04 |
| escore | 情绪表达比例 | 0.05 |
| msg_count | 消息总数（对数归一化） | 0.02 |

**乘法惩罚**：`neediness_penalty`（0.4-1.0）
- 触发条件：消息量比 > 2 或发起频率 > 70%
- 影响：最终 composite = 原始 composite × neediness_penalty

**信号等级**：
- 强窗口(≥0.70) / 中窗口(≥0.50) / 弱窗口(≥0.30) / 冷淡(≥0.15) / 无信号(<0.15)

**互动模式**：lover / provider / neutral

### stage_recognizer.py — 关系阶段识别

**9个阶段**：

| 阶段 | 特征 |
|------|------|
| 初识 | 刚认识，礼貌性回复，话题浅层 |
| 有基本互动 | 有来有回但停留在表面 |
| 高频聊天 | 经常聊天，主动分享日常，回复快 |
| 已约见 | 已经线下见过面 |
| 持续接触 | 见面后继续保持联系 |
| 暧昧推进 | 明确好感信号：主动、撒娇、吃醋 |
| 关系确认 | 已确认恋爱关系 |
| 冷淡/停滞 | 兴趣下降：回复变短、不再主动 |
| 退出/失败 | 基本不再联系，或明确拒绝 |

### events.py — 事件检测

**检测类型**：

| 事件类型 | 检测逻辑 |
|----------|---------|
| 首次聊天 | 最早消息时间 |
| 断联 | 连续 N 天无消息（默认 7 天） |
| 恢复联系 | 断联后重新开始聊天 |
| 频率变化 | 7天窗口内消息量翻倍或减半 |

### ranker.py — 排名引擎

**排名逻辑**：
- 按 composite 分数降序排列
- 支持排除列表过滤
- 计算数据可信度（基于消息量和会话覆盖率）
- 支持历史快照保存和恢复

## 设计原则

1. **纯计算**：所有分析器都是纯函数，无副作用
2. **可测试**：输入明确，输出可验证
3. **可配置**：通过 `config.yaml` 调整权重和阈值
4. **向后兼容**：新增指标不影响旧指标计算

## 调用关系

```
agent/brief.py → analyzers/metrics.py (获取指标)
agent/chat.py → analyzers/chat_history.py (查询消息)
agent/signals.py → analyzers/metrics.py (获取信号)
agent/signals.py → analyzers/stage_recognizer.py (识别阶段)
agent/signals.py → analyzers/events.py (检测事件)
agent/report.py → analyzers/ranker.py (生成排名)
agent/report.py → analyzers/weekly_report.py (生成周报)
```

## 参考文档

- 分析器详细文档：`readme/analyzers.md`
- 指标体系详解：`skill/metrics/metrics_system.md`
