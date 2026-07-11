# Workflows 工作流

## 概述

`workflows/` 存放 Agent 的**工作流定义**，每个工作流描述一个完整的业务流程，指导 Agent 按步骤完成特定任务。工作流通过 `skill_map` 和 `workflow_step` 工具动态提供给 Agent。

## 工作流列表

| 工作流 | 文件 | 步骤数 | 适用场景 |
|--------|------|--------|----------|
| `analysis` | `analysis.md` | 11步 | "分析XX"、"帮我看看XX" |
| `emergency_reply` | `emergency_reply.md` | 4步 | "她发了XX怎么回" |
| `weekly` | `weekly.md` | 2步 | "做周报" |
| `maintain` | `maintain.md` | 4步 | "维持关系" |

## 工作流详解

### analysis — 人物分析完整流程（11步）

**适用场景**：用户要求分析某个联系人的关系状态

**步骤概览**：

| 步骤 | 工具 | 说明 |
|------|------|------|
| 0 | `person_sync` | 同步最新数据 |
| 1 | `person_brief` | 获取全局视图 |
| 2 | `wiki_context` | 构建知识框架（合并步骤2-3） |
| 3 | `person_chat` | 查看聊天记录 |
| 4 | `person_metrics` | 获取详细指标 |
| 5 | `person_signals` | 查看信号详情 |
| 6 | `person_stage` | 识别关系阶段 |
| 7 | `person_timeline` | 查看关系时间线 |
| 8 | `person_evidence` | 查看事实档案 |
| 9-10 | 公式核验 | 辅助参考（可选） |
| 11 | `save_from_markdown` | 保存分析报告 |

**核心优化**：步骤2-3（wiki_search + wiki_read）已合并为 `wiki_context`，减少 RPC 调用次数。

### emergency_reply — 紧急回复流程（4步）

**适用场景**：用户收到对方消息，需要快速回复

**步骤概览**：

| 步骤 | 工具 | 说明 |
|------|------|------|
| 0 | `person_brief` | 获取最新状态 |
| 1 | `person_chat` | 查看最近对话 |
| 2 | `wiki_context` | 查找相关策略 |
| 3 | 返回回复建议 | 无需工具调用 |

### weekly — 周报流程（2步）

**适用场景**：用户要求生成周报

**步骤概览**：

| 步骤 | 工具 | 说明 |
|------|------|------|
| 0 | `system_sync` | 全量同步数据 |
| 1 | `weekly_report` | 生成周报 |

### maintain — 维持关系流程（4步）

**适用场景**：用户要求维持与某些联系人的关系

**步骤概览**：

| 步骤 | 工具 | 说明 |
|------|------|------|
| 0 | `maintain_list` | 获取需要维持关系的候选人 |
| 1 | `person_brief` | 逐个查看状态 |
| 2 | `wiki_context` | 获取维持策略 |
| 3 | 返回维持建议 | 无需工具调用 |

## 工作流调用方式

### 方式1：按步骤执行（推荐）

```python
workflow_step('analysis')        # 查看流程概览
workflow_step('analysis', 0)     # 获取第0步详情
person_sync('XX')                # 执行第0步
workflow_step('analysis', 1)     # 获取第1步详情
person_brief('XX')               # 执行第1步
# ...
```

### 方式2：工具驱动探索

```python
skill_map('person_brief')        # 查 person_brief 之后能调什么
# 根据返回的下一步建议选择工具
```

## 设计原则

1. **渐进式披露**：每步只显示当前步骤的详细信息
2. **灵活跳转**：支持按步骤顺序执行或自由探索
3. **Wiki 贯穿**：每个步骤都可能调用 `wiki_context` 获取知识支持
4. **公式辅助**：公式只在特定步骤出现，不主导流程

## 参考文档

- 分析流程详细文档：`readme/maintain-relationship-workflow.md`