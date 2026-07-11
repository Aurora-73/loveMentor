# Knowledge Wiki 知识库检索

## 概述

`engine/knowledge/` 负责 **Wiki 知识库的索引和检索**，是 Agent 推理的核心依据。Wiki 不是"参考资料"，而是分析方法论的来源，贯穿分析过程的每个环节。

## 架构定位

```
docs/wiki/（OKF 格式知识库，329个页面）
    │
    └── engine/knowledge/（检索引擎）
            │
            ├── wiki_index.py     → 索引加载（search-index.json）
            ├── wiki_retriever.py → 检索器（多维打分）
            └── wiki_context.py   → prompt 格式化
                    │
                    ▼
            Agent 工具：wiki_search / wiki_read / wiki_context
```

## 模块清单

| 文件 | 职责 | 核心功能 |
|------|------|---------|
| `wiki_index.py` | 索引加载 | 加载 search-index.json，提供索引查询接口 |
| `wiki_retriever.py` | 检索器 | 五维度评分（title/keyword/tag/stage/skill）+ 别名扩展 |
| `wiki_context.py` | prompt 格式化 | 批量构建知识上下文（合并去重+阶段加权+预算裁剪） |

## Wiki 知识库格式

### OKF（Open Knowledge Format）

Wiki 页面采用 Markdown + YAML 前置元数据格式：

```markdown
---
title: "IOI（兴趣指标）"
type: entity
tags: ["IOI", "兴趣指标", "信号"]
keywords: ["IOI", "Indicator of Interest", "兴趣"]
stages: ["初识", "有基本互动", "高频聊天"]
skills: ["识别信号", "判断意向"]
---

# IOI（兴趣指标）

...
```

### 页面类型

| 类型 | 含义 | 示例 |
|------|------|------|
| `entity` | 概念/框架 | IOI（兴趣指标）、窗口识别、框架（Frame） |
| `scenario` | 场景决策页 | 她不回消息了怎么办、第一次约会怎么安排 |
| `topic` | 主题综述 | 需求感控制、展示面建设 |
| `synthesis` | 跨源对比 | 升温实操手册、技术导师陷阱 |
| `source` | 来源摘要 | 林老头系统摘要、柯李思方法论 |

## 检索机制

### 五维度评分

检索器对每个 Wiki 页面进行五维度评分：

| 维度 | 评分逻辑 | 权重 |
|------|---------|------|
| title | 标题匹配度 | 高 |
| keyword | 关键词匹配度 | 中 |
| tag | 标签匹配度 | 中 |
| stage | 关系阶段匹配度 | 中 |
| skill | 技能匹配度 | 低 |

### 别名扩展

自动扩展同义词：
- "推拉" → "推拉节奏" → "欲擒故纵" → "情绪波动"
- "需求感" → "需求感控制" → "70%频率法则"

### 渐进式披露

4 种 task_type 预算控制返回内容量：

| task_type | 用途 | 返回内容量 |
|-----------|------|-----------|
| `default` | 默认 | 适中 |
| `reply` | 紧急回复 | 精简 |
| `deep` | 深度分析 | 详细 |
| `search` | 搜索 | 全面 |

## 核心函数

### wiki_index.py

| 函数 | 职责 | 参数 |
|------|------|------|
| `load_index()` | 加载搜索索引 | 无 |
| `get_index()` | 获取索引实例 | 无 |
| `search_index(query)` | 索引查询 | query |

### wiki_retriever.py

| 函数 | 职责 | 参数 |
|------|------|------|
| `search_wiki(query, limit=10, stages=None, focus=None)` | 搜索 Wiki | query, limit, stages, focus |
| `read_wiki(path, max_chars=50000)` | 读取 Wiki 页面 | path, max_chars |
| `dedup_pages(pages)` | 页面去重 | pages |

### wiki_context.py

| 函数 | 职责 | 参数 |
|------|------|------|
| `build_wiki_context(queries, stage=None, focus=None, max_tokens=8000)` | 批量构建知识上下文 | queries, stage, focus, max_tokens |

## Agent 工具接口

| 工具 | 用途 | 说明 |
|------|------|------|
| `wiki_search(query, limit=10)` | 精确搜索 | 用于钻取特定关键词 |
| `wiki_read(path, max_chars=50000)` | 读取页面全文 | 用于精确引用 |
| `wiki_context(queries, stage, focus)` | 批量构建上下文 | 【推荐】一次返回格式化 prompt 段落 |

## wiki_context 核心功能

`wiki_context` 是推荐的主入口，提供以下功能：

1. **合并多条查询**：传入多个关键词，一次返回综合结果
2. **阶段过滤**：根据当前关系阶段筛选相关页面
3. **焦点加权**：根据 focus 参数（signals/chat/strategy/risk）调整评分权重
4. **去重处理**：合并相同或相似的页面，返回去重前后的计数
5. **预算裁剪**：根据 max_tokens 限制返回内容量
6. **格式化输出**：返回可直接嵌入推理的 Markdown 段落

## Wiki 在分析流程中的角色

Wiki 是推理主轴，贯穿分析过程的每个环节：

```
分析流程中调用 Wiki 的时机：
├── 第0步: person_sync → 同步后不查（无数据）
├── 第1步: person_brief → 看到信号后立即查 wiki_context(focus="signals")
├── 第2步: wiki_context → 构建知识框架
├── 第3步: person_chat → 看到聊天模式后查 wiki_context(focus="chat")
├── 第4步: person_metrics → 看到指标后查 wiki_context(focus="signals")
├── 第5步: person_signals → 看到信号类型后用 wiki_read 读全文
├── 第6步: person_stage → 看到阶段后查 wiki_context(stage=阶段, focus="strategy")
├── 第7步: person_timeline → 看到趋势后查 wiki_context(focus="risk")
├── 第8步: person_evidence → 对比历史事实与 Wiki 框架
├── 第9-10步: 公式核验 → 用 Wiki 核验公式结果
└── 第11步: 写报告 → 引用 Wiki 条目作为策略依据
```

## 参考文档

- Wiki 知识库详细文档：`readme/knowledge.md`
- 方法论：`skill/mcp-methodology.md#Wiki是推理主轴`