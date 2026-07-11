# CLAUDE.md

Agent 行为规范。详细架构和工具文档见 `readme/PROJECT.md` 和 `readme/` 下的模块文档。

## 项目概述

LoveMentor 是一个 AI 驱动的恋爱关系辅助系统。用户通过 Claude Code（Agent）与系统交互，Agent 直接调用 Python 工具获取数据，以 Wiki 知识库为推理主轴自行分析后输出结果。公式作为辅助参考视角，不主导决策。

数据来源：WeChatDataAnalysis (WCD) 或 WeFlow HTTP API → 同步管道 → 本地 SQLite → 分析引擎 → Agent 工具。

## 架构

```
原始知识文件          WCD / WeFlow API
       │                    │
       ▼                    ▼
┌──────────────┐    ┌──────────────┐
│  Wiki 知识库  │    │ engine/      │
│  (推理主轴)   │    │  importers/  │ → data/raw/core.db (SQLite)
│  docs/wiki/  │    │  analyzers/  │ → 指标/排名/事件检测
└──────┬───────┘    └──────┬───────┘
       │                   │
       └───────┬───────────┘
               ▼
       engine/tools.py ←── Agent 工具入口
               │
       ┌───────┴───────┐
       ▼               ▼
   Claude Code      MCP Server
   (Python shell)   (FastMCP stdio)
```

## 工程结构

```
engine/              核心逻辑
  tools.py           Agent 工具入口（所有数据操作的统一门面）
  config.py          配置管理（data/system/config.yaml → Config 对象）
  formulas.py        辅助公式（IVI/SPE/EWS 等，自动参数 + manual 参数）
  stickers.py        贴纸词典管理
  agent/             工具实现层（brief/chat/evidence/write/report/sync/signals/moments）
  analyzers/         分析引擎（metrics/ranker/events/stage_recognizer/weekly_report/semantic）
  backtest/          回测框架（collect/analyze/calibrate/semantic_backtest）
  models/            数据模型（base/profile/metrics/stage/strategy/evaluation/event/failure/ranking/date_review）
  identity/          身份目录（联系人/账号/别名解析、合并、搜索）
  importers/         同步管道（wcd_client/weflow_client/db_init/sync_messages/ocr）
  knowledge/         Wiki 知识库检索（wiki_index/wiki_retriever/wiki_context）
  facts/             事实档案读写（people_archive/failure_archive）
mcp_server/          FastMCP stdio 服务器，暴露 49 个工具复用 engine/tools.py
data/
  raw/core.db         微信数据 SQLite（同步目标）
  system/config.yaml  系统配置（后端选择、指标权重、Wiki 路径等）
  facts/              事实档案（按人分文件，纯客观事实）
  outputs/            分析输出（analysis/reports/evaluations/rankings）
  cache/              缓存目录（checkpoints/embeddings）
  failures/           失败案例
docs/wiki/           Wiki 知识库（恋爱知识/技巧/场景应对策略，推理主轴）
tests/               pytest 测试
readme/              模块详细文档
exchange/            与 SalesCRM 共享的同步目录（Windows Junction）
_reference/          外部参考源码（WeChatDataAnalysis 等）
```

## 数据流

```
同步：WCD/WeFlow API → engine/importers/* (sync) → data/raw/core.db
分析：data/raw/core.db → engine/analyzers/* (metrics/rank/events) → engine/agent/* → engine/tools.py
检索：docs/wiki/* → engine/knowledge/* (wiki_index/retriever) → engine/tools.py
持久：data/facts/people/*.md (note/date/events) + data/outputs/analysis/* (save_analysis/save_from_markdown)
```

## 数据层优先级

Agent 分析时，事实层优先于历史分析：

| 优先级 | 数据来源 | 工具 | 性质 |
|--------|---------|------|------|
| 1（最高） | 实时数据 | brief/chat/metrics/status | 当前事实，不可推翻 |
| 2 | 事实档案 | evidence | 用户记录的客观事实 |
| 3 | 事件检测 | events | 从数据推导的事件 |
| 4 | 指标计算 | formula_params/formula_* | 量化推导，有置信度 |
| 5（最低） | 历史分析 | data/outputs/analysis/ | 过去的观点，可能已过时 |

当实时数据与历史分析矛盾时，以实时数据为准。

## 核心原则

代码负责数据，Agent 负责推理。

## 工具入口

所有数据操作通过 `engine/tools.py`：

```python
from engine.tools import brief, metrics, chat, wiki_search, rank, status
from engine.tools import brief_data, chat_data, message_context_data
from engine.tools import note, date, evaluate, events, save_analysis
from engine.tools import contact, exclude, failure, sticker
from engine.tools import sync, sync_person, weekly
from engine.tools import behaviors, behaviors_data  # 语义分析（MacBERT/规则双参考）
```

详细签名见 `.claude/skills/mcp-tools.md` 工具速查表或 `readme/tools.md`。

## 常用命令

```bash
# ── 测试 ──
pytest                                    # 运行全部测试
pytest tests/test_metrics.py              # 单文件测试
pytest tests/test_metrics.py -v           # 详细输出
pytest -xvs                               # 失败即停 + 详细 + 不捕获 stdout

# ── 数据同步 ──
# 启动 WCD 后端（同步前确保已运行）
cd _reference/WeChatDataAnalysis && uv run main.py &
# 全量同步（仅首次或修复数据时）
python -c "from engine.tools import sync; print(sync(mode='full'))"
# 增量同步（日常使用）
python -c "from engine.tools import sync; print(sync())"
# 同步单个人（分析前必须调用）
python -c "from engine.tools import sync_person; print(sync_person('姓名'))"

# ── 数据查询（调试）──
python -c "from engine.tools import brief; print(brief('姓名'))"
python -c "from engine.tools import chat; print(chat('姓名', recent=50))"
python -c "from engine.tools import metrics; print(metrics('姓名'))"

# ── Wiki 检索 ──
python -c "from engine.tools import wiki_search; print(wiki_search('查询词'))"

# ── 启动 MCP Server（stdio模式，供 Claude Desktop/Cursor 使用）──
python -m mcp_server.server

# ── 配置 ──
# 数据后端切换：编辑 data/system/config.yaml 的 weflow.backend ("wcd" 或 "weflow")
```

## 开发环境

- Python 3.13+
- 外部依赖：`pyyaml`、`fastmcp`、`pydantic`、`pytest`（见 `requirements.txt`）
- 同步后端需要 WCD (`_reference/WeChatDataAnalysis`) 或 WeFlow 运行中
- 测试不需要后端，使用 `tests/` 下的 fixture 数据
- Windows 环境下：Python 文件 I/O 显式指定 `encoding="utf-8"`

## 禁止事项

- **禁止直接用 `sqlite3` 查数据库**：所有数据操作必须通过 `engine/tools.py` 的函数。直接查库会绕过身份解析，导致 sender 标注混乱。
- **禁止自己写 SQL**：工具函数已封装所有查询，不要重复造轮子。
- **禁止导出原始数据库记录到文件**：会产生冗余文件，且原始 wxid 无法直接理解。
- **禁止向 `data/input/` 写入任何文件**：该目录仅用于用户手动放置截图，agent 不应写入。
- **禁止读取 `data/input/` 下的文件作为分析依据**：用 `chat()` 从数据库获取。
- **禁止调用 LLM API**：Agent 自己就是 LLM，不需要再调 Anthropic/OpenAI 等 API。
- **禁止在非gitignore的文件内写入隐私信息，包括真实姓名、wxid、手机号、邮箱地址、真实昵称、api_key、密钥信息等

## 权限规范

| 操作类型 | 工具 | Agent 行为要求 |
|---------|------|--------------|
| 只读 | brief/chat/evidence/metrics/status/rank/wiki_*/moments_stats/formula_* | 自由调用 |
| 追加写入 | note/date/evaluate | 直接执行，无需确认 |
| 覆盖写入 | save_analysis/save_from_markdown | 覆盖前告知用户 |
| 检测写入 | events(scan=True) | 先展示检测结果，再写入 |
| 不可逆操作 | contact(merge) | **必须向用户确认后再执行** |

## Privacy Rules

- 禁止在任何非 `.gitignore` 文件中写入真实联系人信息。用假名代替。
- `data/raw/core.db`、`data/system/config.yaml`、`data/facts/people/` 均为私有本地数据，不得写入可提交文件。

## Agent Skill

`.claude/skills/love-mentor.md` — 主入口 skill（MCP 工具使用指南，渐进式披露）。

参考文件（按需阅读）：
- `mcp-analysis.md` — 完整分析流程 + 决策树 + 报告模板
- `mcp-tools.md` — 所有 MCP 工具速查表
- `mcp-methodology.md` — 方法论（Wiki主轴/公式辅助/冲突裁决/指标体系）
- `mcp-rules.md` — 规则（权限/事实档案/回复构造/路由表/禁止事项）

MCP 也提供 `guide(topic)` 工具（11 个主题），是 skill 的精简备选。

## Skill-MCP 融合架构

本系统采用"**Skill 编排流程 + MCP 执行能力**"的融合架构：

### 双向导航机制

| 工具 | 功能 | 用法示例 |
|------|------|---------|
| `skill_map(tool_name)` | 查询工具与 Skill 的双向映射，返回下一步建议 | `skill_map('person_brief')` |
| `workflow_step(workflow, step)` | 按步骤执行工作流，返回当前步骤详情和下一步指引 | `workflow_step('analysis', 0)` |

### 工作流列表

| 工作流 | 名称 | 步骤数 | 适用场景 |
|--------|------|--------|----------|
| `analysis` | 人物分析完整流程 | 13 步 | "分析XX"、"帮我看看XX" |
| `emergency_reply` | 紧急回复流程 | 4 步 | "她发了XX怎么回" |
| `weekly` | 周报流程 | 2 步 | "做周报" |
| `maintain` | 维持关系流程 | 4 步 | "维持关系" |

### 核心工作流（analysis）步骤

```
0: person_sync → 1: person_brief → 2: wiki_search → 3: wiki_read → 4: person_chat
→ 5: person_metrics → 6: person_signals → 7: person_stage → 8: person_timeline
→ 9: person_evidence → 10: formula_get_params → 11: formula_calc_ivi → 12: save_from_markdown
```

### 使用模式

**模式 1：按工作流执行**
```python
workflow_step('analysis')        # 查看流程概览
workflow_step('analysis', 0)     # 获取第0步详情
# 执行 person_sync
workflow_step('analysis', 1)     # 获取第1步详情
# 执行 person_brief
# ...
```

**模式 2：工具驱动探索**
```python
skill_map('person_brief')        # 查 person_brief 之后能调什么
# 根据返回的下一步建议选择工具
```

### 数据源

- `skill/mcp_index.yaml` — 双向索引文件（工具→Skill→工作流映射）
- `mcp_server/tools_workflow.py` — 工作流工具实现

## 同步规范

- **自动解密**：`sync()` 和 `sync_person()` 使用 WCD 后端时，自动调用 `/api/decrypt` 刷新数据库快照（用缓存密钥，不重启微信）。30 分钟内重复同步自动跳过解密，无需手动干预。
- **仅同步私聊**：`sync()` 只处理 `type='private'` 的会话（个人聊天），群聊和公众号消息不会被同步。`sync_person()` 不受此限制。
- **默认增量同步**：`sync()` 和 `sync_person()` 默认 `mode='incremental'`，日常使用增量模式。
- **少用全量**：`mode='full'` 仅在数据修复时使用。
- **WCD 启动**：同步前确保 WCD API 已启动：`cd _reference/WeChatDataAnalysis && uv run main.py &`
- **禁止频繁调用 `fetch_keys`**：此操作会重启微信并要求扫码登录。密钥通过 `account_keys.json` 持久化，WCD 启动时自动加载。
- **数据后端**：通过 `config.yaml` 的 `weflow.backend` 切换 `"wcd"` 或 `"weflow"`，两个客户端接口兼容。

## Conventions

- Wiki 和分析框架使用中文，技术术语保留英文。
- `engine/` 的外部依赖：`pyyaml`、`rapidocr-onnxruntime`、`Pillow`。同步管道和分析器使用 Python 标准库。
- `data/facts/` 是纯事实层：只记录客观事实，不做分析。分析和策略由 Agent 负责。
  - **写入前自检三问**：① 这条信息是对方说的/做的，还是我推断的？→ 只能写前者。② 换一个 Agent 读这条信息，会得出同样的结论吗？→ 如果不会，说明掺杂了判断。③ 这条信息 3 个月后还有效吗？→ 事实是稳定的，判断会过时。
  - **概念分层**：事实档案（evidence layer：note/date/events）只存客观事实；分析归档（evaluation layer：evaluate/save_analysis）存主观判断，优先级低于事实层。`person_evaluate` 概念上归入分析归档，不归入事实档案。
- 同步管道用 `get_messages` API（可靠），不用 `pull_messages`（不可靠）。
- **每次改动后自检是否要写 exchange 记录**：`exchange/` 是与 SalesCRM 共享的同步目录（Windows Junction）。完成代码修改后先问自己——"这个改动对方项目也能用吗？"能用就写，不用等人工对比。
  - **需要写 exchange 的**：架构/基础设施改动（tools.py 重构、新增工具函数、数据模型变更）、Bug 修复、业务无关新功能（贴纸系统、朋友圈统计、事件检测）、性能优化、代码质量改进、工具脚本
  - **不需要写 exchange 的**：业务术语/文案（恋爱↔销售术语替换）、知识库内容（Wiki 实体/场景页面 — docs 各自独立 git）、业务数据（facts/联系人/客户数据 — data 各自独立 git）、项目专属配置/功能
  - **记录格式**：`exchange/YYYY-MM-DD_简要描述.md`，包含改动内容、涉及文件、来源项目、同步建议、注意事项
