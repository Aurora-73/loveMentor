---
name: analysis-workflow
description: 人物分析完整流程 — 11步详细工作流（wiki_context 为主入口）
---

# 人物分析完整流程

## 流程概览

```
0: 同步 → 1: 全局视图 → 2: Wiki知识框架 → 3: 聊天记录
→ 4: 指标 → 5: 信号 → 6: 阶段 → 7: 时间线 → 8: 事实档案
→ 9: 公式参数 → 10: 公式核验 → 11: 保存报告
```

> 权威来源：`skill/mcp_index.yaml`。本文档是 YAML 的可读展开版。

---

## 第0步：同步最新消息

**工具**：`person_sync(name)` 【MCP工具】

**目的**：确保分析基于最新数据，不遗漏最近聊天。

**执行细节**：
- 耗时：约 2-5 秒
- 同步失败不阻塞分析，但会有警告提示
- 如果联系人搜不到（PERSON_NOT_FOUND）：
  1. `system_sync(meta_only=True)` → 同步联系人列表（约 1 秒）
  2. `contact_search(query)` → 搜索联系人
  3. 找到后再 `person_sync(name)`

**下一步**：第1步 `person_brief`

---

## 第1步：获取全局视图

**工具**：`person_brief(name)` 【MCP工具】

**目的**：获取身份信息、指标、事件、信号、`relationship_stage`、`recommended_wiki_queries` 的全局视图。

**执行细节**：
- 重点关注：**信号**、**relationship_stage**（关系阶段短标签）、**recommended_wiki_queries**（可直接传给 wiki_context 的查询词列表）
- 返回的 stage 和 queries 直接用作下一步 wiki_context 的参数

**下一步**：第2步 `wiki_context`

---

## 第2步：构建 Wiki 知识框架（推荐主入口，替代分散的 wiki_search+wiki_read）

**工具**：`wiki_context(queries, stage, focus)` 【MCP工具】

**目的**：一次调用构建方法论框架——合并多条查询 + 阶段过滤 + 焦点加权 + 格式化返回。

**执行细节**：
- 将第1步 `person_brief` 返回的 `recommended_wiki_queries` 传入 `queries` 参数
- 将 `relationship_stage` 传入 `stage` 参数
- 当前在看信号，设置 `focus="signals"`
- 返回：`prompt_section`（可直接嵌入推理的格式化 Markdown）+ `page_list`（命中页面列表）

**后续 Wiki 查询**：在第3-8步中，每看到新数据模式后，再次调 `wiki_context` 切换 focus：
- 看聊天 → `wiki_context(queries=["话术","推拉"], stage=阶段, focus="chat")`
- 看指标 → `wiki_context(queries=["频率法则","需求感"], stage=阶段, focus="signals")`
- 看趋势 → `wiki_context(queries=["降温","窗口"], stage=阶段, focus="risk")`

**精确钻取**：需要引用某页具体内容时，用 `wiki_read(path)` 读全文。

**下一步**：第3步 `person_chat`

---

## 第3步：获取聊天记录

**工具**：`person_chat(name, recent=200)` 【MCP工具】

**目的**：查看最近聊天记录，理解互动模式。

**执行细节**：
- 默认取最近 200 条消息
- 按日期分组，已标注"我"/"对方"
- 重点关注：互动模式、情绪变化、关键对话
- 看到聊天模式后，**再次调 wiki_context(focus="chat")** 查话术策略

**下一步**：第4步 `person_metrics`

---

## 第4步：获取指标数据

**工具**：`person_metrics(name)` 【MCP工具】

**目的**：获取15个有效指标数据，量化关系状态。

**执行细节**：
- 返回15维指标 + neediness_penalty + interaction_pattern + 动态信号
- 重点关注：
  - composite：综合分数
  - signal_level：信号等级（强窗口/中窗口/弱窗口/冷淡/无信号）
  - interaction_pattern：互动模式（lover/provider/neutral）
- 看到数值后，**再次调 wiki_context(focus="signals")** 解读指标含义

**下一步**：第5步 `person_signals`

---

## 第5步：获取信号详情

**工具**：`person_signals(name)` 【MCP工具】

**目的**：获取信号详情（IOI/冷落/窗口等）。

**执行细节**：
- 返回信号类型、强度、置信度
- 配合 Wiki 框架解读信号含义
- 需要钻取时用 `wiki_read(path)` 读对应框架全文

**下一步**：第6步 `person_stage`

---

## 第6步：关系阶段识别

**工具**：`person_stage(name)` 【MCP工具】

**目的**：识别当前关系阶段。返回的 `current_stage` 可直接传入后续 `wiki_context(stage=...)`。

**执行细节**：
- 返回阶段：初识/有基本互动/高频聊天/已约见/持续接触/暧昧推进/关系确认/冷淡/退出
- 配合 Wiki 框架理解阶段策略

**下一步**：第7步 `person_timeline`

---

## 第7步：获取时间线

**工具**：`person_timeline(name)` 【MCP工具】

**目的**：获取关系时间线，理解趋势变化。

**执行细节**：
- 返回关键节点和趋势变化
- 重点关注：关系转折点、频率变化
- 看到趋势后：**再次调 wiki_context(queries=["趋势","降温","升温窗口"], focus="risk")**

**下一步**：第8步 `person_evidence`

---

## 第8步：查阅事实档案

**工具**：`person_evidence(name)` 【MCP工具】

**目的**：查阅已记录的笔记/约会/评价等客观事实。对比历史事实与当前状态。

**执行细节**：
- 返回多个 section：timeline/evaluations/notes/dates/all
- ⚠️ evaluations 属于分析归档，优先级低于 notes/dates/events 等客观事实

**下一步**：第9步 `formula_get_params`

---

## 第9步：获取公式参数

**工具**：`formula_get_params(name)` 【MCP工具】

**目的**：获取战态公式自动计算参数。

**执行细节**：
- 返回所有公式所需的自动参数
- 包含 manual 参数提示（需人工判断的参数）

**下一步**：第10步 `formula_calc_ivi`（或其他公式）

---

## 第10步：公式核验

**工具**：`formula_calc_ivi(...)` / `formula_calc_spe(...)` / `formula_calc_ews(...)` 等 【MCP工具】

**目的**：计算量化指标，作为辅助参考视角。

**执行细节**：
- ⚠️ 公式数值只在"数据全貌"表出现一次
- ⚠️ 不机械套阈值，结合 Wiki 判断
- ⚠️ 公式结果与 Wiki 矛盾时，以 Wiki 为准

**下一步**：第11步 `save_from_markdown`

---

## 第11步：保存分析报告

**工具**：`save_from_markdown(name, markdown_text)` 【MCP工具】

**目的**：【必须】保存完整分析报告。

**执行细节**：
- 写入 `data/outputs/analysis/<name>/latest.md`
- 同时生成 `latest.yaml`（结构化数据），支持 person_compare 对比
- 报告模板见 `guide('report-template')` 或 `mcp-analysis.md`
- 报告中的策略必须引用 Wiki 条目（`[[条目名]]` 格式）
- 推荐：调 `person_save_analysis(name, stage=..., confidence=..., ...)` 补充结构化字段

---

## 报告模板

```markdown
# XX 关系分析报告

## 一、数据全貌

| 指标 | 值 | Wiki 解读 |
|------|-----|-----------|
| composite | 0.65 | 参考《频率法则》 |
| signal_level | 中窗口 | 参考《窗口识别》 |
| ... | ... | ... |

## 二、Wiki 框架诊断

基于以下 Wiki 条目分析：
- [[IOI（兴趣指标）]]
- [[窗口识别]]

## 三、策略建议

1. 短期行动：...
2. 中期策略：...
3. 长期目标：...

## 四、行动步骤

| 步骤 | 行动 | 预期效果 |
|------|------|---------|
| 1 | ... | ... |
| 2 | ... | ... |
```
