# Agent 层

## 概述

`engine/agent/` 是工具函数的实现层。`tools.py` 是包装层（自动解析人名 → conn/config/person），各模块文件包含实际逻辑。

## 核心文件

| 文件 | 功能 |
|------|------|
| `core.py` | 共享基础设施：`_get_conn`、`_resolve_person`、`_build_cross_refs`、`_extract_sections` 等 |
| `context.py` | `ContextBuilder` — 从数据库和文件系统组装人物上下文 |
| `response.py` | `ToolEnvelope`、`ok()`、`err()` — 统一工具返回格式（给 `chat_data`/`brief_data` 等结构化工具使用） |

## 按域拆分

| 文件 | 包含函数 | 职责 |
|------|---------|------|
| `brief.py` | `agent_brief`, `agent_brief_data` | 全局摘要视图（Markdown + 结构化数据） |
| `snapshot.py` | `_detect_personal_patterns`, `_select_important_messages`, `_generate_monthly_summary` | 摘要辅助（个人模式/消息筛选/月度统计） |
| `recommend.py` | `_recommend_wiki`, `_build_framework_recommendations` | Wiki/框架推荐 |
| `chat.py` | `agent_chat`, `agent_chat_data` | 聊天记录查询（Markdown + 结构化数据） |
| `evidence.py` | `agent_evidence` | 事实档案视图 |
| `material.py` | `agent_material_search`, `agent_material_show` | 材料搜索与阅读 |
| `write.py` | `agent_note`, `agent_date`, `agent_evaluate`, `agent_events`, `agent_save_analysis`, `agent_save_from_markdown` | 数据写入 |
| `moments.py` | `moments_stats`, `sync_moments_to_archive` | 朋友圈互动 |
| `sync_agent.py` | `agent_sync`, `sync_person` | 数据同步 |
| `report.py` | `agent_metrics`, `agent_status`, `agent_rank`, `agent_weekly`, `agent_compare_analysis` | 指标与报告 |
| `identity_ops.py` | `agent_contact`, `agent_exclude`, `agent_failure`, `agent_sticker` | 身份与排除管理 |
| `signals.py` | `_detect_signals`, `detect_manipulation_signals`, `_detect_moments_chat_signals`, `_query_signal_messages` | 信号检测 |
| `maintain.py` | `maintain_candidates`, `format_candidates`, `Candidate` | 维持关系候选人筛选 |

## 数据流

```
tools.py (包装层)
    ↓ name → (conn, config, person)
    ├→ brief.py / chat.py / evidence.py / material.py
    ├→ write.py / moments.py / sync_agent.py / report.py / identity_ops.py
    ├→ signals.py (信号检测)
    ├→ core.py (共享基础设施 + Session 连接复用)
    └→ context.py (上下文组装)
```

底层依赖：
```
engine/analyzers/   指标计算、排名、事件
engine/knowledge/   Wiki 检索
engine/facts/       事实档案读写
engine/identity/    身份解析
engine/models/      数据结构
```

## agent_chat 的 sender 标注逻辑

```python
# chat.py → agent_chat
sender = row["sender_id"] or ""
is_mine = sender == config.my_wxid
"sender": "我" if is_mine else person.display_name,
```

判定依据是 `sender_id == config.my_wxid`。如果 `my_wxid` 配置错误，所有标注都会反转。

### agent_brief 输出结构

`brief()` 返回的 Markdown 包含：
1. **事实快照**：身份、数据可信度、首末条消息时间
2. **指标**：composite 分数、信号等级、子指标表格
3. **事件**：断联/恢复/频率变化检测结果
4. **信号**：拒绝/表白/邀约/金钱/操控关键词检测
5. **Wiki 推荐**：根据信号自动推荐相关 Wiki 页面
6. **历史分析**：如果有保存过的分析结论

### agent_brief_data 结构化数据

`brief_data()` 返回 `{status, data, meta}` 信封格式，`data` 包含：

**必含字段**：
- `identity` — 身份信息（person_id, display_name, accounts）
- `message_stats` — 消息统计（total, my_count, her_count, first_ts, last_ts）
- `metrics` — 指标字典（composite, base_score, fback 等）
- `events` — 事件列表（date, event_type, detail, confidence）
- `signals` — 信号字典（rejection, confession, invitation 等）
- `recent_messages` — 最近 30 条消息
- `latest_analysis` — 最新分析结论（YAML 解析后的 dict）
- `recommendations` — 推荐（wiki 列表 + framework 列表）

**可选字段**：
- `ranking_trend` — 排名趋势
- `data_confidence` — 数据可信度水平
- `similar_failures` — 相似失败案例
- `personal_patterns` — 个人模式警告
- `moments` — 朋友圈互动（Markdown 格式）
- `fact_archive` — 事实档案全文（Markdown 格式）
- `has_archive` — 是否有事实档案

**设计原则**：`agent_brief` 内部调用 `agent_brief_data` 获取数据，只做 Markdown 格式化，不重复数据收集逻辑。

## 注意事项

1. **连接管理**：`_get_conn()` 每次打开新连接，用完必须 `conn.close()`。`tools.py` 的包装层用 `try/finally` 保证关闭。支持 `Session` 上下文管理器复用连接。
2. **person 解析失败**：`_resolve_person` 找不到人时返回 `None`，`tools.py` 包装层会抛 `ValueError("未找到联系人: XX")`。
3. **agent_chat 的 conversation_id**：通过 `person.accounts[0].conversation_id` 获取，如果一个人有多个微信账号，只用第一个。
4. **信号检测**：`agent_chat` 和 `agent_brief` 会扫描关键词检测拒绝/表白/邀约/金钱/操控信号，这些是硬编码的关键词列表，不经过 LLM。
