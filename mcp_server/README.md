# MCP Server

## 概述

`mcp_server/` 是 LoveMentor 的 **MCP（Model Context Protocol）服务器**，基于 FastMCP 框架，将 `engine/tools.py` 的 50 个工具通过 stdio 协议暴露给 AI 代理（Claude Desktop、Cursor 等）。MCP 是一层薄包装，不重复实现业务逻辑，直接调用 engine 层函数。

## 架构定位

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

## 安装

```bash
pip install -r requirements.txt
```

依赖：`fastmcp>=2.0`（实际验证版本 3.4.2）、`pydantic>=2.7`

## 运行

```bash
cd E:/Code/loveMentor
python -m mcp_server.server
```

服务器在 stdio 上监听 JSON-RPC 请求，无 HTTP 端口。

## 配置（Claude Desktop）

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

## 目录结构

```
mcp_server/
├── __init__.py
├── server.py              # FastMCP 服务器入口，注册所有 50 个工具
├── config.py              # 配置（复用 engine.config）
├── tools_config.py        # 工具配置
├── tools_read.py          # 只读工具（25 个，含 system_sync/wcd_status/events_scan）+ wcd_start
├── tools_write.py         # 写入工具（14 个）
├── tools_formula.py       # 公式计算工具（9 个，辅助参考视角）
├── tools_guide.py         # 使用指南工具（1 个，11 个主题）
├── tools_workflow.py      # 工作流导航工具（2 个：skill_map/workflow_step）
├── README.md              # 本文件
├── TOOL_MAPPING.md        # 工具映射表
├── ISSUES.md              # 问题记录
├── QUALITY_CHECK.md       # 质量自检报告
├── user_feedback.md       # 用户反馈
└── tests/
    ├── __init__.py
    ├── conftest.py        # 共享 fixture
    ├── test_encoding.py   # 中文编码测试
    ├── test_smoke.py      # 冒烟测试
    ├── test_p0.py         # P0 工具测试
    ├── test_bugfix.py     # Bug 修复验证
    └── test_final.py      # 全量验收测试（50 工具验证）
```

## 工具清单（50 个）

### 核心工具（8 个）

| 工具名 | 参数 | 说明 | 类型 |
|--------|------|------|------|
| `person_brief` | `name` | 人物简要信息（身份、指标、事件、信号、最近消息） | 只读 |
| `person_chat` | `name, recent, from_date, to_date, keyword, context_lines` | 聊天记录（按日期分组，标注"我"/"对方"） | 只读 |
| `person_metrics` | `name` | 详细关系指标（回复率、回复速度、情绪评分等） | 只读 |
| `person_rank` | 无 | 所有人的关系热度排名 | 只读 |
| `person_status` | `name` | 当前状态快照（精简版指标） | 只读 |
| `wiki_search` | `query, limit` | 搜索 Wiki 知识库（Agent 推理的第一依据） | 只读 |
| `person_note` | `name, content` | 添加人物备注到事实档案 | 写入 |
| `person_date_record` | `name, date_text, location, rating` | 记录约会信息 | 写入 |

### 即时补齐（3 个）

| 工具名 | 说明 | 类型 |
|--------|------|------|
| `wiki_read` | 读取 Wiki 页面完整正文 | 只读 |
| `person_sync` | 增量同步单个人最新消息（几秒完成） | 写入 |
| `person_save_analysis` | 保存分析结论，旧版本自动转为 previous | 写入 |

### 已实现工具（14 个）

**只读（8 个）：**
`person_timeline`、`person_signals`、`person_evidence`、`person_stage`、`person_compare`、`weekly_report`、`person_moments_stats`、`maintain_list`

**写入（6 个）：**
`events_scan`（只读检测）、`events_save`（检测写入）、`person_evaluate`（追加写入）、`system_sync`（全量/增量同步）、`wcd_status`（只读状态检测）、`wcd_start`（启动 WCD 后端进程）

### 拆分工具（15 个）

**只读：** `contact_search`、`sticker_scan`、`sticker_list`、`exclude_list`、`failure_list`、`message_context`

**写入：** `contact_alias`、`contact_alias_remove`、`contact_merge`（不可逆，带 confirm）、`sticker_label`、`exclude_add`、`exclude_remove`、`failure_add`、`save_from_markdown`、`sync_moments`

### 公式工具（9 个，辅助参考视角）

| 工具名 | 说明 |
|--------|------|
| `formula_get_params` | 参考计算参数（辅助视角） |
| `formula_calc_ivi` | 参考计算 IVI（意图真实度） |
| `formula_calc_spe` | 参考计算 SPE（社交势能） |
| `formula_calc_ews` | 参考计算 EWS（升温窗口期） |
| `formula_calc_is` | 参考计算 IS（真实亲密度） |
| `formula_calc_gap_effect` | 参考计算 Gap_Effect（情绪落差刺激） |
| `formula_calc_eev` | 参考计算 EEV（升温期望值） |
| `formula_calc_cs` | 参考计算 CS（矛盾演化状态） |
| `formula_calc_action` | 参考决策（进攻/拉扯/重置/维持） |

### 使用指南工具（1 个）

| 工具名 | 参数 | 说明 |
|--------|------|------|
| `guide` | `topic` | 获取使用指南和工作流文档。11 个主题：getting-started / workflow/analysis / report-template / methodology / rules/evidence / rules/permissions / rules/reply / workflow/maintain / reference/sync / reference/formula / reference/stickers |

### 工作流导航工具（2 个）

| 工具名 | 参数 | 说明 |
|--------|------|------|
| `skill_map` | `tool_name` | 查询工具与 Skill 的双向映射，返回下一步建议 |
| `workflow_step` | `workflow, step` | 按步骤执行工作流，返回当前步骤详情和下一步指引 |

## 工具分类汇总

| 分类 | 数量 |
|------|------|
| 数据获取（只读） | 13 |
| 数据写入 | 14 |
| 同步 | 6 |
| 联系人管理 | 7 |
| 贴纸管理 | 3 |
| 公式（辅助） | 9 |
| 工作流导航 | 2 |
| 使用指南 | 1 |
| **总计** | **50** |

## 错误处理

所有工具统一错误格式：

```python
{"error": "PERSON_NOT_FOUND", "message": "未找到联系人: xxx", "suggestion": "使用 person_rank() 查看所有联系人"}
```

## 同步策略

三层数据新鲜度保障：

```
Layer 1: Windows 计划任务（每日全量）
Layer 2: WCD 常驻后台（开机自启）
Layer 3: MCP 按需增量（person_sync，秒级完成）
```

## 参考文档

- MCP 详细文档：`readme/mcp.md`
- Agent 工具文档：`readme/tools.md`