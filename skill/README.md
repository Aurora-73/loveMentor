# Skill Agent 技能文档

## 概述

`skill/` 存放 Agent 的**技能文档**，采用渐进式披露结构，指导 Agent 如何使用 MCP 工具进行恋爱关系分析。Skill 层负责业务流程编排和决策规则定义，与 MCP 层（执行能力）形成融合架构。

## 架构定位

```
Skill 层（业务流程编排）                    MCP 层（标准化执行）
    │                                          │
    ├── love-mentor.md（主入口）               ├── person_sync
    ├── mcp-analysis.md（分析流程）            ├── person_brief
    ├── mcp-methodology.md（方法论）           ├── wiki_search
    ├── mcp-rules.md（规则）                   ├── person_chat
    ├── mcp-tools.md（工具速查）               ├── person_metrics
    ├── mcp_index.yaml（双向索引）             ├── ... (50个工具)
    ├── workflows/（工作流）
    ├── signals/（信号解读）
    ├── metrics/（指标体系）
    └── formulas/（公式）
```

## 目录结构

```
skill/
├── love-mentor.md           # 主入口（场景路由 + 核心原则 + 渐进式参考）
├── mcp-analysis.md          # 分析流程 + 决策树 + 报告模板
├── mcp-methodology.md       # 方法论（Wiki主轴/公式辅助/冲突裁决/指标体系）
├── mcp-rules.md             # 规则（权限/事实档案/回复构造/路由表/禁止事项）
├── mcp-tools.md             # 工具速查（49个工具的参数和用法）
├── mcp_index.yaml           # 双向索引数据源（工具→Skill→工作流映射，49个工具）
├── workflows/               # 工作流子文件（渐进式披露）
│   ├── analysis.md          # 分析流程 11 步详细步骤
│   ├── emergency_reply.md   # 紧急回复 4 步流程
│   ├── weekly.md            # 周报 2 步流程
│   └── maintain.md          # 维持关系 4 步流程
├── signals/                 # 信号解读子文件
│   ├── basic_signals.md     # 基础信号（IOI/冷落/窗口/需求感）
│   └── manipulation_signals.md # 操控信号（废物测试/框架操控/情绪操控）
├── metrics/                 # 指标体系子文件
│   └── metrics_system.md    # 15维指标详解（权重/计算方式/解读方法）
└── formulas/                # 公式子文件
    ├── war_formulas.md      # 战态公式详解（IVI/SPE/EWS等）
    └── skill_map.md         # 公式与 Skill 的映射关系
```

## 文件详解

### 主入口文件

| 文件 | 职责 | 核心内容 |
|------|------|---------|
| `love-mentor.md` | 统一入口 | 三件事你必须知道、基本流程、快速场景速查、渐进式参考文件 |

### 流程文档

| 文件 | 职责 | 核心内容 |
|------|------|---------|
| `mcp-analysis.md` | 分析流程 | 完整分析流程、决策树、10个场景处理、8段式报告模板 |
| `workflows/analysis.md` | 分析流程详细步骤 | 11步详细工作流（wiki_context 为主入口） |
| `workflows/emergency_reply.md` | 紧急回复流程 | 4步紧急回复流程 |
| `workflows/weekly.md` | 周报流程 | 2步周报流程 |
| `workflows/maintain.md` | 维持关系流程 | 4步维持关系流程 |

### 方法论文档

| 文件 | 职责 | 核心内容 |
|------|------|---------|
| `mcp-methodology.md` | 方法论 | Wiki 主轴、公式辅助、冲突裁决、15维指标体系、9个关系阶段 |

### 规则文档

| 文件 | 职责 | 核心内容 |
|------|------|---------|
| `mcp-rules.md` | 规则 | 操作权限规范、事实档案写入规则、回复构造规则、路由表、禁止事项 |

### 工具文档

| 文件 | 职责 | 核心内容 |
|------|------|---------|
| `mcp-tools.md` | 工具速查 | 49个工具的参数、返回值、用途分类 |

### 信号文档

| 文件 | 职责 | 核心内容 |
|------|------|---------|
| `signals/basic_signals.md` | 基础信号 | IOI、冷落、窗口、需求感、互动模式 |
| `signals/manipulation_signals.md` | 操控信号 | 废物测试、框架操控、情绪操控 |

### 指标文档

| 文件 | 职责 | 核心内容 |
|------|------|---------|
| `metrics/metrics_system.md` | 指标体系 | 22维指标详解（16行为统计+6 Wiki衍生+3语义）、乘法惩罚、信号等级、动态信号 |

### 公式文档

| 文件 | 职责 | 核心内容 |
|------|------|---------|
| `formulas/war_formulas.md` | 战态公式 | IVI/SPE/EWS/IS/Gap_Effect/EEV/CS/action |
| `formulas/skill_map.md` | 公式映射 | 公式与 Skill 的映射关系 |

## Skill-MCP 融合架构

### 核心工具

| 工具 | 功能 | 参数 |
|------|------|------|
| `skill_map(tool_name)` | 查询工具与 Skill 的双向映射，返回下一步建议 | tool_name（可选） |
| `workflow_step(workflow, step)` | 按步骤执行工作流，返回当前步骤详情和下一步指引 | workflow, step（可选） |

### 工作流列表

| 工作流 | 名称 | 步骤数 | 适用场景 |
|--------|------|--------|----------|
| `analysis` | 人物分析完整流程 | 11步 | "分析XX"、"帮我看看XX" |
| `emergency_reply` | 紧急回复流程 | 4步 | "她发了XX怎么回" |
| `weekly` | 周报流程 | 2步 | "做周报" |
| `maintain` | 维持关系流程 | 4步 | "维持关系" |

### 使用模式

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

## 渐进式披露原则

1. **入口精简**：主入口 `love-mentor.md` 只包含核心原则和快速参考
2. **按需展开**：详细内容在子文件中，Agent 按需阅读
3. **层次分明**：工作流 → 信号 → 指标 → 公式，逐层深入
4. **交叉引用**：文档间通过 `[[条目名]]` 格式互相引用

## 参考文档

- MCP 服务器文档：`readme/mcp.md`
- 项目总览：`readme/PROJECT.md`