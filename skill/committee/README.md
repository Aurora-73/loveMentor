---
name: committee-subagent
description: |
  委员会审查 subagent 设计 — 5 个独立 subagent 并行审查回复草案。
  主 agent 通过 Task 工具开 subagent，prompt 巆异化实现确认偏差防护。
  触发：auto_reply workflow 第 5 步
---

# 委员会审查 subagent 设计（v4 7.5 节实现）

## 核心架构

```
主 Agent (auto_reply workflow)
    ├─ 生成回复草案
    ├─ 并行开 5 个 subagent（Task 工具，单消息多 tool calls）
    │   ├─ 拟人度审查官      → humanlike.md
    │   ├─ 用户一致性审查官   → consistency.md
    │   ├─ 感情推进审查官     → progression.md
    │   ├─ 风险审查官（硬否决）→ risk.md
    │   └─ 邀约窗口审查官     → invite_window.md
    ├─ 收集 5 份审查意见（JSON）
    └─ 综合裁决（通过 / 修改后通过 / 驳回重写）
```

**关键原则**：
- 主 agent = 策略作者（写草案）
- subagent = 独立审查者（不共享上下文，只看主 agent 透露的信息）
- 信息隔离 = 每个审查官只接收其角度所需的信息，防止信息过载和交叉污染

## 5 官职责表（v4 7.1 节）

| 审查官 | 核心问题 | prompt 文件 | 输入 | 硬否决权 |
|--------|---------|------------|------|---------|
| 拟人度 | 像不像真人发的？ | humanlike.md | 草案 + 基于 Wiki 状态性聊天原则 + 上下文自然度 | 否（建议性） |
| 用户一致性 | 符合用户真实人设吗？ | consistency.md | 草案 + fact + fabricated_facts + recent_summary | 否（建议性） |
| 感情推进 | 对推进感情有帮助吗？ | progression.md | 草案 + Wiki 方法论 + 关系阶段 + 情绪趋势 + pending_items | 否（策略主导） |
| 风险 | 有风险吗？ | risk.md | 草案 + Wiki 禁忌 + avoid_topics + landmine_topics | **是（硬否决）** |
| 邀约窗口 | 当前是邀约窗口吗？ | invite_window.md | 对话线索 + IOI 信号 + 关系阶段（不审查草案） | 否（窗口报告） |

## 信息隔离矩阵

| 信息 | 拟人度 | 用户一致性 | 感情推进 | 风险 | 邀约窗口 |
|------|--------|----------|---------|------|---------|
| 回复草案 | ✅ | ✅ | ✅ | ✅ | ❌ |
| 用户话题画像 (facts_topics) | ❌ | ❌ | ❌ | ❌ | ❌ |
| 用户事实档案 (fact) | ❌ | ✅ | ❌ | ❌ | ❌ |
| recent_summary | ❌ | ✅ | ✅ | ❌ | ❌ |
| Wiki 方法论 | ❌ | ❌ | ✅ | ❌ | ❌ |
| 关系阶段 | ❌ | ✅ | ✅ | ❌ | ✅ |
| 情绪趋势 | ❌ | ❌ | ✅ | ❌ | ✅ |
| pending_items | ❌ | ❌ | ✅ | ❌ | ✅ |
| Wiki 禁忌 | ❌ | ❌ | ❌ | ✅ | ❌ |
| avoid_topics | ❌ | ❌ | ❌ | ✅ | ❌ |
| landmine_topics | ❌ | ❌ | ❌ | ✅ | ❌ |
| 对话线索 (current_threads) | ❌ | ❌ | ❌ | ❌ | ✅ |
| IOI 信号 | ❌ | ❌ | ❌ | ❌ | ✅ |

**隔离理由**：每个审查官只看与其角度相关的信息，避免被无关信息干扰，也防止泄露策略意图给风险官（风险官应独立判断，不应知道"为什么这么写"）。

## 输出格式（固化 schema，v4 7.3 节）

### 4 个审查官（拟人度/用户一致性/感情推进/风险）— 统一核心 schema

```json
{
  "verdict": "pass | modify | reject",
  "hard_block": false,
  "reasons": [
    {
      "type": "问题分类",
      "severity": "none | low | medium | high",
      "description": "问题描述 + 具体修改建议",
      "evidence": "引用草案原文 + Wiki/档案/线索证据"
    }
  ],
  "required_changes": ["必须修改的点（仅 modify/reject 时填，空数组 pass 时）"]
}
```

**字段说明**：
- `verdict`：审查结论（pass 通过 / modify 微调后通过 / reject 驳回重写）
- `hard_block`：是否硬否决（仅 risk 官可为 true；其他 3 官固定 false）。true 时主 agent 必须驳回，不可覆盖
- `reasons`：审查发现的所有问题/建议（合并原 issues + suggestions）。每条包含 type/severity/description/evidence
- `required_changes`：必须修改的点（原 must_fix）。pass 时为空数组 `[]`

**各官扩展字段**（保留特色，作为核心 schema 的补充）：
- consistency 官：`checks`（3 项检查结果）、`fabrication_needed`（需记录的编造内容）
- progression 官：`strategy_assessment`（5 维度策略评估）
- risk 官：`risk_checks`（7 类风险检查结果）

### 邀约窗口审查官（不同格式，不审查草案）

```json
{
  "window_detected": true | false,
  "window_type": "IOI_cluster | compliance_test | hint | stage_transition | null",
  "confidence": 0.0,
  "signals_found": [
    {
      "type": "IOI | compliance | hint | stage_transition",
      "description": "信号描述",
      "evidence": "引用原文"
    }
  ],
  "recommendation": "invite_now | wait | not_applicable"
}
```

## 主 agent 编排示例

### 步骤 1：准备各审查官的输入

主 agent 在生成回复草案后，从已有数据中提取各审查官所需信息：

```python
# 主 agent 已有的数据（来自 auto_reply workflow 前 4 步）
reply_draft = "生成的回复草案"
contact_name = "alice"
relationship_stage = "stage_2"
user_profile_fact = open("data/user_profile_fact.yaml").read()
user_fabricated_facts = open("data/user_fabricated_facts.yaml").read()
user_facts_topics = open("data/user_facts_topics_profile.yaml").read()
conversation_thread_data = {...}  # 来自 conversation_thread 工具
wiki_context_data = {...}  # 来自 wiki_context 工具
```

### 步骤 2：并行调用 5 个 subagent（单消息多 Task tool calls）

主 agent 在**一条消息中**发起 5 个 Task 工具调用（并行执行）：

```
// 在同一条 assistant 消息中：
Task(
    subagent_type="general_purpose_task",
    description="拟人度审查",
    query=<humanlike.md 模板填充后的完整 prompt>
)
Task(
    subagent_type="general_purpose_task",
    description="用户一致性审查",
    query=<consistency.md 模板填充后的完整 prompt>
)
Task(
    subagent_type="general_purpose_task",
    description="感情推进审查",
    query=<progression.md 模板填充后的完整 prompt>
)
Task(
    subagent_type="general_purpose_task",
    description="风险审查",
    query=<risk.md 模板填充后的完整 prompt>
)
Task(
    subagent_type="general_purpose_task",
    description="邀约窗口检测",
    query=<invite_window.md 模板填充后的完整 prompt>
)
```

### 步骤 3：收集结果并综合裁决

主 agent 收到 5 份 JSON 结果后，按以下规则裁决：

**裁决规则**（v4 7.3-7.4 节，基于固化 schema）：

| 情况 | 裁决 | 动作 |
|------|------|------|
| 任一官 `hard_block=true` | **硬否决** | 驳回重写，不可覆盖（仅 risk 官可触发） |
| ≥2 官 `verdict="reject"` | 严重驳回 | 驳回重写 |
| 1 官 `verdict="modify"` | 轻微问题 | Agent 自行修改后通过（参考 `required_changes`） |
| 所有官 `verdict="pass"` | 综合通过 | 发送 |
| 邀约窗口官 `window_detected=true` | 触发邀约流程 | 走 auto_reply_invite workflow |

**hard_block 触发条件**（仅 risk 官）：
- verdict="reject" 且 severity="high" → hard_block=true
- 命中禁忌话术 / 信息泄露 / avoid_topics → hard_block=true
- 其他情况 → hard_block=false

**3 次重试上限**：超过 3 次仍无法通过 → 记录失败原因，本次跳过，等下次对方发消息（v4 7.7 节）。

### 步骤 4（可选）：邀约窗口触发

如果邀约窗口官检测到窗口（window_detected=true），主 agent 应：
1. 先完成当前回复发送（不因窗口检测而中断当前回复）
2. 发送后，走 `auto_reply_invite` workflow

## 模板填充说明

每个 prompt 模板包含 `{{占位符}}`，主 agent 调用前需替换为实际值：

| 占位符 | 来源 | 示例 |
|--------|------|------|
| `{{reply_draft}}` | 主 agent 生成 | "哈哈，我也是这么想的" |
| `{{contact_name}}` | 联系人参数 | "alice" |
| `{{relationship_stage}}` | person_brief | "stage_2" |
| `{{user_profile_fact}}` | 读取 data/user_profile_fact.yaml | YAML 内容 |
| `{{user_fabricated_facts}}` | 读取 data/user_fabricated_facts.yaml | YAML 内容 |
| `{{user_facts_topics}}` | 读取 data/user_facts_topics_profile.yaml | YAML 内容 |
| `{{recent_summary}}` | conversation_thread.recent_summary | 最近对话摘要 |
| `{{her_emotion_trend}}` | conversation_thread.her_emotion.trajectory | "上升" / "平稳" / "下降" |
| `{{pending_items}}` | conversation_thread.pending_items | 待办事项列表 |
| `{{wiki_methodology}}` | wiki_context.prompt_section | Wiki 方法论文本 |
| `{{wiki_taboos}}` | wiki_context focus=risk | Wiki 禁忌文本 |
| `{{avoid_topics}}` | conversation_thread.avoid_topics | 短期禁忌列表 |
| `{{landmine_topics}}` | conversation_thread.landmine_topics | 雷区话题列表 |
| `{{conversation_threads}}` | conversation_thread.current_threads | 当前对话话题 |
| `{{ioi_signals}}` | person_signals | IOI 信号列表 |

## 性能考量

- **并行执行**：5 个 subagent 并行，总延迟 = max(5 个延迟) 而非 sum
- **Token 成本**：每条回复需 5 次 LLM 调用（subagent）+ 1 次（主 agent 生成草案）+ 1 次（主 agent 裁决）= 7 次
- **降级策略**：如果 Token 预算紧张，可只对高风险场景（Stage 3+ / 首次邀约 / 敏感话题）开 5 官，低风险场景只开 Risk 官

## 与 v4 文档的对应关系

| v4 章节 | 本目录对应 |
|---------|-----------|
| 7.1 五个审查角度的职责划分 | 5 个 prompt 文件 |
| 7.3 综合审核协议 | README 裁决规则 |
| 7.4 判决原则 | README 裁决规则 |
| 7.5 委员会确认偏差防护 | README 信息隔离矩阵 + risk.md 强制对抗性审查 |
| 7.6 委员会与对话线索的协作 | 各 prompt 文件的输入字段 |
| 7.7 失败退避策略 | README 3 次重试上限 |
