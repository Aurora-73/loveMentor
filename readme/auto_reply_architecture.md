# v4 自动回复架构（实现说明）

> **状态**：已实现（Phase 1 MVP + Phase 2 完善 完成，Phase 3 部分完成）
> **实现完成日期**：2026-07-23
> **关联**：[Wiki 知识库](../docs/wiki/index.md) | [MCP 服务器](mcp.md) | [微信自动化流程](wechat_auto_flow.md)

---

## 一、架构概述

v4 自动回复架构是 LoveMentor 的核心能力，让 Agent 能够自主管理微信对话、生成回复、审查质量、发送消息。

**核心原则**：Agent = LLM = 用户化身。所有语义理解由 Agent 完成，MCP 工具只做 LLM 做不了的事（CRUD/统计/系统操作/Wiki 检索）。

**架构组件**：

```
持续运行层（Agent 轮询）
    │
    ├─ 对话线索层（conversation_thread）← 短期上下文管理
    ├─ 数据层（person_chat/metrics/evidence）← 联系人数据
    ├─ 知识层（wiki_context）← 方法论主轴
    ├─ 用户画像层（user_profile_manage）← grounding + smoothing + bad_patterns
    │
    ├─ 委员会层（5 官 subagent 并行审查）← 草案质量把关
    │   ├─ 拟人度审查官
    │   ├─ 用户一致性审查官
    │   ├─ 感情推进审查官
    │   ├─ 风险审查官（硬否决权）
    │   └─ 邀约窗口审查官
    │
    ├─ 执行层（wechat_send 系列）← 四重硬约束
    ├─ 邀约层（date_briefing + date_feedback_loop）
    └─ 归档层（save_from_markdown + person_note）
```

---

## 二、工具清单

### v4 新增 MCP 工具（11 个）

| 工具 | 文件 | 功能 |
|------|------|------|
| `conversation_thread` | `mcp_server/tools_thread.py` | 对话线索管理（10 个 action：get/update/append_summary/clear/check_expired/clear_cancel_flag 等）|
| `schedule_manage` | `mcp_server/tools_schedule.py` | 日程管理（7 个 action：query/add/update/remove/list_slots/update_preferences/add_note）|
| `user_profile_manage` | `mcp_server/tools_profile.py` | 用户画像管理（3 类文件：user_profile_fact / user_style_profile / user_bad_patterns）|
| `date_briefing` | `mcp_server/tools_date.py` | 约会前简报生成 |
| `date_feedback_loop` | `mcp_server/tools_date.py` | 约会后反馈闭环 |
| `recent_replies_check` | `mcp_server/tools_replies.py` | 最近回复检查 |
| `effect_tracking` | `mcp_server/tools_replies.py` | 发送效果追踪 |
| `server_chan_notify` | `mcp_server/tools_notify.py` | Server酱推送通知 |
| `override_learning` | `mcp_server/tools_override.py` | 手动覆盖学习 |
| `contact_priority_manage` | `mcp_server/tools_priority.py` | 联系人优先级管理 |
| `reply_state_manage` | `mcp_server/tools_reply_state.py` | 回复状态管理（6 个 action：record/update/check_retry/check_suspended/clear_suspended/stats）|

### 微信发送工具（5 个）

| 工具 | 功能 | 输入方式 |
|------|------|----------|
| `wechat_send` | 文本发送（自动切分标点+emoji）| IME_CHAR 逐字输入 |
| `wechat_send_emoji` | 表情包发送 | 表情面板搜索+点击 |
| `wechat_send_image` | 图片发送 | CF_DIB 剪贴板粘贴 |
| `wechat_send_file` | 视频/文件发送 | CF_HDROP 剪贴板粘贴 |
| `wechat_send_batch` | 批量混合发送 | 支持 text/emoji/image/video/file 混合 |

---

## 三、四重硬约束

发送消息前依次校验，任一失败即阻止发送：

| 优先级 | 硬约束 | 检查内容 | 失败处理 |
|--------|--------|----------|----------|
| 0 | **用户接管取消** | `conversation_thread` 的 `user_took_over` 标记 | 返回 `USER_TOOK_OVER` 错误，不发送 |
| 1 | **线索已读** | `conversation_thread` 是否已读取最新对话 | 返回 `THREAD_NOT_READ` 错误，提示先读线索 |
| 2 | **回复冷却** | `reply_state_manage` 检查是否在冷却期 | 返回 `COOLDOWN_ACTIVE` 错误，等待冷却结束 |
| 3 | **互斥锁** | `CrossProcessLock("loveMentor_wechat_op")` 跨进程锁 | 等待锁释放后执行 |

**实现位置**：
- 硬约束 0：`mcp_server/tools_wechat.py` L121 `_check_user_took_over`（4 个发送工具都有）
- 硬约束 1-2：`mcp_server/tools_wechat.py` 发送前校验
- 硬约束 3：`engine/wechat_sender/cross_process_lock.py`（Win32 Named Mutex，支持 WAIT_ABANDONED 崩溃恢复）

---

## 四、委员会审查机制

### 5 官并行 subagent 架构

主 Agent 在一条消息中并行发起 5 个 Task 工具调用（`general_purpose_task` 类型），每个审查官只接收其角度所需的信息（信息隔离矩阵）。

| 审查官 | 职责 | 输入信息 | 硬否决权 |
|--------|------|----------|----------|
| **拟人度** | 5 维度：句长/用词/emoji/AI痕迹/风格一致性 | 草案 + user_style_profile | 否 |
| **用户一致性** | 5 项：编造经历/身份冲突/人设突变/阶段突兀/坏习惯 | 草案 + user_profile_fact + user_bad_patterns + recent_summary | 否 |
| **感情推进** | 4 维度：错失窗口/需求感/阶段节奏/pending_items | 草案 + Wiki + 阶段 + 情绪 + pending_items | 否 |
| **风险** | 7 类风险 + 强制对抗性审查（至少 2 个风险点）| 草案 + 禁忌列表 + avoid_list + landmine_topics | **是**（severity=high 时硬否决）|
| **邀约窗口** | 4 类窗口：IOI集群/服从性/暗示/阶段转换 | 对话线索 + IOI 信号 + 阶段（不审查草案）| N/A（只检测窗口）|

### 综合裁决规则

```
Risk 官 severity="high" → 硬否决，驳回重写
≥2 官 reject → 驳回重写
1 官 modify → 自行修改后通过
全 pass → 发送
```

### 实现文件

`skill/committee/` 目录（6 个文件）：
- `README.md` — 设计说明 + 信息隔离矩阵 + 编排示例 + 裁决规则
- `humanlike.md` — 拟人度审查官 prompt
- `consistency.md` — 用户一致性审查官 prompt
- `progression.md` — 感情推进审查官 prompt
- `risk.md` — 风险审查官 prompt
- `invite_window.md` — 邀约窗口审查官 prompt

---

## 五、回复状态机

`reply_state_manage` 工具管理 Agent 行为层的状态机，与 `conversation_thread`（线索层）解耦。

### 6 个 action

| action | 功能 |
|--------|------|
| `record` | 记录一次发送尝试（消息 ID、联系人、失败类型）|
| `update` | 更新发送状态（成功/失败/重试中/放弃）|
| `check_retry` | 检查是否可以重试（重试次数上限 + 冷却期）|
| `check_suspended` | 检查是否被暂停（连续失败保护）|
| `clear_suspended` | 清除暂停状态（用户手动恢复）|
| `stats` | 统计信息（成功率/失败类型分布/暂停次数）|

### 5 种失败类型 + 重试上限

| 失败类型 | 重试上限 | 退避策略 |
|----------|----------|----------|
| 网络超时 | 3 次 | 指数退避（30s → 60s → 120s）|
| OCR 验证失败 | 2 次 | 固定间隔 60s |
| 窗口未找到 | 2 次 | 固定间隔 30s |
| 发送按钮未找到 | 2 次 | 固定间隔 30s |
| 未知错误 | 1 次 | 不重试，标记 abandoned |

### 连续失败保护

- 24 小时内连续失败 ≥3 次 → 自动暂停
- 暂停后需要用户手动 `clear_suspended` 恢复
- 重试上限后自动标记 `abandoned`（区分"暂停"和"放弃"）

**数据存储**：`data/system/reply_states.yaml`

---

## 六、消息切分与发送

### 自动切分（`split_message_for_wechat`）

发送前自动删除所有标点和 emoji，并按这些位置切分为多条短消息：

- 标点：中英文标点、换行、省略号、引号、括号
- emoji：Unicode emoji 范围，位置作为切段点
- 多段 → `send_message_batch` 连续发送
- 单段 → `send_message_with_retry` 单条发送
- 兜底：纯标点/emoji/空白 → 返回 `[""]`（不发送含标点的原文）

**实现位置**：`mcp_server/tools_wechat.py` `split_message_for_wechat` 函数

### IME_CHAR 逐字输入

中文消息用 `PostMessageW` 发送 `WM_IME_CHAR` 消息（绕过剪贴板），模拟 IME 输入法逐字输入：

- 随机间隔 0.08-0.25s（模拟候选词选择）
- ASCII 字符用 `SendInput` + `KEYEVENTF_UNICODE` 逐字输入
- 配置：`human_sim.py` L131 `USE_IME_CHAR_FOR_CHINESE = True`

**实现位置**：`engine/wechat_sender/human_sim.py` `_type_ime_char` + `_type_short_message`

---

## 七、用户画像三层架构

| 文件 | 定位 | 优先级 | 内容 |
|------|------|--------|------|
| `data/user_profile_fact.yaml` | grounding（事实锚定）| 高 | 用户真实信息（职业/爱好/经历等），防止 Agent 编造 |
| `data/user_style_profile.yaml` | smoothing（风格平滑）| 低 | 跨会话统计风格（句长/用词/emoji 习惯），批处理生成 |
| `data/user_bad_patterns.yaml` | 避免模仿 | 高 | 坏习惯模式（太讨好/太解释/太秒回等），标记已纠正 |

**策略优先级**：Wiki > 上下文 > 事实 > 阶段 > 风格

**联系人特化层**：`data/user_style_overrides/` 目录，每个联系人独立风格覆盖

---

## 八、实现状态

### Phase 1 (MVP) — ✅ 完成

- conversation_thread（对话线索管理）
- schedule_manage（日程管理）
- user_profile_manage（用户画像管理）
- date_briefing（约会简报）
- recent_replies_check（最近回复检查）
- server_chan_notify（Server酱推送）
- wechat_send 三重硬约束

### Phase 2 (完善) — ✅ 完成

- override_learning（手动覆盖学习）
- contact_priority_manage（联系人优先级）
- date_feedback_loop（约会反馈闭环）
- effect_tracking（效果追踪）
- 图片发送能力（wechat_send_image）
- 静默断联处理（Agent 行为，非工具）

### Phase 3 (扩展) — 部分完成

**已完成**：
- ✅ 委员会 5 官 subagent 并行审查
- ✅ 四重硬约束（新增 user_took_over）
- ✅ reply_state_manage 状态机
- ✅ 消息自动切分 + IME_CHAR 逐字输入
- ✅ 视频/文件发送（wechat_send_file）
- ✅ 批量混合发送（wechat_send_batch）
- ✅ 跨进程互斥锁（Win32 Named Mutex）

**待实现**（需外部依赖或用户决策）：
- ⏳ 委员会标准自优化（需长时间运行数据）
- ⏳ 系统日历集成（需要 Outlook/Google Calendar API）

---

## 九、质量审查修复记录

v4 实现后进行了质量审查，发现并修复了 8 项工程不变量差异问题：

| 问题 | 优先级 | 状态 | 实现位置 |
|------|--------|------|---------|
| 1. user_took_over 缺 timestamp | 低 | ✅ 已修复 | `tools_thread.py` L78 `user_took_over_time` + L281-284 同步记录 |
| 2. 版本冲突处理不完整 | 中 | ✅ 已修复 | `tools_thread.py` L211-254 `_action_update` 3 次重试 + `_log_thread_conflict` |
| 3. 字段级合并规则不完整 | 中 | ✅ 已修复 | `tools_thread.py` L310-374 `_merge_fields`（her_emotion/initiative_tracker/pending_items）|
| 4. cancel_flag 机制未实现 | **高** | ✅ 已修复 | `tools_wechat.py` L121 `_check_user_took_over`（4 个发送工具都有）|
| 5. 发送失败重试状态机 | 中 | ✅ 已修复 | `tools_reply_state.py`（新建，`reply_state_manage` 工具 + RETRY_LIMITS 表）|
| 6. 失败退避策略 | 中 | ✅ 已修复 | `tools_reply_state.py` 连续失败保护（24h 内 ≥3 次暂停）|
| 7. abandoned 标记 | 中 | ✅ 已修复 | `tools_reply_state.py` L228-231 重试上限后标记 abandoned |
| 8. processed_message_ids 清理注释 | 低 | ✅ 已修复 | `tools_thread.py` L130-132 注释说明工程近似 |

---

## 十、端到端测试验证

### 委员会审查 + 发送完整链路测试

**测试场景**：
- 联系人：[REDACTED]（茶）
- 对方消息："在吗？周末有空吗？"
- 关系阶段：stage_2

**第 1 轮审查**（5 官并行）：
- 拟人度：pass
- 用户一致性：pass
- 感情推进：modify（需求感略过+替对方挑明邀约）
- 风险：**reject + high**（需求感过强 stage_2 高风险 + 阶段错位 + 禁忌边界）
- 邀约窗口：window_detected=true, confidence=0.85
- **综合裁决**：驳回重写（风险官硬否决）

**修改后草案**："周末没特别安排呀，怎么了？"
- "没特别安排"替代"有空"（降低可得性）
- "怎么了？"替代"是不是想约我出去玩"（不替对方挑明）

**第 2 轮审查**：风险官 pass + 感情推进官 pass → **通过**

**发送结果**：
- 自动切分："周末没特别安排呀，怎么了？" → ["周末没特别安排呀", "怎么了"]
- 第 1 条：8 字 IME_CHAR 逐字输入，OCR conf=0.883 ✅
- 第 2 条：3 字 IME_CHAR 逐字输入，OCR conf=0.534 ✅
- 总耗时：21.4s，四重硬约束全部通过

---

## 十一、相关文档

- [MCP 服务器](mcp.md) — 工具清单和配置方法
- [微信自动化流程](wechat_auto_flow.md) — 端到端发送流程图
- [微信 OCR 增强](wechat_ocr_enhancement.md) — UI 元素识别方案
- [Skill 委员会设计](../skill/committee/README.md) — 5 审查官 prompt 设计
- [Skill 自动回复工作流](../skill/workflows/auto_reply.md) — 12 步自动回复流程
