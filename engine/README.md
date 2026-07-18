# Engine 核心引擎

## 概述

`engine/` 是 LoveMentor 项目的**核心逻辑层**，负责数据同步、分析计算、知识库检索和事实档案管理。它是纯数据处理层，不依赖 LLM，通过 `tools.py` 向 Agent 提供统一的工具接口。

## 架构定位

```
WCD/WeFlow API ──┐
                 ▼
         engine/importers/ ──→ data/raw/core.db
                 │
         engine/analyzers/ ──→ 指标/排名/事件检测
                 │
         engine/knowledge/ ──→ Wiki 知识库检索
                 │
         engine/facts/ ──→ 事实档案读写
                 │
                 ▼
         engine/tools.py ←── Agent 调用入口
```

## 目录结构

| 子目录 | 职责 | 核心文件 |
|--------|------|---------|
| `agent/` | Agent 工具实现层 | brief.py, chat.py, evidence.py, write.py, sync_agent.py |
| `analyzers/` | 分析引擎 | metrics.py, ranker.py, events.py, stage_recognizer.py |
| `backtest/` | 回测框架验证 | collect.py, analyze.py, calibrate.py, validate.py |
| `facts/` | 事实档案读写 | people_archive.py, failure_archive.py |
| `identity/` | 身份目录 | directory.py |
| `importers/` | 数据同步管道 | sync.py, wcd_client.py, weflow_client.py |
| `knowledge/` | Wiki 知识库检索 | wiki_index.py, wiki_retriever.py, wiki_context.py |
| `models/` | 数据模型 | base.py, metrics.py, stage.py, strategy.py |
| `stickers/` | 贴纸词典管理 | core.py, label.py |

## 核心文件

| 文件 | 职责 |
|------|------|
| `tools.py` | Agent 工具统一入口，包装所有底层函数，自动处理 conn/config/person 解析 |
| `config.py` | 配置管理，从 `data/system/config.yaml` 加载 Config 对象 |
| `formulas.py` | 战态公式（IVI/SPE/EWS 等），自动参数 + manual 参数 |

## 工具分层架构

```
Agent 调用: chat('小溪', recent=50)
    ↓
tools.py 包装层: _resolve('小溪') → (conn, config, person)
    ↓
engine/agent/chat.py: agent_chat(conn, config, person, recent=50)
    ↓
返回: dict / str
```

包装层只做三件事：
1. 将 `name: str` 解析为 `(conn, config, person)` 三元组
2. 调用底层函数
3. `conn.close()` 关闭连接

## 数据流向

```
同步：WCD/WeFlow API → engine/importers/* → data/raw/core.db
分析：data/raw/core.db → engine/analyzers/* → engine/agent/* → engine/tools.py
检索：docs/wiki/* → engine/knowledge/* → engine/tools.py
持久：data/facts/people/*.md + data/outputs/analysis/*
```

## 关键设计原则

1. **禁止直接查库**：所有数据操作必须通过 `tools.py`，绕过身份解析会导致 sender 标注混乱
2. **错误返回字符串**：所有工具不抛异常，错误情况返回描述性 str（如 "未找到联系人: XX"）
3. **向后兼容**：新增参数必须有默认值，不破坏已有调用
4. **读写分离**：只读工具（brief/chat/metrics）无副作用，写入工具（note/date/save）有明确权限规范

## 外部依赖

| 依赖 | 用途 | 是否必须 |
|------|------|---------|
| pyyaml | 配置文件解析 | 是 |
| rapidocr-onnxruntime | 截图 OCR | 仅 import-chat |
| Pillow | 图片尺寸读取 | 仅 import-chat |

同步管道和分析器使用 Python 标准库（sqlite3、urllib、json）。

## 与 MCP Server 的关系

`mcp_server/` 通过 `engine/tools.py` 暴露工具，MCP 是一层薄包装，不重复实现业务逻辑：

```
MCP Server (FastMCP stdio)
    │
    └── 调用 engine/tools.py 中的函数
        │
        └── 调用 engine/agent/、engine/analyzers/、engine/knowledge/ 等底层模块
```

## 参考文档

- 详细工具文档：`readme/tools.md`
- Agent 工具实现：`readme/agent.md`
- 分析器文档：`readme/analyzers.md`
- 公式文档：`readme/formulas.md`
