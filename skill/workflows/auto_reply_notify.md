---
name: auto-reply-notify-workflow
description: 紧急通知流程 — 5步从检测到推送
---

# 紧急通知流程（v4）

## 流程概览

```
0: 检测紧急 → 1: 读取线索 → 2: Wiki策略 → 3: 紧急发送 → 4: 通知用户
```

---

## 第0步：检测紧急事件

**工具**：`live_chat_read(name, since_last_read=True)` 【MCP工具】

**目的**：实时监听检测到紧急关键词或对方连续追问。

**执行细节**：
- 紧急关键词（示例，Agent 自主判断）：
  - 情绪类："睡不着" / "难过" / "想死" / "好累"
  - 关系类："我们不合适" / "算了吧" / "别联系了"
  - 追问类：对方连续 3 条消息未获回复
- Agent 自主判断紧急程度，不依赖固定规则
- 深夜时段（23:00-06:00）紧急关键词立即触发，不受降频限制

---

## 第1步：读取对话线索

**工具**：`conversation_thread(action='get', name)` 【MCP工具】

**目的**：获取当前对话上下文，判断紧急程度。

**执行细节**：
- 重点关注：her_emotion.trajectory（情绪趋势）、landmine_topics（是否触发雷区）
- 如果线索过期，先调 `conversation_thread(action='catch_up')` 补读
- Agent 基于线索 + 消息内容自主判断紧急级别

---

## 第2步：Wiki 紧急策略

**工具**：`wiki_context(queries, task_type='reply', stage, focus='risk')` 【MCP工具】

**目的**：获取紧急应对策略。

**执行细节**：
- queries 基于紧急类型：
  - 情绪类 → `['情绪安抚', '共情技巧']`
  - 关系危机类 → `['挽回', '重新吸引']`
  - 追问类 → `['频率法则', '需求感']`
- Agent 基于 Wiki 策略自主生成紧急回复

---

## 第3步：紧急发送

**工具**：`wechat_send(name, message, urgent=True)` 【MCP工具】

**目的**：紧急发送回复（绕过回复冷却校验）。

**执行细节**：
- `urgent=True` 绕过回复冷却校验（Stage 1-2: 30min / Stage 3: 5min / Stage 4+: 3min）
- **仍校验**线索已读（last_processed_message_id >= 最新消息 ID）
- **仍校验**互斥锁
- 发送后仍需调 `conversation_thread(action='update')` 更新线索
- 发送后调 `recent_replies_check(action='add')` 记录到查重池
- 发送后调 `effect_tracking(action='record')` 记录效果

---

## 第4步：通知用户

**工具**：`server_chan_notify(title, content, priority)` 或 AskUserQuestion

**目的**：通知用户发生了紧急事件。

**执行细节**：
- **Server酱推送**（用户不在电脑前）：
  - `server_chan_notify(title="紧急事件：[REDACTED] 情绪突变", content="...", priority=3)`
  - priority=3（Urgent）确保推送
  - content 包含：事件描述 + Agent 回复内容 + 后续建议
- **AskUserQuestion**（用户在电脑前）：
  - 展示紧急事件详情
  - 提供选项：继续自动回复 / 用户接管 / 暂停自动回复

---

## 紧急事件类型与处理

| 类型 | 检测方式 | 紧急级别 | 处理方式 |
|------|---------|---------|---------|
| 对方情绪低落 | 紧急关键词 | 高 | 立即回复 + 通知用户 |
| 关系危机信号 | "不合适"/"算了吧" | 高 | 立即回复 + 通知用户 |
| 对方连续追问 | 3 条未回复 | 中 | 立即回复 |
| 系统异常 | 工具报错 | 中 | 通知用户 + 暂停自动回复 |
| 委员会连续驳回 | 3 次驳回 | 低 | 通知用户接管 |

---

## 相关流程

- **自动回复**：日常消息回复，走 `auto_reply` workflow
- **自动邀约**：邀约窗口检测，走 `auto_reply_invite` workflow

## 相关 Skill 文档

- `skill/workflows/auto_reply.md`：自动回复流程
- `readme/auto_reply_architecture.md`：完整架构实现说明
