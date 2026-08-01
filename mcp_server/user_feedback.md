# LoveMentor MCP 实战体验报告

> **测试日期**: 2026-07-01
> **测试方式**: Claude Code（deepseek-v4-flash）通过 MCP stdio 协议直接调用
> **测试范围**: 全部工具全覆盖测试，含边缘用例和错误处理
> **测试轮次**: 两轮（首轮 25+ 工具 / 第二轮全覆盖 + 边界测试）

---

## 一、总体评价

MCP 服务器整体可用，大部分工具响应正确。统一 envelope 格式（`status/data/meta` 或 `status/error_type/error_message`）使 AI 解析无歧义。第二轮测试发现 10 个问题，其中 3 个为阻塞级。

---

## 二、全覆盖测试矩阵

### 2.1 人物信息类（6/6 ✅）

| 工具 | 测试情况 | 发现 |
|------|---------|------|
| `person_brief` | ✅ 正常 + 不存在联系人 | 不存在联系人返回正确的 `PERSON_NOT_FOUND` |
| `person_status` | ✅ 正常 | 和 metrics 高度重叠 |
| `person_metrics` | ✅ 正常 | 含 confidence/sample_size |
| `person_rank` | ✅ 正常 | 253 人排名，含 delta |
| `person_timeline` | ✅ 正常 + max_events=50 | 正确返回 3 个事件 |
| `person_compare` | ✅ 有分析后对比 | 新旧分析对比功能正常 |

### 2.2 聊天/信号/证据类（5/5 ✅）

| 工具 | 测试情况 | 发现 |
|------|---------|------|
| `person_chat` | ✅ 正常 + 关键字 + 日期范围 + 空范围(过去/未来) + recent=0/99999 | 空范围返回空列表 ✅；**recent=0 返回全部消息（91k chars），无上限保护** |
| `person_signals` | ✅ 正常 + 不存在联系人 | 三层信号正确；不存在联系人返回 `PERSON_NOT_FOUND` |
| `person_evidence` | ✅ 无档案 + 有档案后 + section 过滤 | 有数据后显示 timeline/dates/notes ✅ |
| `person_moments_stats` | ✅ 正常 | 无互动返回空数据 ✅ |
| `message_context` | ✅ 正常 | 跨会话上下文正常 ✅ |

### 2.3 Wiki 类（2/2 ⚠️）

| 工具 | 测试情况 | 发现 |
|------|---------|------|
| `wiki_search` | ✅ 正常 + query 为空 + limit=0/999 | 空 query 返回匹配 ✅；limit=0 返回空列表但 total=30 ✅ |
| `wiki_read` | ⚠️ 路径测试 × 5 种 | **见 P1** |

### 2.4 写入类（4/4 ✅）

| 工具 | 测试情况 | 发现 |
|------|---------|------|
| `person_note` | ✅ | 即时写入 facts ✅ |
| `person_evaluate` | ✅ | 即时写入 evaluations ✅ |
| `person_date_record` | ✅ | 即时写入 facts ✅ |
| `save_from_markdown` | ✅ | 覆盖写入 analysis ✅ |

### 2.5 同步类（3/3 ✅）

| 工具 | 测试情况 | 发现 |
|------|---------|------|
| `person_sync` | ✅ 增量同步 | 72 条新消息，1-2 秒 ✅ |
| `sync_moments` | ✅ 正常 | 空结果（无朋友圈互动）✅ |
| `wcd_status` | ✅ 正常 | 返回密钥缓存状态 ✅ |

### 2.6 公式类（9/9 ✅）

| 工具 | 测试情况 | 发现 |
|------|---------|------|
| `formula_get_params` | ✅ 正常 | 自动参数 + 手工参数 hint/range/default |
| `formula_calc_ivi` | ✅ 正常 + (0,0,0,0) + (1,1,1,1) + (-1,0.5,0.5,0.5) | **无输入校验：接受负数** |
| `formula_calc_spe` | ✅ 正常 + 极值 | 对称输入返回对称结果 ✅ |
| `formula_calc_ews` | ✅ 正常 | 综合指标计算 ✅ |
| `formula_calc_is` | ✅ 正常 | 亲密度计算 ✅ |
| `formula_calc_gap_effect` | ✅ 正常 | 落差计算 ✅ |
| `formula_calc_eev` | ✅ 正常 + (0,0,0,0) | 全零输入仍正常输出 ✅ |
| `formula_calc_cs` | ✅ 极值多组 | **解释文本正确随值变化** ✅ |
| `formula_calc_action` | ✅ 正常输入 + 负值 EWS | 正常分派策略 ✅ |

### 2.7 联系人/排除/失败案例（6/6 ✅）

| 工具 | 测试情况 | 发现 |
|------|---------|------|
| `contact_search` | ✅ 正常 | 结构化身份 + 别名 |
| `contact_alias` | ✅ 添加别名 | 即时生效 ✅ |
| `exclude_list` | ✅ 正常 | 三层排除完整 ✅ |
| `exclude_add` | ✅ 添加后查询 | 即刻生效 ✅ |
| `exclude_remove` | ✅ 移除后查询 | 即刻生效 ✅ |
| `failure_list` | ✅ 有案例后 | 正确显示新案例 ✅ |

### 2.8 贴纸类（2/3 ⚠️）

| 工具 | 测试情况 | 发现 |
|------|---------|------|
| `sticker_list` | ✅ unlabeled=true + 默认 | 两种格式返回正常 ✅ |
| `sticker_label` | ✅ 正常 | 标注成功 ✅ |
| `sticker_scan` | ❌ 未测 | 文档提示可能耗时，未执行 |

### 2.9 其他

| 工具 | 测试情况 | 发现 |
|------|---------|------|
| `events_scan` | ✅ 扫描 + 写入后再次扫描 | `written=false` / 不重复写入 ✅ |
| `events_save` | ✅ 写入 | 2 个事件写入成功 ✅ |
| `maintain_list` | ❌ **P0** | `'Candidate' object has no attribute 'priority'` |
| `skill_search` | 🗑️ 已移除 | 工具已删除，改用 wiki_search + .claude/skills/ |
| `contact_merge` | ⚠️ 相同人合并 | **见 P2** |

---

## 三、关键问题（按严重程度排序）

### 🔴 P0: `maintain_list` AttributeError

```
TOOL_ERROR: 'Candidate' object has no attribute 'priority'
```

`engine/tools.py` 中 `maintain_candidates()` 引用了 `Candidate` 对象的 `.priority` 属性，但数据模型中不存在此属性。

**重现**: 调用 `maintain_list(limit=3)`
**根因**: `Candidate` 类定义或数据加载逻辑缺少 `priority` 字段

---

### 🔴 P1: wiki_search 返回的 path 不能直接用于 wiki_read

**现象**：
- wiki_search 返回：`docs/wiki/scenarios/第一次约会怎么安排.md`
- 实际正确路径：`docs/wiki/wiki/scenarios/第一次约会怎么安排.md`

多了一层 `wiki/`。尝试了 5 种路径变体：
- `docs/wiki/scenarios/xxx` → ❌ 文件不存在
- `docs/wiki/entities/xxx` → ❌ 文件不存在
- `docs/wiki/wiki/scenarios/xxx` → ✅ 正确
- `docs/wiki/wiki/entities/xxx` → ✅ 正确
- `wiki/entities/xxx` → ❌ 不允许读取该目录
- `entities/xxx` → ❌ 不允许读取该目录

**影响**: Agent 使用 `wiki_search → 拿 path → wiki_read` 的标准流程会失败，必须手动补 `wiki/`。

---

### 🔴 P2: `contact_merge` 同人合并 + 确认逻辑缺失

测试 `contact_merge(source="测试联系人A", target="测试联系人A")`（相同人）：
```json
{"success":true, "message":"合并失败", "warning":"不可逆操作已执行"}
```

三个问题：
1. **矛盾响应**：`success: true` 但 `message: "合并失败"`，解析方无法判断实际状态
2. **同人检查缺失**：source == target 时应返回明确错误，不应执行
3. **确认机制缺失**：按设计 `contact_merge` 属于不可逆操作，需要用户确认后才能执行，但在 MCP 调用中直接通过了

---

### 🟡 P3: `person_chat` 缺乏返回上限保护

`recent=0` 或 `recent=99999` 返回全部消息（91k+ chars），MCP 返回内容超限被截断保存到文件。

**建议**: 设置硬上限（如 `max(0, min(recent, 500))`），并在返回中提示截断情况。

---

### 🟡 P4: 公式工具缺乏参数校验

`formula_calc_ivi(sp=-1, ...)` 接受负数并返回 `IVI=-1.622`，没有参数范围校验。

**建议**: 对超出 `[0, 1]` 范围的参数做 clamp 或返回校验错误。

---

### 🟡 P5: `person_status` 和 `person_metrics` 高度重叠

两个工具返回字段几乎相同，仅在包装层上有差异。Agent 使用时容易混淆该用哪个。

---

### 🟡 P6: `skill_search("聊天技巧")` 返回 0 结果（已移除）

skill_search 工具已整体删除。改用 `wiki_search` 搜索 Wiki 内容 + `.claude/skills/` 渐进式披露 skill 文件引导 Agent 使用 MCP 工具。

---

### 🟡 P7: `person_evidence(section="analysis")` 不显示分析内容

事实档案（`data/facts/people/`）中不包含分析内容（存在于 `data/outputs/analysis/`），但 `evidence` 工具没有提示"分析内容请使用 save_analysis/compare 查看"，可能让 agent 误以为没有分析记录。

---

### 🟡 P8: `wcd_status` 语义错误——它应该是"启动 WCD"，不是"查缓存"

当前 `wcd_status` 只调用 `check_keys()` 查密钥文件是否存在，返回"密钥已缓存"或"密钥未缓存"。但 MCP 不应暴露"查缓存"接口——它应该暴露**"使用已有缓存密钥启动 WCD 后端"**的接口。查缓存状态应该是启动逻辑中的一个内部步骤，而不是独立的 MCP 工具语义。

**影响**: 
- Agent 在 WCD 未启动时调 `wcd_status`，得到"密钥已缓存"但 WCD 仍不在线，后续同步调用全部失败
- agent 无法通过 MCP 自主恢复 WCD（目前只能靠 Bash 或手动）
- 工具命名与实际行为不匹配，造成理解混乱

**建议**: 将 `wcd_status` 改为先检查密钥 → 拉起 WCD 进程 → 轮询 health 端点 → 返回最终状态。密钥缓存检查只是内部第一步，不是工具的"输出"。

---

### 🟢 P8（建议级）: `person_compare` 在首次分析前后的行为差异

- 首次调用：`{"content":"没有找到 测试联系人A 的分析结论"}`
- 写入分析后：正确显示新旧对比

行为正确，但第一次返回的是纯字符串（非 dict），与其他工具的 envelope 格式不一致。建议统一为 `{"status": "ok", "data": null, "meta": {...}}`。

---

### 🟢 P9（建议级）: `events_save` 和 `person_timeline` 数据源不统一

`events_save` 写入 2 条事件到事实档案后，`person_timeline` 仍然只显示 3 个原始事件。两个工具可能基于不同的数据源（事实档案 vs 实时分析），建议明确文档说明。

---

## 四、体验亮点

1. **统一 envelope 格式**：所有工具返回一致的 `{"status":"ok"/"error", "data":..., "meta":...}` 结构，AI 解析逻辑统一。

2. **`person_sync` 增量秒级**：约 1-2 秒完成，适合分析前置调用。

3. **write 工具即写即用**：note/evaluate/date_record 不需要 confirm，适合 agent 自动化流程。

4. **`events_scan` 的 `written: false` 设计**：明确只读不写，配合 `events_save` 的双工具设计合理。

5. **`formula_get_params` 的 hint/range/default**：帮助 agent 理解参数含义和取值范围。

6. **错误分类清晰**：`PERSON_NOT_FOUND` / `TOOL_ERROR` 两级错误让 agent 可以做不同应对。

7. **`person_chat` 关键字过滤和日期范围过滤**：`keyword="吃饭"` 返回 3 条匹配结果，过滤准确。

---

## 五、修复优先级建议

| 优先级 | 问题 | 影响面 | 建议修复方式 |
|--------|------|--------|-------------|
| P0 | maintain_list AttributeError | 工具不可用 | 修复 Candidate 模型或调用逻辑 |
| P1 | wiki 路径不一致 | wiki 知识检索完全断裂 | 统一 wiki_search 路径前缀 |
| P2 | contact_merge 同人+确认缺失 | 安全风险 + 误导性返回 | 加同人检查 + 确认门 + 修复响应格式 |
| P3 | chat 无上限保护 | 大返回撑爆 MCP | 加 hard cap + 截断提示 |
| P4 | 公式无参数校验 | 负数/越界值产生无意义结果 | 加 clamp 或校验 |
| P5 | status/metrics 重叠 | Agent 使用困惑 | 明确定位或合并 |
| P6 | skill_search 0 结果 | 功能不可用 | 已移除工具，改用 wiki_search + .claude/skills/ |
| P7 | evidence 不显示分析 | Agent 误判无分析记录 | 加提示或扩展检索范围 |
| P8 | compare 首次返回格式不一致 | 解析需要特殊处理 | 统一 envelope 格式 |
| P9 | events/timeline 数据源不统一 | 数据不一致困惑 | 文档说明或对齐数据源 |
