# Readme 模块文档

## 概述

`readme/` 存放项目的**详细模块文档**，包括架构设计、工具说明、分析流程、公式系统等。这些文档是理解项目架构和功能的权威参考。

## 文件清单

| 文件 | 内容 | 适用读者 |
|------|------|---------|
| `PROJECT.md` | 项目总览（架构、已实现功能、工具列表、使用方法） | 所有人 |
| `tools.md` | Agent 工具详细文档（工具的签名、参数、返回值） | 开发者、Agent |
| `agent.md` | Agent 工具实现层文档（工具分层、返回 schema、权限规范） | 开发者 |
| `analyzers.md` | 分析引擎文档（指标计算、排名、事件检测、阶段识别） | 开发者 |
| `backtest.md` | 回测框架文档（案例内时序分析、描述性统计、校准闭环） | 开发者 |
| `formulas.md` | 公式参考文档（IVI/SPE/EWS 等战态公式的原理和用法） | 开发者、Agent |
| `facts.md` | 事实档案文档（evidence/evaluation 分层、自检清单） | 开发者、Agent |
| `identity.md` | 身份目录文档（Person→Account→Alias 三层映射） | 开发者 |
| `importers.md` | 同步管道文档（WCD/WeFlow 同步流程） | 开发者 |
| `knowledge.md` | Wiki 知识库文档（检索机制、OKF 格式、渐进式披露） | 开发者、Agent |
| `models.md` | 数据模型文档（dataclass 定义、字段说明） | 开发者 |
| `mcp.md` | MCP 服务器文档（工具清单、配置方法、错误处理） | 开发者、Agent |
| `mcp_guide_completion.md` | MCP guide 工具完成记录 | 开发者 |
| `mcp_information_gap.md` | MCP 工具信息缺口分析 | 开发者 |
| `architecture_correction_completed.md` | 架构矫正完成记录 | 开发者 |
| `future_formula_wiki_metadata.md` | P6 未来计划：公式-Wiki 结构化元数据 | 规划者 |
| `maintain-relationship-workflow.md` | 维持关系工作流详细文档 | 开发者、Agent |

## 文档分类

### 核心文档

| 文档 | 用途 |
|------|------|
| `PROJECT.md` | 项目总览，入门必读 |
| `tools.md` | 工具速查，开发者常用 |
| `mcp.md` | MCP 服务器配置和使用 |

### 模块文档

| 文档 | 对应模块 |
|------|---------|
| `agent.md` | engine/agent/ |
| `analyzers.md` | engine/analyzers/ |
| `backtest.md` | engine/backtest/ |
| `facts.md` | engine/facts/ |
| `identity.md` | engine/identity/ |
| `importers.md` | engine/importers/ |
| `knowledge.md` | engine/knowledge/ |
| `models.md` | engine/models/ |

### 方法论文档

| 文档 | 用途 |
|------|------|
| `formulas.md` | 公式系统原理和用法 |
| `maintain-relationship-workflow.md` | 维持关系流程 |

### 历史记录

| 文档 | 用途 |
|------|------|
| `architecture_correction_completed.md` | 架构矫正完成记录 |
| `mcp_guide_completion.md` | MCP guide 工具完成记录 |
| `mcp_information_gap.md` | MCP 工具信息缺口分析 |

### 未来计划

| 文档 | 用途 |
|------|------|
| `future_formula_wiki_metadata.md` | P6 未来计划 |

## 阅读建议

### 初次接触项目

1. 先读 `PROJECT.md` — 了解项目整体架构和核心功能
2. 再读 `tools.md` — 了解可用工具
3. 最后读感兴趣的模块文档

### 开发新功能

1. 读对应的模块文档（如开发指标功能读 `analyzers.md`）
2. 读 `tools.md` 了解工具契约
3. 读 `models.md` 了解数据模型

### Agent 使用

1. 读 `mcp.md` — 了解 MCP 工具清单
2. 读 `tools.md` — 了解工具签名和用法
3. 读 `formulas.md` — 了解公式系统

## 文档更新原则

1. **代码优先**：文档描述应与代码实现一致
2. **及时更新**：代码变更后同步更新文档
3. **结构清晰**：按章节组织，便于查阅
4. **示例丰富**：提供代码示例和使用场景