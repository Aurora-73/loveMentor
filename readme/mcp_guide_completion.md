# MCP guide 工具改进完成记录

> 完成日期：2026-07-02
> 状态：✅ 已完成并验收通过
> 目标：让纯 MCP 使用者（Claude Desktop / Cursor / Windsurf）无需阅读外部文档，仅通过 MCP 工具本身就能正确、完整地使用系统

---

## 一、改进背景

改进前的 MCP 系统是"零件箱，没有组装说明"——全部工具完整覆盖功能，但 Agent 不知道：
- 工具调用顺序和依赖关系
- 推理方法论（Wiki 主轴、公式辅助）
- 输出物规范（两文件保存、报告模板）
- 冲突裁决规则
- 操作权限分级

详细的信息差分析见 [mcp_information_gap.md](file:///E:/Code/loveMentor/readme/mcp_information_gap.md)。

## 二、设计原则

| # | 原则 | 含义 |
|---|------|------|
| 1 | **非侵入** | 不改现有工具的参数、返回格式、内部逻辑。只新增工具和增强描述 |
| 2 | **按需查** | 流程知识不塞进每个工具描述，而是集中在 guide 工具里，Agent 需要时才查 |
| 3 | **精确指导** | guide 返回的是"下一步该做什么"，不是几百页的完整文档 |
| 4 | **流程可见** | 关键工具的描述中明确指出前/后置依赖（"分析前必须先调 person_sync"） |
| 5 | **同步一致** | LoveMentor 的改进同步到 SalesCRM（exchange/ 机制） |
| 6 | **单一真相源** | guide 内容是 readme + skills 文档的精简映射，后者是权威来源 |

## 三、改进内容

### 3.1 新增 guide 工具（11 个主题）

| 主题 | 用途 |
|------|------|
| `getting-started` | 快速入门（三件事 + 三场景） |
| `workflow/analysis` | 人物分析完整流程（6步：同步→brief→Wiki→数据→公式→保存） |
| `report-template` | 8 段式分析报告模板 |
| `methodology` | 核心方法论（Wiki 主轴 + 公式辅助 + 冲突裁决 5 级优先级） |
| `rules/evidence` | 事实档案写入规则（自检三问 + 概念分层） |
| `rules/permissions` | 操作权限规范（只读/追加/覆盖/不可逆 4 级） |
| `rules/reply` | 回复构造规则（话术 + 时间线 + 对话领导） |
| `workflow/maintain` | 维持关系工作流（候选人筛选 + 消息输出） |
| `reference/sync` | 同步策略速查（3 种场景 + 范围限制） |
| `reference/formula` | 公式使用指南（含义 + 阈值 + 核验示例） |
| `reference/stickers` | 贴纸系统（镜像检测 + 标注体系） |

支持中英文别名映射（如"分析"→workflow/analysis，"report"→report-template）。

### 3.2 工具描述增强

#### P0 关键工具

| 工具 | 增强内容 |
|------|---------|
| `person_sync` | 添加 "⚠️【分析前置·必须调用】" |
| `save_from_markdown` | 添加 "⚠️【分析完成·必须调用】" |
| `events_save` | 添加 "⚠️【先扫后写】" |

#### P1 进阶工具

| 工具 | 增强内容 |
|------|---------|
| `person_brief` | 添加 "⚠️调此工具前必须先调 person_sync" |
| `person_save_analysis` | 添加 "【可选】" + evidence_refs 参数说明 |
| `maintain_list` | 添加 "详细流程见 guide('workflow/maintain')" |
| `person_evaluate` | 添加 "⚠️概念上属于分析归档，优先级低于客观事实" |
| `contact_merge` | 添加 "⚠️【必须确认】" |
| `formula_calc_*` | 添加 "【辅助参考·核验而非套用】" |

## 四、上下文预算评估

| 指标 | 改进前 | 改进后 |
|------|--------|--------|
| 工具数量 | 完整工具集 | 完整工具集 + guide |
| 工具描述总 token | ~1200（估算） | ~2000（估算） |
| 增量 | — | ~+800 tokens |

**结论**：+800 tokens 对 Agent 上下文（通常 100K-200K 窗口）影响在 1% 以内，可接受。

## 五、内容维护机制

### 触发更新条件

| # | 触发场景 | 需要更新的 guide 主题 |
|---|---------|---------------------|
| 1 | 新增 MCP 工具 | getting-started、workflow/analysis |
| 2 | 新增 Wiki 页面 | workflow/analysis（常用 Wiki 表） |
| 3 | 修改操作流程 | workflow/analysis、reference/sync |
| 4 | 修改输出规范 | report-template |
| 5 | 新增权限规则 | rules/permissions |
| 6 | SalesCRM 同步适配 | 所有主题的恋爱→销售术语替换 |

### 单一真相源关系

```
readme/*.md 和 .claude/skills/*.md  →  权威来源
                   ↓
         tools_guide.py 的 GUIDES  →  精简映射
                   ↓
         Agent 通过 guide(topic) 获取  →  按需查询
```

- guide 内容不创新，只从 readme/skills 提取最核心的部分
- readme/skills 变更时，必须检查是否影响 guide 内容
- 如果 readme 和 guide 矛盾，以 readme 为准

### 修改代码后自检清单

```
□ 这个改动是否影响现有 guide 主题的内容？
□ 如果是，更新了对应 guide 主题了吗？
□ 更新后调 guide(topic) 验证内容正确吗？
□ 需要同步到 SalesCRM 的 exchange/ 目录吗？
```

## 六、验收结果

| 验收项 | 结果 |
|--------|------|
| 工具总数 | 完整工具集 + guide ✅ |
| guide 11 主题可调用 | ✅ |
| 中文别名映射 | ✅ |
| 未知主题返回列表 | ✅ |
| P0 描述增强 | ✅ |
| P1 描述增强 | ✅ |
| 主项目测试 | 243/243 通过 ✅ |
| MCP 测试 | 16/16 通过 ✅ |
| readme/mcp.md 同步 | ✅ |

## 七、修改文件清单

| 文件 | 操作 |
|------|------|
| [tools_guide.py](file:///E:/Code/loveMentor/mcp_server/tools_guide.py) | 新建：11 主题 + 别名映射 |
| [server.py](file:///E:/Code/loveMentor/mcp_server/server.py) | 修改：注册 guide + 12 个描述增强 |
| [test_final.py](file:///E:/Code/loveMentor/mcp_server/tests/test_final.py) | 修改：48→49 + test_guide_tool |
| [readme/mcp.md](file:///E:/Code/loveMentor/readme/mcp.md) | 修改：工具数、目录、清单同步 |
| [exchange/复用矫正/guide_tool_pattern.md](file:///E:/Code/loveMentor/exchange/复用矫正/guide_tool_pattern.md) | 新建：SalesCRM 同步资产 |

## 八、SalesCRM 同步

可复用资产已存入 [exchange/复用矫正/guide_tool_pattern.md](file:///E:/Code/loveMentor/exchange/复用矫正/guide_tool_pattern.md)，包含：
- 11 个主题结构
- 术语替换表（LoveMentor→SalesCRM）
- 描述增强清单
- 验收标准

SalesCRM 同步待办记录在 [plan/issue.md](file:///E:/Code/loveMentor/plan/issue.md)。
