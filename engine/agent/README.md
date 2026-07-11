# Agent 工具实现层

## 概述

`engine/agent/` 是 Agent 工具的**底层实现层**，按功能域拆分到各个模块。`engine/tools.py` 作为统一入口，将用户传入的人名解析为数据库连接和身份对象后，调用本目录下的对应函数。

## 架构定位

```
engine/tools.py（统一入口）
    │
    └── 调用 engine/agent/ 下的模块
            │
            ├── brief.py      → 全局摘要
            ├── chat.py       → 聊天记录
            ├── evidence.py   → 事实追溯
            ├── write.py      → 数据写入
            ├── report.py     → 指标报告
            ├── sync_agent.py → 数据同步
            ├── signals.py    → 信号检测
            ├── moments.py    → 朋友圈
            ├── identity_ops.py → 身份管理
            └── ...
```

## 模块清单

| 文件 | 职责 | 对外工具 |
|------|------|---------|
| `core.py` | 共享基础设施（连接/解析/交叉引用） | 内部使用 |
| `context.py` | 上下文组装器（ContextBuilder） | 内部使用 |
| `registry.py` | Skill 注册表（SkillRegistry） | 内部使用 |
| `brief.py` | 全局摘要（身份+指标+事件+信号+Wiki推荐） | `brief`, `brief_data` |
| `snapshot.py` | 摘要辅助（个人模式/消息筛选/月度统计） | 内部使用 |
| `recommend.py` | Wiki/框架推荐 | 内部使用 |
| `chat.py` | 聊天证据（结构化消息列表） | `chat`, `chat_data`, `message_context_data` |
| `evidence.py` | 事实追溯（timeline/evaluations/notes/dates） | `evidence` |
| `material.py` | 材料搜索/阅读 | `wiki_search`, `wiki_read` |
| `write.py` | 数据写入（note/date/evaluate/events/save_*） | `note`, `date`, `evaluate`, `events`, `save_analysis`, `save_from_markdown` |
| `moments.py` | 朋友圈（互动统计/同步到档案） | `moments_stats`, `sync_moments` |
| `sync_agent.py` | 数据同步（增量/全量） | `sync`, `sync_person` |
| `report.py` | 指标报告（metrics/status/rank/weekly） | `metrics`, `status`, `rank`, `weekly` |
| `identity_ops.py` | 身份管理（contact/exclude/failure/sticker） | `contact`, `exclude`, `failure`, `sticker` |
| `signals.py` | 信号检测（关键词/操控/朋友圈联动） | `signals`, `stage` |
| `maintain.py` | 维持关系候选人筛选 | `maintain_candidates`, `format_candidates` |
| `response.py` | 回复构造辅助 | 内部使用 |

## 设计模式

### 函数签名规范

所有底层函数遵循统一签名模式：

```python
def agent_xxx(conn, config, person, **kwargs):
    """
    conn: sqlite3.Connection — 数据库连接
    config: Config — 配置对象
    person: IdentityPerson — 身份对象
    kwargs: 业务参数
    返回: dict / str
    """
```

### 错误处理

- 不抛异常，返回描述性字符串
- `isinstance(result, dict)` 判断成功与否
- 错误消息包含建议：`"未找到联系人: XX。建议使用 contact_search() 搜索"`

## 工具分类

### 数据读取（只读）

| 工具 | 返回类型 | 用途 |
|------|---------|------|
| `brief` | str | 全局视图（格式化） |
| `brief_data` | dict | 结构化摘要 |
| `chat` | str | 聊天记录（格式化） |
| `chat_data` | dict | 结构化消息列表 |
| `message_context_data` | dict | 消息上下文 |
| `evidence` | str | 事实档案 |
| `metrics` | dict | 全部指标 |
| `status` | str | 格式化状态表 |
| `rank` | str | 联系人排名 |
| `wiki_search` | str | Wiki 搜索 |
| `wiki_read` | str | Wiki 页面读取 |
| `moments_stats` | dict | 朋友圈互动统计 |

### 数据写入

| 工具 | 用途 |
|------|------|
| `note` | 添加备注到事实档案 |
| `date` | 记录约会 |
| `evaluate` | 记录主观评估 |
| `events` | 检测并写入关系事件 |
| `save_analysis` | 保存分析结论到 YAML |
| `save_from_markdown` | 从 Markdown 保存分析 |

### 身份管理

| 工具 | 用途 |
|------|------|
| `contact` | 身份目录操作（search/alias/merge） |
| `exclude` | 排除管理 |
| `failure` | 失败案例管理 |
| `sticker` | 贴纸管理 |

### 同步和报告

| 工具 | 用途 |
|------|------|
| `sync` | 全局同步 |
| `sync_person` | 按人名同步 |
| `sync_moments` | 同步朋友圈互动 |
| `weekly` | 生成周报 |
| `compare_analysis` | 对比分析 |

### 维持关系

| 工具 | 用途 |
|------|------|
| `maintain_candidates` | 筛选需要维持关系的候选人 |
| `format_candidates` | 格式化为 Markdown |

## 数据层优先级

Agent 分析时按以下优先级处理数据：

1. **实时数据**（最高）：brief/chat/metrics/status — 当前事实，不可推翻
2. **事实档案**：evidence — 用户记录的客观事实
3. **事件检测**：events — 从数据推导的事件
4. **公式计算**：formula_* — 量化推导，有置信度
5. **历史分析**（最低）：data/outputs/analysis/ — 过去的观点，可能已过时

## 参考文档

- 工具详细文档：`readme/tools.md`
- Agent 工具契约：`readme/agent.md`