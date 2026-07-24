---
name: auto-reply-workflow
description: 自动回复完整流程 — 8步从监听到发送
---

# 自动回复完整流程（v4）

## 流程概览

```
0: 启动监听 → 1: 读取新消息 → 2: 读取对话线索 → 3: Wiki知识框架
  4: 跨联系人查重 → 5: 委员会审查 → 6: 发送回复（四重硬约束）→ 7: 更新线索
```

---

## 第0步：启动实时监听

**工具**：`live_monitor_start(name, poll_interval=10)` 【MCP工具】

**目的**：开始监听联系人消息（10 秒轮询）。

**执行细节**：
- 场景：用户希望 Agent 自动回复对方消息
- 启动后 Agent 持续监听，无需用户干预
- `auto_stop=600`（无读取 10 分钟自动停止）

---

## 第1步：增量读取新消息

**工具**：`live_chat_read(name, since_last_read=True)` 【MCP工具】

**目的**：读取实时缓存的消息，判断对方是否说完。

**执行细节**：
- 增量模式（since_last_read=True）只返回上次读取后的新消息
- 判断对方说完的依据：连续 N 秒无新消息（按关系阶段，Stage 1-2: 30s / Stage 3+: 10s）
- 深夜降频（23:00-02:00 30s/次, 02:00-06:00 2min/次）
- 紧急关键词（"睡不着"/"难过"/"想死"等）立即触发回复

---

## 第2步：读取/更新对话线索

**工具**：`conversation_thread(action='get', name)` 【MCP工具】

**目的**：获取对话线索（current_threads / her_emotion / key_context / landmine_topics / avoid_topics）。

**执行细节**：
- 线索是 wechat_send 发送的硬约束前提（未读取最新消息会拒绝发送）
- 线索过期时（按关系阶段阈值：Stage 1-2: 12h / Stage 3: 6h / Stage 4+: 3h）先调 `catch_up`
- 重点关注：her_emotion.trajectory（情绪趋势）、initiative_tracker（主动率）、landmine_topics（雷区）

---

## 第3步：构建 Wiki 知识框架

**工具**：`wiki_context(queries, task_type='reply', stage, focus='reply')` 【MCP工具】

**目的**：传入 stage + focus='reply' 获取回复方法论（推拉/冷读/共情等）。

**执行细节**：
- queries 从 conversation_thread 的 current_threads + key_context 提取
- stage 从 person_brief 的 relationship_stage 获取
- 返回 prompt_section 可直接嵌入 Agent 推理

---

## 第4步：跨联系人查重

**工具**：`recent_replies_check(action='check', reply_content, to)` 【MCP工具】

**目的**：检查是否对其他人发过相同话术（破坏拟人度）。

**执行细节**：
- Agent 生成回复草案后立即调用
- 完全相同话术 → 高危（必须换）
- 相同 pattern 不同措辞 → 中危（建议换）
- 不同 pattern → 通过
- 发送成功后调 `action='add'` 记录到池中

---

## 第5步：委员会审查（5 官 subagent 并行）

**工具**：`Task`（主 agent 开 5 个 subagent，并行执行）

**目的**：5 个独立 subagent 从不同角度审查回复草案，防止确认偏差（v4 7.5 节）。

**Prompt 模板**：`skill/committee/`（详见 `README.md`）

### 5 官职责（v4 7.1 节）

| 审查官 | prompt 文件 | 核心问题 | 硬否决权 |
|--------|------------|---------|---------|
| 拟人度 | `humanlike.md` | 像不像真人发的？ | 否 |
| 用户一致性 | `consistency.md` | 符合用户真实人设吗？ | 否 |
| 感情推进 | `progression.md` | 对推进感情有帮助吗？ | 否（策略主导） |
| 风险 | `risk.md` | 有风险吗？ | **是** |
| 邀约窗口 | `invite_window.md` | 当前是邀约窗口吗？ | 否（窗口报告） |

### 执行方式

主 agent 在**一条消息中**并行发起 5 个 Task 工具调用（subagent_type=`general_purpose_task`），每个 subagent 收到填充后的 prompt 模板（含 `{{占位符}}` 已替换为实际值）。

**信息隔离**：每个 subagent 只接收其角度所需的信息（信息隔离矩阵详见 `skill/committee/README.md`），不共享主 agent 上下文。

### 输出格式（固化 schema）

4 个审查官返回 JSON（verdict/hard_block/reasons/required_changes + 各官扩展字段），邀约窗口官返回窗口检测报告（window_detected/confidence/recommendation）。

### 综合审核协议（v4 7.3-7.4 节，基于固化 schema）

| 情况 | 裁决 | 动作 |
|------|------|------|
| 任一官 `hard_block=true` | **硬否决** | 驳回重写，不可覆盖（仅 risk 官可触发） |
| ≥2 官 `verdict="reject"` | 严重驳回 | 驳回重写 |
| 1 官 `verdict="modify"` | 轻微问题 | Agent 自行修改后通过（参考 `required_changes`） |
| 所有官 `verdict="pass"` | 综合通过 | 发送 |
| 邀约窗口官 `window_detected=true` | 触发邀约流程 | 发送当前回复后走 auto_reply_invite |

**3 次重试上限**：超过 3 次仍无法通过 → 记录失败原因，本次跳过，等下次对方发消息（v4 7.7 节）。

---

## 第6步：发送回复

**工具**：`wechat_send(name, message, urgent=False)` 【MCP工具】

**目的**：发送回复（v4 四重硬约束）。

**四重硬约束**（自动校验）：
1. **用户接管取消校验**：`conversation_thread.user_took_over == False`
   - 失败返回 `USER_TOOK_OVER`，需用户显式调 `conversation_thread(action='clear_cancel_flag')` 取消接管
2. **线索已读校验**：`last_processed_message_id >= 最新消息 ID`
   - 失败返回 `THREAD_NOT_CAUGHT_UP`，需先调 `conversation_thread(action='catch_up')`
3. **回复冷却校验**：按阶段最小冷却（Stage 1-2: 30min / Stage 3: 5min / Stage 4+: 3min）
   - 失败返回 `COOLDOWN_ACTIVE` 和 `wait_seconds`
   - `urgent=True` 可绕过（用于对方连续追问等紧急场景）
4. **互斥锁校验**：视觉自动化串行

---

## 第7步：更新对话线索

**工具**：`conversation_thread(action='update', name, update_fields, expected_version)` 【MCP工具】

**目的**：发送后更新线索（last_processed_message_id + recent_summary + her_emotion）。

**执行细节**：
- 使用乐观锁（expected_version）防止并发冲突
- 更新 recent_summary（追加本次对话摘要，最多保留 20 条）
- 更新 last_processed_message_id 为最新消息 ID
- 如果对方情绪有变化，更新 her_emotion.trajectory

---

## 相关流程

- **紧急回复**：用户主动触发的回复建议，走 `emergency_reply` workflow
- **自动邀约**：邀约窗口检测到后，走 `auto_reply_invite` workflow
- **紧急通知**：紧急事件推送，走 `auto_reply_notify` workflow

## 相关 Skill 文档

- `skill/workflows/emergency_reply.md`：紧急回复流程（用户手动触发）
- `skill/love-mentor.md`：基本流程
- `readme/auto_reply_architecture.md`：完整架构实现说明
