# Analyzers 模块说明

## 指标窗口

大部分指标默认 30 天窗口，`active_days` 也是 30 天。可通过 config 调整。

## 会话分割

`rlatency` 等指标需要定义"什么是同一会话"。`metrics.py` 中各指标函数默认连续消息间隔 > 4 小时视为不同会话（`session_gap_hours: int = 4`，与 `config.py` 默认值一致）。注意 `interaction_sequence.py` 的 TurnPair 分析默认使用 6 小时（`DEFAULT_SESSION_GAP_HOURS = 6`）。

## Neediness Penalty

乘法惩罚，不是加法。两个独立组件：

- **消息量比惩罚**：`volume_ratio = 你发消息数 / 她发消息数`，当 `> 1.3` 时触发，惩罚系数 `1.0 - (excess * 0.3)`，下限 **0.5**
- **发起频率惩罚**：`initiation_ratio = 你主动发起消息的比例`，当 `> 0.6`（60%）时触发，惩罚系数 `1.0 - (excess * 2.0)`，下限 **0.4**
- 最终 `neediness_penalty = min(volume_penalty, initiation_penalty)`，整体下限 0.4

## 排名快照

周报会保存 YAML 快照到 `data/outputs/rankings/`，用于检测排名变化。

## 排除不可逆

手动排除后，排名中不再出现该联系人，但消息数据不受影响。
