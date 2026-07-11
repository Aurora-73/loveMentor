# Facts 事实档案

## 概述

`engine/facts/` 负责**事实档案的读写操作**，将用户记录的客观事实（备注、约会、事件、朋友圈互动）持久化到 Markdown 文件中。事实档案是 Agent 分析的重要参考依据，优先级高于历史分析结论。

## 架构定位

```
Agent 工具调用: note("小溪", "她说喜欢猫")
    │
    └── engine/agent/write.py
            │
            └── engine/facts/people_archive.py
                    │
                    └── data/facts/people/<显示名>__<person_id>.md
```

## 模块清单

| 文件 | 职责 | 核心功能 |
|------|------|---------|
| `people_archive.py` | 人物档案读写 | 读取/写入/追加人物档案（notes/dates/events/evaluations） |
| `failure_archive.py` | 失败案例读写 | 记录和查询失败案例 |

## 档案结构

### 人物档案

路径：`data/facts/people/<显示名>__<person_id>.md`

**文件格式**（Markdown + YAML Frontmatter）：

```markdown
---
person_id: "p123"
display_name: "小溪"
created_at: "2026-01-01T00:00:00"
updated_at: "2026-07-09T12:00:00"
---

## 基本信息

- 身份：xxx
- ...

## 关系时间线

- [2026-06-01] 首次聊天
- [2026-06-15] 断联 15 天
- [2026-07-01] 恢复联系

## Dates

| 日期 | 地点 | 评分 |
|------|------|------|
| 2026-06-08 | 岳麓山 | 4/5 |

## Notes

- [2026-06-01] 她说喜欢猫
- [2026-06-10] 她主动分享日常

## Evaluations

- [2026-06-15] 分析：回复变慢，可能进入冷淡期
```

### 自我档案

路径：`data/facts/self/`

存放用户自己的信息和记录。

## 核心函数

### people_archive.py

| 函数 | 职责 | 参数 |
|------|------|------|
| `read_person_archive(person_id)` | 读取人物档案 | person_id |
| `write_person_archive(person_id, content)` | 覆盖写入人物档案 | person_id, content |
| `append_note(person_id, text)` | 追加备注 | person_id, text |
| `append_date(person_id, date_text, location, rating)` | 追加约会记录 | person_id, date_text, location, rating |
| `append_event(person_id, event_type, event_text)` | 追加事件记录 | person_id, event_type, event_text |
| `append_evaluation(person_id, text)` | 追加评估记录 | person_id, text |
| `sync_moments_to_archive(person_id, moments_data)` | 同步朋友圈互动到档案 | person_id, moments_data |

### failure_archive.py

| 函数 | 职责 | 参数 |
|------|------|------|
| `read_failures()` | 读取所有失败案例 | 无 |
| `write_failure(name, text)` | 记录失败案例 | name, text |

## 概念分层

事实档案严格区分两个层次：

| 层 | 内容 | 冲突优先级 | 写入工具 |
|----|------|-----------|---------|
| **事实档案** | 客观事实（她说了什么、做了什么） | 2（高） | `person_note`, `person_date`, `events_save` |
| **分析归档** | 主观判断（分析结论、评估） | 5（最低） | `person_evaluate`, `save_from_markdown` |

### 写入前自检三问

写入 `person_note` 前必须回答：

1. 这条信息是她说的/做的，还是我推断的？→ 只能写前者
2. 如果换一个 Agent 读这条信息，会得出同样的结论吗？→ 如果不会，说明掺杂了判断
3. 这条信息 3 个月后还有效吗？→ 事实是稳定的，判断会过时

### 可以写 vs 不可以写

| ✅ 可以写（客观事实） | ❌ 不可写（主观判断） |
|---------------------|---------------------|
| 她原话："我喜欢猫" | "她对我有好感，值得追" |
| 她行为："凌晨主动发消息" | "她肯定喜欢我" |
| 用户补充："上次约会很成功" | "本月表白成功率 80%" |
| 事件记录："6/1-6/15 断联 15 天" | "她已经不感兴趣了" |

## 关键设计原则

1. **只存客观事实**：事实档案不做分析，分析由 Agent 负责
2. **持久化 Markdown**：便于人类阅读和版本控制
3. **自动迁移**：支持从旧格式自动迁移到新格式
4. **时间戳刷新**：每次写入刷新 `updated_at` 字段和文件末尾的"最后更新"行
5. **事件去重**：写入事件前检查是否已存在（`_event_entry_exists`）

## 数据层优先级

```
1（最高）: 实时数据（brief/chat/metrics）
2: 事实档案（evidence: notes/dates/events）
3: 事件检测（events）
4: 公式计算（formula_*）
5（最低）: 历史分析（data/outputs/analysis/）
```

## 参考文档

- 事实档案详细文档：`readme/facts.md`
- 写入规则：`skill/mcp-rules.md#事实档案写入规则`