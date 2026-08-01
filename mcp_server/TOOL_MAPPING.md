# MCP 工具映射表

> 反映全部工具的最终实现状态（Phase 1 + Phase 2 + Phase 3）
> 最后更新：2026-07-01 v2

## 一、Phase 1 核心工具映射

| MCP 工具名 | engine.tools 函数 | 实际签名 | 返回类型 | 备注 |
|-----------|------------------|----------|----------|------|
| `person_brief` | `brief_data(name)` | `brief_data(name: str) -> dict` | dict | ✅ 符合预期 |
| `person_chat` | `chat_data(name, recent)` | `chat_data(name: str, *, recent: int = 50, ...) -> dict` | dict | ✅ 符合预期 |
| `person_metrics` | `metrics(name)` | `agent_metrics(name: str) -> dict | str` | dict \| str | ✅ MCP 层处理 str 错误 |
| `person_rank` | `rank_data()` | `rank_data() -> dict` | dict | ✅ 已新增 _data 变体 |
| `person_status` | `status_data(name)` | `status_data(name: str) -> dict` | dict | ✅ 已新增 _data 变体 |
| `wiki_search` | `wiki_search_data(query, limit)` | `wiki_search_data(query: str, limit: int = 5) -> dict` | dict | ✅ 已新增 _data 变体 |
| `person_note` | `note(name, content)` | `agent_note(name: str, content: str) -> str` | str | ✅ 写入工具，MCP 层包装为 dict |
| `person_date_record` | `date(name, date_text, location, rating)` | `agent_date(name: str, date_text: str, location=None, rating=None) -> str` | str | ✅ 写入工具，MCP 层包装为 dict |

## 二、Phase 2 P0 工具映射

| MCP 工具名 | engine.tools 函数 | 实际签名 | 返回类型 | 备注 |
|-----------|------------------|----------|----------|------|
| `wiki_read` | `wiki_show(path, max_chars)` | `agent_material_show(path: str, *, max_chars: int = 50000) -> str` | str | ✅ MCP 层包装为 dict |
| `wiki_context` | `wiki_context_data(queries, ...)` | `wiki_context_data(queries, task_type, stage, focus, max_chars, max_pages) -> dict` | dict | ✅ 新增·批量构建Wiki上下文 |
| `person_sync` | `sync_person(name, mode)` | `sync_person(name: str, mode: str = "incremental") -> str` | str | ✅ MCP 层包装为 dict |
| `person_save_analysis` | `save_analysis(name, **kwargs)` | `save_analysis(name, stage, confidence, reasoning, ...) -> str` | str | ✅ MCP 层包装为 dict |

## 三、Phase 2 P1 工具映射

| MCP 工具名 | engine.tools 函数 | 实际签名 | 返回类型 | 备注 |
|-----------|------------------|----------|----------|------|
| `person_timeline` | `timeline(name, max_events)` | `timeline(name: str, max_events: int = 30) -> dict` | dict | ✅ Phase 1 后补 |
| `person_signals` | `signals(name)` | `signals(name: str) -> dict` | dict | ✅ Phase 1 后补 |
| `person_evidence` | `evidence(name, section, since_date)` | `evidence(name, section="all", since_date=None) -> str` | str | ✅ MCP 层包装为 dict |
| `person_compare` | `compare_analysis(name)` | `compare_analysis(name: str) -> str` | str | ✅ MCP 层包装为 dict |
| `weekly_report` | `weekly(deep)` | `weekly(deep: bool = False) -> str` | str | ✅ MCP 层包装为 dict |
| `person_moments_stats` | `moments_stats(name)` | `moments_stats(name) -> dict | str` | dict \| str | ✅ MCP 层处理 str |
| `maintain_list` | `maintain_candidates(max_people)` | `maintain_candidates(max_people=10) -> list` | list | ✅ MCP 层包装为 dict |
| `events_scan` | `events(name, scan=False)` | `events(name, scan=False, disconnect_days=7) -> str` | str | ✅ 只读，MCP 层包装为 dict |
| `events_save` | `events(name, scan=True)` | `events(name, scan=True, disconnect_days=7) -> str` | str | ✅ 写入，MCP 层包装为 dict |
| `person_evaluate` | `evaluate(name, text)` | `evaluate(name: str, text: str) -> str` | str | ✅ 追加写入 |
| `system_sync` | `sync(mode, meta_only)` | `sync(mode="incremental", meta_only=False) -> str` | str | ✅ 写入，长耗时 |
| `wcd_status` | `check_keys()` | `check_keys() -> str` | str | ✅ 启动 WCD 后端（用缓存密钥），当前仅检查密钥状态 |

## 四、Phase 2 P2 工具映射

| MCP 工具名 | engine.tools 函数 | 实际签名 | 返回类型 | 备注 |
|-----------|------------------|----------|----------|------|
| `contact_search` | `contact(query, action="search")` | `agent_contact(query, action="search") -> str` | str | ✅ 只读 |
| `contact_alias` | `contact(query, action="alias", **kwargs)` | `agent_contact(query, action="alias", type=..., value=...) -> str` | str | ✅ 追加写入 |
| `contact_merge` | `contact(query, action="merge", merged=target)` | `agent_contact(query, action="merge", merged=...) -> str` | str | ⚠️ 不可逆，destructiveHint |
| `sticker_scan` | `sticker(action="scan")` | `agent_sticker(action="scan", private_only=True) -> str` | str | ✅ 只读，长耗时 |
| `sticker_list` | `sticker(action="list")` | `agent_sticker(action="list", limit=30, ...) -> str` | str | ✅ 只读 |
| `sticker_label` | `sticker(action="label")` | `agent_sticker(action="label", md5=..., label=...) -> str` | str | ✅ 写入 |
| `exclude_list` | `exclude(action="list")` | `agent_exclude(action="list") -> str` | str | ✅ 只读 |
| `exclude_add` | `exclude(action="add")` | `agent_exclude(action="add", name=..., reason=...) -> str` | str | ✅ 写入 |
| `exclude_remove` | `exclude(action="remove")` | `agent_exclude(action="remove", name=...) -> str` | str | ✅ 写入 |
| `failure_list` | `failure(action="list")` | `agent_failure(action="list") -> str` | str | ✅ 只读 |
| `failure_add` | `failure(action="add")` | `agent_failure(action="add", person=..., stage=..., ...) -> str` | str | ✅ 追加写入 |
| `message_context` | `message_context_data(message_ids, ...)` | `message_context_data(message_ids, before=20, after=20) -> dict` | dict | ✅ 只读 |
| `save_from_markdown` | `save_from_markdown(...)` | `save_from_markdown(...) -> str` | str | ✅ 覆盖写入 |
| `sync_moments` | `sync_moments(name)` | `sync_moments(name) -> str` | str | ✅ 追加写入 |

## 五、Phase 3 P3 公式工具映射

| MCP 工具名 | engine.formulas 函数 | 实际签名 | 返回类型 | 备注 |
|-----------|---------------------|----------|----------|------|
| `formula_get_params` | `formula_params()` | `formula_params() -> dict` | dict | ✅ 只读 |
| `formula_calc_ivi` | `formula_ivi(...)` | `formula_ivi(...) -> dict` | dict | ✅ 纯计算 |
| `formula_calc_spe` | `formula_spe(...)` | `formula_spe(...) -> dict` | dict | ✅ 纯计算 |
| `formula_calc_ews` | `formula_ews(...)` | `formula_ews(...) -> dict` | dict | ✅ 纯计算 |
| `formula_calc_is` | `formula_is(...)` | `formula_is(...) -> dict` | dict | ✅ 纯计算 |
| `formula_calc_gap_effect` | `formula_gap_effect(...)` | `formula_gap_effect(...) -> dict` | dict | ✅ 纯计算 |
| `formula_calc_eev` | `formula_eev(...)` | `formula_eev(...) -> dict` | dict | ✅ 纯计算 |
| `formula_calc_cs` | `formula_cs(...)` | `formula_cs(...) -> dict` | dict | ✅ 纯计算 |
| `formula_calc_action` | `formula_action(...)` | `formula_action(...) -> dict` | dict | ✅ 含 DB 读取 |

## 六、历史问题与解决

### 返回类型不一致问题（已解决）

计划文档 §4.1 决策「_data 变体优先，返回 dict」，原始实现中：
- `brief_data`、`chat_data` 返回 dict ✅
- `metrics` 返回 dict | str（错误时返回 str） ⚠️ → MCP 层用 `isinstance` 检查处理
- `rank`、`status`、`wiki_search` 返回 str ❌ → 新增 `_data` 变体解决

### 已新增的 _data 变体

| 函数 | 原返回 | 新增函数 | 新返回 | 位置 |
|------|--------|----------|--------|------|
| `rank` | str | `rank_data() -> dict` | dict | `engine/tools.py` |
| `status` | str | `status_data(name) -> dict` | dict | `engine/tools.py` |
| `wiki_search` | str | `wiki_search_data(query, limit) -> dict` | dict | `engine/tools.py` |

### 命名冲突问题（已解决）

| 函数 | 问题 | 解决方案 |
|------|------|---------|
| `wiki_search` | MCP 函数名和 engine.tools 导入同名，无限递归 | 改用 `wiki_search_data` 完全规避 |

## 七、🚫 永不暴露

| 函数 | 原因 |
|------|------|
| `fetch_keys` | 重启微信 + 需要手动扫码，AI 无法完成 |

## 八、统计汇总

| Phase | 只读 | 写入 | 不可逆 | 合计 |
|-------|------|------|--------|------|
| Phase 1 | 6 | 2 | 0 | 8 |
| Phase 2 P0 | 1 | 1 | 1 | 3 |
| Phase 2 P1 | 8 | 5 | 0 | 13 |
| Phase 2 P2 | 6 | 7 | 1 | 14 |
| Phase 3 P3 | 9 | 0 | 0 | 9 |
| **合计** | **31** | **15** | **2** | **48** |

> 注：`person_save_analysis` 和 `save_from_markdown` 为覆盖写入（需 confirm）；`contact_merge` 为不可逆操作（destructiveHint）。只读统计中包含 `formula_calc_action`（虽读 DB 但不写入）。
