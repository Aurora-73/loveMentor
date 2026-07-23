# LoveMentor MCP 服务器

> **状态**：已完工 — 全量验收通过，Claude Desktop / Claude Code 实测可用
> **最后更新**：2026-07-24（补全素材搜索工具、更新目录结构、新增 v4 工作流）

---

## 一、概述

MCP（Model Context Protocol）服务器将 `engine/tools.py` 的函数通过标准协议暴露给 AI 代理（Claude Desktop、Cursor、Windsurf 等），让 AI 可以直接读取和操作恋爱数据。

```
Claude Desktop / Cursor / Windsurf
            │
            │  (MCP stdio protocol)
            ▼
    ┌───────────────┐
    │  MCP Server   │  ← mcp_server/
    │  (FastMCP)    │
    └───────┬───────┘
            │  Python 函数调用
            ▼
    ┌───────────────┐
    │ engine/tools.py│
    └───────┬───────┘
            ▼
    engine/analyzers/ + engine/agent/ + engine/knowledge/
```

**设计原则**：MCP 是一层薄包装，不重复实现业务逻辑，直接调用 `engine/tools.py` 中的函数。

### 与 BottleCRM MCP 的区别

| 对比维度 | BottleCRM MCP | LoveMentor MCP |
|---------|---------------|----------------|
| 架构 | 远端 REST client（httpx 调用后端 API） | 本地函数暴露（直接调用 Python 函数） |
| 认证 | PAT + RLS + RBAC | 不需要（本地个人工具） |
| 安全模型 | 企业级（跨租户隔离） | 简单（只有本人） |
| 工具数量 | 通用 CRUD 工具 | 业务工具（含 v4 自动回复工具集） |
| 复杂度 | 高 | 低 |

---

## 二、技术选型

### 框架

| 选项 | 说明 |
|------|------|
| **FastMCP**（3.x） | 官方 Python MCP SDK，使用 `mcp.tool(name=..., description=...)(fn)` 模式注册工具 |

### 传输

| 阶段 | 传输方式 | 说明 |
|------|---------|------|
| 当前 | **stdio** | 本地运行，配置简单，通过 JSON-RPC over stdin/stdout 通信 |

### 依赖

```
fastmcp>=2.0      # MCP 服务器框架
pydantic>=2.7     # 数据验证（fastmcp 依赖）
```

---

## 三、目录结构

```
mcp_server/                  # MCP 服务器
├── __init__.py
├── server.py                # FastMCP 服务器入口，注册所有工具
├── config.py                # 服务器配置
├── tools_read.py            # 只读工具（brief/chat/metrics/rank/wiki 等）
├── tools_write.py           # 写入工具（note/date/evaluate/save_analysis 等）
├── tools_formula.py         # 公式计算工具（辅助参考视角）
├── tools_guide.py           # 使用指南工具（11 个主题）
├── tools_workflow.py        # 工作流导航（skill_map/workflow_step）
├── tools_config.py          # 配置工具（get_backend/set_backend）
├── tools_thread.py          # 对话线索工具（conversation_thread）
├── tools_reply_state.py     # 回复状态机（reply_state_manage）
├── tools_wechat.py          # 微信发送与控制（send/emoji/image/file/batch/verify/ocr）
├── tools_live.py            # 实时监控（live_monitor_start/stop/status/read）
├── tools_profile.py         # 用户画像管理（user_profile_manage）
├── tools_schedule.py        # 日程管理（schedule_manage）
├── tools_date.py            # 约会工具（date_briefing/date_feedback_loop）
├── tools_replies.py         # 回复检查（recent_replies_check/effect_tracking）
├── tools_notify.py          # 通知工具（server_chan_notify/config）
├── tools_override.py        # 手动覆盖学习（override_learning）
├── tools_priority.py        # 联系人优先级（contact_priority_manage）
├── tools_pictures.py        # 图片素材搜索（search_user_pictures）
├── tools_canned.py          # 罐装素材搜索（search_canned_materials）
├── tools_avatar.py          # 头像工具（person_avatar）
├── weflow_cdp.py            # WeFlow CDP 集成
├── README.md                # 使用说明
├── user_feedback.md         # 实战测试反馈
├── ISSUES.md                # 实施过程中的问题记录
├── TOOL_MAPPING.md          # 工具映射表
└── tests/                   # 测试
    └── ...
```

---

## 四、配置与启动

### Claude Desktop 配置

```json
{
  "mcpServers": {
    "lovementor": {
      "command": "python",
      "args": ["-m", "mcp_server.server"],
      "cwd": "E:/Code/loveMentor",
      "env": {
        "PYTHONIOENCODING": "utf-8"
      }
    }
  }
}
```

### 启动验证

```bash
python -X utf8 -m mcp_server.server
```

服务器在 stdio 上监听 JSON-RPC 请求，无 HTTP 端口。

---

## 五、工具清单

> **工具优先级**：Wiki 工具（`wiki_search`/`wiki_read`/`wiki_context`）是 Agent 推理的第一依据，方法论主轴；数据工具提供事实；公式工具仅作辅助参考视角。
> **使用指南**：`guide` 工具提供 11 个主题的操作指南（分析流程/报告模板/方法论/权限规范等），Agent 不确定操作流程时调用。
> **v4 自动回复工具**：详见 [auto_reply_architecture.md](auto_reply_architecture.md)。

### 5.1 Phase 1 — 核心工具

| 工具名 | 参数 | 说明 | 类型 |
|--------|------|------|------|
| `wiki_search` | `query, limit` | **搜索 Wiki 知识库（Agent 推理的第一依据，方法论主轴）** | 只读 |
| `person_brief` | `name` | 人物简要信息（身份、指标、事件、信号、最近消息） | 只读 |
| `person_chat` | `name, recent, from_date, to_date, keyword, context_lines` | 聊天记录（按日期分组，标注"我"/"对方"） | 只读 |
| `person_metrics` | `name` | 详细关系指标（回复率、回复速度、情绪评分等） | 只读 |
| `person_rank` | — | 所有人的关系热度排名 | 只读 |
| `person_status` | `name` | 当前状态快照（精简版指标） | 只读 |
| `person_note` | `name, content` | 添加人物备注到事实档案 | 写入 |
| `person_date_record` | `name, date_text, location, rating` | 记录约会信息 | 写入 |

### 5.2 Phase 2 P0 — 即时补齐

| 工具名 | 说明 | 类型 |
|--------|------|------|
| `wiki_read` | **读取 Wiki 页面完整正文（用于精确引用）** | 只读 |
| `wiki_context` | **批量 Wiki 上下文检索（合并 wiki_search+wiki_read，分析工作流第二步核心工具）。接受最多 5 条查询，返回格式化知识框架** | 只读 |
| `person_sync` | 增量同步单个人最新消息（几秒完成）。支持 `transcribe_mode` 参数：`async`（默认，后台异步转写语音/图片）、`sync`（同步等待转写完成）、`off`（不转写） | 写入 |
| `person_save_analysis` | 保存分析结论，旧版本自动转为 previous | 写入 |

### 5.3 Phase 2 P1 — 已实现工具

**只读：**
`person_timeline`、`person_signals`、`person_evidence`、`person_stage`、`person_compare`、`weekly_report`、`person_moments_stats`、`maintain_list`、`events_scan`（只读检测）、`wcd_status`（WCD 后端状态检测）、`weflow_status`（WeFlow 后端状态检测）、`person_behaviors`（语义行为标签查询）、`person_behaviors_data`（语义行为原始数据）

**写入：**
`events_save`（检测写入）、`person_evaluate`（追加写入）、`system_sync`（全量/增量同步）、`wcd_start`（启动 WCD 后端进程）、`weflow_start`（启动 WeFlow 后端进程）

### 5.4 Phase 2 P2 — 拆分工具

**只读：** `contact_search`、`sticker_scan`、`sticker_list`、`exclude_list`、`failure_list`、`message_context`

**写入：** `contact_alias`、`contact_alias_remove`、`contact_merge`（不可逆，带 confirm）、`sticker_label`、`exclude_add`、`exclude_remove`、`failure_add`、`save_from_markdown`、`sync_moments`

### 5.5 Phase 3 P3 — 公式工具（辅助参考视角）

> 公式是 chat-skills 遗产的独立体系，通过标注 Wiki 依据做软关联。**Agent 核验而非套用**——读公式结果 → 结合 Wiki 知识核验 → 自己做判断。阈值是参考，不是硬规则。

| 工具名 | 说明 |
|--------|------|
| `formula_get_params` | 参考计算参数（辅助视角，从数据库自动计算战态参数） |
| `formula_calc_ivi` | 参考计算 IVI（辅助视角，意图真实度） |
| `formula_calc_spe` | 参考计算 SPE（辅助视角，社交势能） |
| `formula_calc_ews` | 参考计算 EWS（辅助视角，升温窗口期） |
| `formula_calc_is` | 参考计算 IS（辅助视角，真实亲密度） |
| `formula_calc_gap_effect` | 参考计算 Gap_Effect（辅助视角，情绪落差刺激） |
| `formula_calc_eev` | 参考计算 EEV（辅助视角，升温期望值） |
| `formula_calc_cs` | 参考计算 CS（辅助视角，矛盾演化状态） |
| `formula_calc_action` | 参考决策（辅助视角，进攻/拉扯/重置/维持） |

### 5.6 使用指南工具

| 工具名 | 参数 | 说明 | 类型 |
|--------|------|------|------|
| `guide` | `topic` | 获取使用指南和工作流文档。11 个主题：getting-started / workflow/analysis / report-template / methodology / rules/evidence / rules/permissions / rules/reply / workflow/maintain / reference/sync / reference/formula / reference/stickers。支持中文别名 | 只读 |

### 5.7 配置与导航工具

| 工具名 | 参数 | 说明 | 类型 |
|--------|------|------|------|
| `get_backend` | — | 查看当前数据后端配置（wcd/weflow） | 只读 |
| `set_backend` | `backend, base_url, token` | 切换数据后端（wcd 或 weflow），写入 config.yaml 后即时生效 | 写入 |
| `skill_map` | `tool_name` | 查询工具与 Skill 的双向映射，返回下一步建议（详见 §10.2） | 只读 |
| `workflow_step` | `workflow, step` | 按步骤执行工作流，返回当前步骤详情和下一步指引（详见 §10.2） | 只读 |

### 5.8 永不暴露

| 函数 | 原因 |
|------|------|
| `fetch_keys` | 会重启微信并要求扫码，AI 无法完成 |

### 5.9 v4 自动回复工具

> 详见 [auto_reply_architecture.md](auto_reply_architecture.md)。

**对话与状态管理：**
`conversation_thread`（对话线索 10 action）、`reply_state_manage`（回复状态机 6 action）、`recent_replies_check`（最近回复检查）、`effect_tracking`（发送效果追踪）

**用户画像与日程：**
`user_profile_manage`（用户画像 3 类文件）、`schedule_manage`（日程 7 action）、`contact_priority_manage`（联系人优先级）

**约会闭环：**
`date_briefing`（约会前简报）、`date_feedback_loop`（约会后反馈）、`override_learning`（手动覆盖学习）

**通知：**
`server_chan_notify`（Server酱推送）、`server_chan_config`（Server酱配置）

### 5.10 微信发送与控制工具

**发送（四重硬约束 + 自动切分）：**
`wechat_send`（文本，IME_CHAR 逐字输入）、`wechat_send_emoji`（表情包）、`wechat_send_image`（图片）、`wechat_send_file`（视频/文件）、`wechat_send_batch`（批量混合）、`wechat_verify_send`（验证发送）

**控制：**
`wechat_status`（状态检查）、`wechat_start`（启动微信）、`wechat_stop`（停止微信）、`wechat_ocr`（OCR 识别）、`open_wechat_window`（打开/唤醒微信窗口）

> 详见 [wechat_auto_flow.md](wechat_auto_flow.md) 端到端流程图。

### 5.11 实时监控工具

| 工具名 | 说明 | 类型 |
|--------|------|------|
| `live_monitor_start` | 启动联系人实时监控（`poll_interval` 默认 10s，`fetch_limit` 可调，`include_brief=True` 预加载快照） | 写入 |
| `live_monitor_stop` | 停止监控 | 写入 |
| `live_monitor_status` | 查询监控状态 | 只读 |
| `live_chat_read` | 增量读取新消息（`since_last_read=True` 基于偏移量，避免全文件扫描） | 只读 |

### 5.12 头像工具

| 工具名 | 说明 | 类型 |
|--------|------|------|
| `person_avatar` | 获取联系人头像（5 级数据源优先级：本地缓存 → core.db → WCD/WeFlow API → contacts.json → CDP 强制刷新） | 只读 |

### 5.13 素材搜索工具

> 设计原则：工具只提供数据 + 模糊搜索，不替 Agent 做决策（不按 stage 过滤、不推荐"该用哪条素材"）。

| 工具名 | 参数 | 说明 | 类型 |
|--------|------|------|------|
| `search_user_pictures` | `keywords, category, limit` | 搜索用户图片库，返回匹配图片的描述和绝对路径。数据来源：`data/user_pictures/README.md` + 子文件夹 README + 目录扫描。支持单文件描述解析 | 只读 |
| `search_canned_materials` | `keywords, category, stage, limit` | 搜索罐装素材库（`data/canned_materials.yaml`），返回匹配素材的完整内容。按 stage 分类：脑筋急转弯/冷知识/冷笑话/电影台词/浪漫台词/身体语言等 | 只读 |

**图片素材库结构**：
- `data/user_pictures/README.md` — 主目录说明（分类概览 + 使用流程）
- `data/user_pictures/<分类>/README.md` — 子文件夹说明（描述 + 关键词 + 单文件描述）
- 子文件夹 README 末尾的"## 单文件描述"section 为每个文件提供具体描述

**罐装素材库结构**：
- `data/canned_materials.yaml` — 按 stage 分类（stage_1 破冰 / stage_2 熟悉 / stage_3 暧昧 / self_improvement 自我提升）
- `data/date_props.yaml` — 约会道具（看手相话术 + 无酒精互动游戏）

---

## 六、核心设计决策

### 6.1 返回格式：_data 变体优先

所有只读工具返回 Python dict（非 Markdown 字符串），AI 解析零歧义、token 更省。`engine/tools.py` 中新增 `brief_data`、`chat_data`、`rank_data`、`status_data`、`wiki_search_data` 等 dict 版本。

### 6.2 确认语义：三级操作

| 操作类型 | 确认需求 | 示例 |
|---------|---------|------|
| **只读** | 不需要确认 | brief、chat、rank、metrics |
| **追加写入** | 直接执行 | note、date、evaluate |
| **不可逆/覆盖** | confirm + 风险提示 | merge、save_analysis |

### 6.3 同步策略

三层数据新鲜度保障：

```
Layer 1: Windows 计划任务（每日全量）
Layer 2: WCD 常驻后台（开机自启）
Layer 3: MCP 按需增量（person_sync，秒级完成）
```

### 6.4 密钥安全

`fetch_keys` 永不暴露。`wcd_status` 仅做只读缓存状态查询。密钥通过 `account_keys.json` 持久化，WCD 启动时自动加载。

---

## 七、错误处理

所有工具统一错误格式：

```python
# 联系人不存在
{"error": "PERSON_NOT_FOUND", "message": "未找到联系人: xxx", "suggestion": "使用 person_rank() 查看所有联系人"}

# 工具执行失败
{"error": "TOOL_ERROR", "message": "xxx 执行失败: ...", "suggestion": "查看工具描述确认参数格式"}
```

---

## 八、实施过程与成果

### 关键里程碑

| 时间 | 事件 |
|------|------|
| 2026-07-01 Phase 1 | 核心工具注册，中文编码测试通过 |
| 2026-07-01 Phase 2 P0 | wiki_read / sync_person / save_analysis 补齐 |
| 2026-07-01 Phase 2 P1-P2 | 工具全部注册（timeline/events/contact/sticker 等） |
| 2026-07-01 Phase 3 | 公式工具暴露 |
| 2026-07-01 实战测试 | Claude Desktop 完成首次人物分析；Claude Code 全覆盖工具测试，发现 9 个问题 |
| 2026-07-01 反馈修复 | 9 个问题全部修复，测试文件全部 PASS |
| 2026-07-01 person_stage | 新增关系阶段自动识别工具 |
| 2026-07-02 guide 工具 | 新增使用指南工具，11 个主题 + 别名映射，解决信息差 |

### 实战测试发现并修复的 9 个问题

| # | 工具 | 问题 | 修复方式 |
|--|------|------|---------|
| P0 | `maintain_list` | AttributeError | 基于 reason 映射 priority/suggested_action |
| P1 | `wiki_search`→`wiki_read` | 路径不一致 | 修复 _search_wiki 路径拼接 |
| P2 | `contact_merge` | 同人合并+确认缺失 | 添加同人检查 + 正确解析返回值 |
| P3 | `person_chat` | 无上限保护 | CHAT_MAX_RECENT=500 硬上限 |
| P4 | `formula_calc_*` | 无参数校验 | _clamp_01 + param_warnings |
| P5 | `person_status`/`person_metrics` | 字段重叠 | status 精简为 9 字段，metrics 保留 11 字段 |
| P6 | `skill_search` | 0 结果 | 已移除工具，改用 wiki_search + .claude/skills/ |
| P7 | `person_evidence` | 不显示分析 | 添加 has_analysis + 提示文本 |
| P8 | `wcd_status` | 语义错误 | 改为 health + 密钥缓存检查 + suggestion |

### 验收结果

- 工具全部注册（含配置与导航工具、WeFlow 后端工具、v4 自动回复工具集）
- `fetch_keys` 安全隔离验证通过
- 主项目单元测试 + MCP 测试通过

---

## 九、经验沉淀

实施过程中积累的可复用经验存于 `exchange/MCP_lize/`：

| 分类 | 内容 |
|------|------|
| Lessons | stdio UTF-8 编码、FastMCP 工具注册、实战测试典型问题 |
| Snippets | 工具包装模板、错误处理、服务器入口、签名验证 |
| Tests | 中文编码测试、工具签名核对 |
| Issues | confirm 逻辑设计、dict vs Markdown 返回 |

---

## 十、Skill-MCP 融合架构

### 10.1 设计理念

本系统采用"**Skill 编排流程 + MCP 执行能力**"的融合架构，解决纯 MCP 缺乏业务流程指导、纯 Skill 缺乏标准化工具接口的问题。

| 层级 | 职责 | 实现 |
|------|------|------|
| **Skill 层** | 业务流程编排、决策规则定义、方法论框架 | `skill/` 下的 Markdown 文件 |
| **MCP 层** | 标准化数据接口、工具执行、安全隔离 | `mcp_server/` 下的 Python 工具 |
| **双向导航** | 工具与文档的双向索引、工作流指引 | `skill_map()` / `workflow_step()` |

### 10.2 核心工具

| 工具 | 功能 | 参数 |
|------|------|------|
| `skill_map(tool_name)` | 查询工具与 Skill 的双向映射，返回下一步建议 | `tool_name`: 工具名（可选，不传返回全部） |
| `workflow_step(workflow, step)` | 按步骤执行工作流，返回当前步骤详情和下一步指引 | `workflow`: 工作流名, `step`: 步骤编号（可选） |

### 10.3 工作流定义

| 工作流 | 名称 | 步骤数 | 适用场景 |
|--------|------|--------|----------|
| `analysis` | 人物分析完整流程 | 12 步 | "分析XX"、"帮我看看XX" |
| `emergency_reply` | 紧急回复流程 | 4 步 | "她发了XX怎么回" |
| `weekly` | 周报流程 | 2 步 | "做周报" |
| `maintain` | 维持关系流程 | 4 步 | "维持关系" |
| `auto_reply` | v4 自动回复流程 | 12 步 | 委员会审查 + 发送 |
| `auto_reply_invite` | 邀约自动回复流程 | 6 步 | 含邀约窗口检测 |
| `auto_reply_notify` | 紧急通知流程 | 2 步 | Server酱推送 |

### 10.4 分析工作流（analysis）详细步骤

> 已合并 `wiki_search`+`wiki_read` 为 `wiki_context` 单步（传入多条查询一次返回格式化知识框架），流程从 13 步精简为 12 步。

```
0:  person_sync         → 同步最新消息
1:  person_brief        → 获取全局视图（含 recommended_wiki_queries）
2:  wiki_context        → 构建 Wiki 知识框架（合并搜索+阅读，传入 brief 的 stage 和 recommended_wiki_queries）
3:  person_chat         → 获取聊天记录
4:  person_metrics      → 获取指标数据
5:  person_signals      → 获取信号详情
6:  person_stage        → 关系阶段识别
7:  person_timeline     → 获取关系时间线
8:  person_evidence     → 查阅事实档案
9:  formula_get_params  → 获取公式参数
10: formula_calc_ivi    → 公式核验（辅助参考）
11: save_from_markdown  → 保存分析报告
```

> `wiki_search`/`wiki_read` 仍保留为独立工具，用于钻取单个页面或精确引用；但作为工作流主路径已由 `wiki_context` 替代。

### 10.5 双向索引数据源

`skill/mcp_index.yaml` 是融合架构的核心数据源，包含：

- **tools**：工具映射（下一步建议、Skill 参考、工作流位置）
- **workflows**：4 个工作流的详细步骤定义
- **scenarios**：场景到工作流的路由映射

### 10.6 使用模式

**模式 1：按工作流执行（推荐）**

```python
workflow_step('analysis')        # 查看流程概览
workflow_step('analysis', 0)     # 获取第0步详情
person_sync('XX')                # 执行第0步
workflow_step('analysis', 1)     # 获取第1步详情
person_brief('XX')               # 执行第1步
# ...
```

**模式 2：工具驱动探索**

```python
skill_map('person_brief')        # 查 person_brief 之后能调什么
# 根据返回的下一步建议选择工具
```

**模式 3：场景路由**

```python
# 用户说"分析XX" → 路由到 analysis 工作流
# 用户说"她发了XX怎么回" → 路由到 emergency_reply 工作流
```

### 10.7 工具描述增强

所有核心工具的 description 中嵌入了下一步建议（与 `mcp_index.yaml` 的 `next_step` 一致）：

| 工具 | 下一步建议 |
|------|-----------|
| `person_sync` | 调 `person_brief` 获取全局视图（含 `recommended_wiki_queries`） |
| `person_brief` | 看到信号后立即调 `wiki_context` 构建知识框架 |
| `person_chat` | 看到聊天模式后调 `wiki_context` 查策略 |
| `person_metrics` | 看到数值后调 `wiki_context` 解读含义 |
| `wiki_context` | 构建框架后回到 `person_chat`/`person_metrics`/`person_signals` 深入分析 |
| `wiki_search` | 精确钻取单条目；建框架请用 `wiki_context` |
| `wiki_read` | 读单页全文用于精确引用；批量建框架请用 `wiki_context` |
| `formula_get_params` | 接下来代入 `formula_calc_ivi`/`spe`/`ews` 核验 |
