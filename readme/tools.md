# Agent 工具详细文档

## 概述

所有工具通过 `engine/tools.py` 导入，返回 `str`（Markdown）或 `dict`（结构化数据）。工具函数是 `engine/agent/` 各模块的包装层，自动解析人名 → `(conn, config, person)`，处理连接管理和错误兜底。

## 工具契约

### 分层

工具按职责分为五层，每层有明确的返回 schema：

| 层 | 工具 | 返回类型 | 说明 |
|---|------|---------|------|
| **数据读取** | brief, chat, evidence, metrics, status, rank, wiki_search, wiki_show, moments_stats, behaviors | str 或 dict | 只读，无副作用，可安全重试 |
| **数据写入** | note, date, evaluate, events(scan=True), save_analysis, save_from_markdown | str 或 Path | 有副作用，写入 facts/outputs |
| **身份管理** | contact(alias/link/merge), exclude(add/remove), failure(add), sticker(label) | str | 修改身份目录/排除列表，merge 不可逆 |
| **计算工具** | formula_params, formula_ivi, formula_spe, formula_ews, formula_is, formula_gap_effect, formula_eev, formula_cs, formula_action | dict | 纯计算，无副作用 |
| **维持关系** | maintain_candidates, format_candidates | list[Candidate] 或 str | 候选人筛选，无副作用 |

### 返回 schema

**数据读取工具返回的 dict**（metrics, moments_stats, formula_*, behaviors_data, brief_data, chat_data）：

```python
{
    "key": value,           # 数据字段
    # 错误时返回 str 而非 dict：
    # "未找到联系人: XX"
}
```

**数据写入工具返回的 str**：成功消息（如 "已写入备注: /path/to/file.md"）或错误消息。

**错误约定**：所有工具不抛异常，错误情况返回描述性 str。调用方通过 `isinstance(result, dict)` 判断成功与否。

### 权限规范

| 操作类型 | 工具 | 是否可回滚 | Agent 行为要求 |
|---------|------|-----------|--------------|
| **只读** | brief/chat/evidence/metrics/status/rank/wiki_*/moments_stats/formula_*/behaviors | N/A | 自由调用 |
| **追加写入** | note/date/evaluate | 是（可手动编辑文件删除） | 直接执行，无需确认 |
| **覆盖写入** | save_analysis/save_from_markdown | 是（旧文件被覆盖） | 覆盖前告知用户 |
| **检测写入** | events(scan=True) | 是（可从档案删除） | 先展示检测结果，再写入 |
| **身份变更** | contact(alias/link) | 是（可撤销） | 直接执行 |
| **不可逆操作** | contact(merge) | 否 | **必须向用户确认后再执行** |
| **排除操作** | exclude(add) | 是（可 remove） | 直接执行，告知原因 |
| **同步** | sync/sync_person | 否（数据已入库） | 直接执行，报告结果 |
| **周报** | weekly | 否（快照已保存） | 直接执行 |

---

## 工具完整列表

### 数据获取（只读）

| 工具 | 参数 | 返回 | 用途 |
|------|------|------|------|
| `brief(name, compact=False)` | 名字 | str | 全局视图：事实+指标+事件+信号+Wiki推荐 |
| `brief_data(name)` | 名字 | dict | 结构化摘要（identity/metrics/events/signals/recent_messages），Agent 内部分析用 |
| `chat(name, recent=50, from_date=None, to_date=None, keyword=None, context_lines=0)` | 名字+过滤 | str | 聊天记录（按日期分组，人类阅读） |
| `chat_data(name, recent=50, from_date=None, to_date=None, keyword=None, context_lines=0)` | 名字+过滤 | dict | 结构化聊天查询，Agent 内部分析用 |
| `message_context_data(message_ids, before=20, after=20)` | 消息ID列表 | dict | 根据消息 ID 获取前后上下文（不跨会话） |
| `evidence(name, section="all", since_date=None)` | 名字+section | str | 事实档案（timeline/evaluations/notes/dates/all） |
| `metrics(name)` | 名字 | dict | 全部指标数据（composite/信号等级/指标/动态信号） |
| `status(name)` | 名字 | str | 详细指标状态（格式化表格） |
| `rank()` | 无 | str | 全部联系人排名表 |
| `rank_data()` | 无 | dict | 结构化排名数据 |
| `status_data(name)` | 名字 | dict | 结构化状态数据 |
| `wiki_search(query)` | 关键词 | str | 跨 Wiki/Analysis/KB 搜索 |
| `wiki_search_data(query, limit=5)` | 关键词 | dict | 结构化 Wiki 搜索 |
| `wiki_context_data(queries, ...)` | 查询列表 | dict | 批量 Wiki 上下文检索（最多 5 条查询） |
| `wiki_show(path, max_chars=50000)` | 文件路径 | str | 安全读取材料文件全文 |
| `moments_stats(name)` | 名字 | dict | 朋友圈互动统计（双向点赞/评论/比例） |
| `timeline(name, max_events=30, categories=None)` | 名字 | dict | 关系事件时间线 |
| `signals(name)` | 名字 | dict | 信号检测（拒绝/表白/邀约/金钱/操控） |
| `stage_data(name)` | 名字 | dict | 关系阶段状态 |
| `behaviors(name, window_days=30, source="macbert", model="b2", target_role="her")` | 名字+窗口+来源+模型+视角 | str | 语义行为分析报告（10维标签+派生指标，默认 B2 her-side） |
| `behaviors_data(name, window_days=30, source="macbert", model="b2", target_role="her")` | 名字+窗口+来源+模型+视角 | dict | 结构化语义数据（标签均值/派生指标/窗口序列） |
| `turn_stats(name, window_days=30)` | 名字+窗口 | str | 互动轮次统计（self/other 轮次分布、发起频率、回复延迟、未响应 cue，零模型依赖） |

### 语义分析参数说明

`behaviors()` / `behaviors_data()` 的 `model` 和 `target_role` 参数：

| 参数 | 可选值 | 说明 |
|------|--------|------|
| `model` | `"b2"`（默认） | B2 role-aware 模型，默认生产模型 |
| `model` | `"b0"` | B0' roleless 回退基线 |
| `target_role` | `"her"`（默认） | 分析对方行为 |
| `target_role` | `"me"` | 分析本人行为（只在 SELF/OTHER 对比中使用，不单独输出） |

`source` 参数：`"macbert"`（默认，MacBERT ONNX 模型）| `"rule"`（规则 baseline，词典匹配）

### 数据写入

| 工具 | 参数 | 返回 | 用途 |
|------|------|------|------|
| `note(name, text)` | 名字+内容 | str | 添加备注到事实档案 |
| `date(name, date_text=None, location=None, rating=None)` | 名字+约会信息 | str | 记录约会 |
| `evaluate(name, text)` | 名字+评估 | str | 记录主观评估 |
| `events(name, scan=False, disconnect_days=7)` | 名字 | str | 检测关系事件（scan=True 写入档案） |
| `save_analysis(name, ...)` | 分析结果 | str | 保存分析结论到 YAML（支持 evidence_refs/metric_snapshot/data_window） |
| `save_from_markdown(name, markdown_text)` | 名字+Markdown | str | 从结构化 Markdown 保存分析 |
| `contact(query, action="search", **kwargs)` | 名字+操作 | str | 身份目录（search/show/alias/link/merge/audit） |
| `exclude(action="list", **kwargs)` | 操作 | str | 排除管理（list/add/remove） |
| `failure(action="list", **kwargs)` | 操作 | str | 失败案例（list/add） |
| `sticker(action="list", **kwargs)` | 操作 | str | 贴纸管理（scan/list/label） |

### 同步和周报

| 工具 | 参数 | 返回 | 用途 |
|------|------|------|------|
| `sync(mode="incremental", session_id=None, meta_only=False)` | 模式 | str | 数据同步（**默认增量**）。meta_only=True 只同步联系人/会话 |
| `sync_person(name, mode="incremental", transcribe_mode="async")` | 名字+转写模式 | str | 按人名同步（**默认增量**，只拉该联系人的最新消息）。`transcribe_mode` 控制语音/图片转写：`async`（默认，后台异步）、`sync`（同步等待）、`off`（不转写）。详见 [importers.md 语音/图片转写机制](./importers.md#语音图片转写机制) |
| `sync_moments(name)` | 名字 | str | 同步朋友圈互动到事实档案 |
| `weekly(deep=False)` | 是否深度 | str | 生成周报（排名快照 + Markdown） |
| `compare_analysis(name)` | 名字 | str | 对比 latest 和 previous 分析结论 |

### 辅助参考工具（公式）

> 公式是 chat-skills 遗产的独立体系，标注 Wiki 依据做软关联。Agent 核验而非套用阈值。

| 工具 | 参数 | 返回 | 用途 |
|------|------|------|------|
| `formula_params(name, conn=None)` | 名字+可选连接 | dict | 自动计算全部可量化参数 |
| `formula_ivi(sp, fback, user_investment, pface)` | 参数 | dict | 意图真实度（参考视角） |
| `formula_spe(user_ddepth, target_ddepth, target_latency, user_latency)` | 参数 | dict | 社交势能（参考视角） |
| `formula_ews(gap_effect, cp_index, eev, scarcity_loss)` | 参数 | dict | 升温窗口期（参考视角） |
| `formula_is(backstage, pface)` | 参数 | dict | 真实亲密度（参考视角） |
| `formula_gap_effect(act, exp)` | 参数 | dict | 情绪落差（参考视角） |
| `formula_eev(p_succ, escalation_bonus, p_fail, power_drop_risk)` | 参数 | dict | 升温期望值（参考视角） |
| `formula_cs(internal_d, external_r)` | 参数 | dict | 矛盾状态（参考视角） |
| `formula_action(ivi, spe, ews, cs=0.0, ev=0.5)` | 参数 | dict | 终极决策（参考视角） |

### 维持关系

| 工具 | 参数 | 返回 | 用途 |
|------|------|------|------|
| `maintain_candidates(max_people=10)` | 最多人数 | list[Candidate] | 筛选需要维持关系的候选人（热度下降/窗口未推进/高潜力） |
| `format_candidates(candidates)` | 候选人列表 | str | 格式化为 Markdown（含上次消息摘要、消息建议规则） |

### 密钥管理

| 工具 | 参数 | 返回 | 用途 |
|------|------|------|------|
| `check_keys()` | 无 | str | 检查微信数据库密钥状态 |
| `fetch_keys(wechat_install_path=None)` | 安装路径 | str | 提取微信数据库密钥 |

---

## Wiki 返回契约

**wiki_search 返回**：Markdown 格式的搜索结果列表，每条包含：
- 标题 + 类型（entity/scenario/topic/synthesis/source）
- 匹配原因 + 相关度评分
- 文件路径
- 匹配的关键词

**wiki_show 返回**：文件全文（Markdown），截断到 max_chars。路径越界或文件不存在时返回错误消息。

---

## 常见用法

### 分析一个联系人

```python
from engine.tools import brief, behaviors, metrics, timeline

# 1. 全局视图
print(brief("姓名"))

# 2. 语义行为分析（默认 B2 her-side）
print(behaviors("姓名"))

# 3. 结构化指标
data = metrics("姓名")
print(data["composite"], data["signal_level"])

# 4. 事件时间线
print(timeline("姓名"))
```

### 聊天记录分析

```python
from engine.tools import chat, chat_data, message_context_data

# 人类阅读
print(chat("姓名", recent=100))

# 结构化查询（Agent 内部）
data = chat_data("姓名", from_date="2026-06-01", keyword="周末")

# 消息上下文
ctx = message_context_data(["msg_id_1", "msg_id_2"], before=20, after=20)
```

### 保存分析结论

```python
from engine.tools import save_analysis

result = save_analysis(
    "姓名",
    summary="互动降温，对方回复频率下降",
    stage="冷淡/停滞",
    evidence_refs=["2026-06-15 对方未回复邀约"],
    metric_snapshot={"composite": 0.28, "signal_level": "冷淡"},
)
```

## 参考文档

- `readme/PROJECT.md` — 项目总览（含工具列表摘要）
- `readme/agent.md` — Agent 工具实现层文档（工具分层、返回 schema、权限规范）
- `readme/mcp.md` — MCP 服务器文档（49 个工具清单、配置方法）
- `ml/MODEL_USAGE.md` — 语义分析模型使用文档（B0'/B2 双模型架构）
