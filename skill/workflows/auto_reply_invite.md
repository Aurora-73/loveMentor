---
name: auto-reply-invite-workflow
description: 自动邀约流程 — 7步从窗口检测到简报生成
---

# 自动邀约流程（v4）

## 流程概览

```
0: 窗口检测 → 1: 查询日程 → 2: 生成方案 → 3: 用户确认
  4: 约会简报 → 5: 填充简报 → 6: 记录日程
```

---

## 第0步：检测邀约窗口

**工具**：`person_brief(name)` 【MCP工具】

**目的**：从 brief 获取 relationship_stage + signals，结合 Wiki 判断是否进入邀约窗口。

**执行细节**：
- 邀约窗口判断依据：关系阶段（Stage 2+ 可模糊邀约，Stage 3+ 可确定邀约）+ 信号（IOI/邀约窗口）
- Agent 自主判断是否进入邀约流程，不依赖专门的窗口检测工具
- 参考Wiki：`wiki_context(queries=['邀约窗口', 'IOI'], focus='strategy')`

---

## 第1步：查询用户日程

**工具**：`schedule_manage(action='list_slots', date)` 【MCP工具】

**目的**：查询用户可用时段，避免邀约时间冲突。

**执行细节**：
- Agent 先调 `schedule_manage(action='query')` 查看已安排事件
- 再调 `schedule_manage(action='list_slots')` 查询空档
- Agent 基于用户偏好（preferred_date_duration / preferred_date_types）筛选合适时段
- 如果用户未设置偏好，Agent 通过 AskUserQuestion 询问

---

## 第2步：生成邀约方案

**工具**：`wiki_context(queries, task_type='meet', stage, focus='strategy')` 【MCP工具】

**目的**：获取邀约三步法方法论，Agent 自主生成邀约方案。

**执行细节**：
- 邀约三阶递进（v4 决策#16）：
  1. **埋线**：日常聊天中埋下邀约线索（如"最近发现一家不错的店"）
  2. **模糊邀约**：不指定具体时间（如"周末有空一起喝咖啡"）— 可自动发送
  3. **确定邀约**：指定具体时间地点（如"周六下午3点在XX咖啡"）— 必须用户确认
- Agent 基于 Wiki + 日程 + 对话线索自主生成邀约话术
- 邀约话术需通过 `recent_replies_check(action='check')` 查重

---

## 第3步：用户确认

**工具**：无（使用 AskUserQuestion）

**目的**：确定邀约必须用户确认（涉及用户日程）。

**执行细节**：
- Agent 通过 AskUserQuestion 向用户展示邀约方案
- 确认内容：时间、地点、活动类型、邀约话术
- 用户可修改任一项，Agent 重新生成
- 用户确认后进入简报生成

---

## 第4步：生成约会前简报

**工具**：`date_briefing(name, date_plan)` 【MCP工具】

**目的**：生成 5 段式约会前简报模板。

**执行细节**：
- date_plan 包含：date / time_range / location / activity
- 返回 briefing_markdown（5 段式模板）+ data_sources + wiki_queries
- 模板中分析性段落标记为 `[Agent 基于 Wiki 填充]`

---

## 第5步：填充简报内容

**工具**：`wiki_context(queries=wiki_queries, task_type='meet', stage, focus='date')` 【MCP工具】

**目的**：获取约会方法论，填充简报中分析性段落。

**执行细节**：
- queries 来自 date_briefing 返回的 wiki_queries
- Agent 基于 wiki_context 返回的 prompt_section 填充：
  - 第二段（注意事项）：Wiki 约会方法论
  - 第三段（可讨论话题）：各阶段聊天话题库
  - 第五段（约会后计划）：第一次约会回来之后的黄金窗口

---

## 第6步：记录日程

**工具**：`schedule_manage(action='add', ...)` 【MCP工具】

**目的**：将确定的约会记录到用户日程。

**执行细节**：
- 事件 ID 格式：`evt_{timestamp}_{person}`
- 记录内容：date / time_range / location / activity / person
- 约会当天 Agent 应主动提醒用户（基于 schedule_manage 查询）

---

## 约会后反馈

约会结束后（日程时间到点 +1 小时 / 用户手动告知），走 `date_feedback_loop`：

1. `date_feedback_loop(name, date_event_id)` → 生成待分析项
2. Agent 基于 pending_items 调 AskUserQuestion 询问用户
3. 根据用户回答更新数据：
   - `events_save`：记录关键事件
   - `person_note`：记录观察要点
   - `conversation_thread`：更新 key_context + her_emotion
4. `date_feedback_mark_analyzed(record_id)` → 标记已分析

---

## 相关流程

- **自动回复**：日常消息回复，走 `auto_reply` workflow
- **紧急通知**：紧急事件推送，走 `auto_reply_notify` workflow

## 相关 Skill 文档

- `skill/workflows/auto_reply.md`：自动回复流程
- `readme/auto_reply_architecture.md`：完整架构实现说明
