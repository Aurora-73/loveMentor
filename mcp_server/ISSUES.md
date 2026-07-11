# MCP Server 执行过程问题记录

## 问题列表

### 1. 网络连接失败，无法安装 fastmcp 和 pydantic
- **问题描述**：执行 `pip install fastmcp>=2.0 pydantic>=2.7` 时，连接 pypi.org 失败（WinError 10051）
- **影响**：无法验证 FastMCP API 是否可用，无法运行空服务器测试
- **状态**：已解决（用户手动完成安装）
- **实际版本**：FastMCP 3.4.2

### 2. server.py 中 from fastmcp import mcp 错误
- **问题描述**：`from fastmcp import mcp` — FastMCP 不导出 `mcp` 实例，需要 `FastMCP("LoveMentor")`
- **影响**：`ImportError: cannot import name 'mcp' from 'fastmcp'`
- **状态**：已修复
- **修复方式**：改为 `from fastmcp import FastMCP` + `mcp = FastMCP("LoveMentor")`

### 3. tools_read.py @tool 装饰器不存在
- **问题描述**：`from fastmcp import tool` 不存在，FastMCP v3.4 的 `@tool` 是实例方法
- **影响**：工具无法注册
- **状态**：已修复
- **修复方式**：tools_read.py/tools_write.py 导出纯函数，server.py 用 `mcp.tool()(...)` 注册

### 4. rank_data/status_data/wiki_search_data 在 tools.py 中不存在
- **问题描述**：MCP 计划用 `_data` 变体返回 dict，但 `rank_data`、`status_data`、`wiki_search_data` 在 tools.py 中不存在（只有返回 str 的 `rank`、`status`、`wiki_search`）
- **影响**：`ImportError` 或返回类型与计划不一致
- **状态**：已修复
- **修复方式**：在 `engine/tools.py` 中新增 3 个 `_data` 变体函数，返回 dict

### 5. tools_read.py 中 wiki_search 函数名冲突
- **问题描述**：`tools_read.py` 中定义了 `wiki_search` 函数，但同时从 `engine.tools` 导入了同名的 `wiki_search`，导致局部函数覆盖导入
- **影响**：调用 `wiki_search` 时无限递归
- **状态**：已修复
- **修复方式**：`from engine.tools import wiki_search as _wiki_search`，函数内部调用 `_wiki_search()`

### 6. wiki_search 工具未使用 wiki_search_data，limit 参数被忽略
- **问题描述**：`tools_read.py` 的 `wiki_search` 函数使用 str 版本的 `_wiki_search(query)` 而非 dict 版本的 `wiki_search_data(query, limit=limit)`，导致 `limit` 参数被完全忽略，且返回结构不符合 Phase 1 统一 dict 规范
- **发生时间**：2026-07-01
- **影响范围**：`wiki_search` MCP 工具的 `limit` 参数无效，返回 `{"results": <str>}` 而非结构化 dict
- **状态**：已修复
- **修复方式**：改为 `from engine.tools import wiki_search_data`，函数内部调用 `wiki_search_data(query, limit=limit)`
- **根因分析**：Issue #5 修复时只解决了命名冲突，未同步切换到 `_data` 变体，与 rank_data/status_data 的处理方式不一致

### 7. 返回格式不一致：ToolEnvelope vs 裸 dict（非关键）
- **问题描述**：`brief_data()` 和 `chat_data()` 返回 ToolEnvelope 格式 `{status, data, meta}`，而 `rank_data()`、`status_data()`、`wiki_search_data()` 返回裸 dict。MCP 层透传时格式不统一。
- **发生时间**：2026-07-01 冒烟测试阶段
- **影响范围**：不影响功能正确性，AI 可解析两种格式；但格式不统一可能增加 AI 解析复杂度
- **状态**：已记录（非阻断性，Phase 2 可统一）
- **临时处理措施**：冒烟测试中通过 `_unwrap()` 函数兼容两种格式
- **建议**：Phase 2 中统一所有 `_data` 函数的返回格式，要么全部用 ToolEnvelope，要么全部用裸 dict

### 8. maintain_list AttributeError（Claude 实战反馈 P0）
- **问题描述**：`maintain_list` 调用 `c.priority` 和 `c.suggested_action`，但 `Candidate` 类没有这两个字段
- **发生时间**：2026-07-01 Claude 实战测试
- **影响范围**：maintain_list 工具完全不可用
- **状态**：已修复
- **修复方式**：在 tools_read.py 中基于 `reason` 字段映射 `priority`（高/中/低）和 `suggested_action`（建议行动文本）

### 9. wiki_search 路径与 wiki_read 不一致（Claude 实战反馈 P1）
- **问题描述**：wiki_search 返回 `docs/wiki/scenarios/...`，但文件实际在 `docs/wiki/wiki/scenarios/...`（双层 wiki/）
- **发生时间**：2026-07-01 Claude 实战测试
- **影响范围**：wiki_search → wiki_read 标准流程断裂
- **状态**：已修复
- **修复方式**：修复 material.py 中 `_search_wiki` 路径拼接：`wiki/` 前缀时改为 `docs/wiki/{raw_path}` 而非 `docs/{raw_path}`

### 10. contact_merge 同人合并 + 确认逻辑缺失（Claude 实战反馈 P2）
- **问题描述**：source == target 时直接执行返回矛盾响应（success:true + message:"合并失败"）
- **发生时间**：2026-07-01 Claude 实战测试
- **影响范围**：误导性返回，AI 无法判断实际状态
- **状态**：已修复
- **修复方式**：添加同人检查（source == target 返回 SAME_PERSON 错误）+ 正确解析底层返回值判断 success

### 11. person_chat 缺乏返回上限保护（Claude 实战反馈 P3）
- **问题描述**：recent=0 或 recent=99999 返回全部消息（91k+ chars），MCP 返回超限
- **发生时间**：2026-07-01 Claude 实战测试
- **影响范围**：大返回撑爆 MCP 传输
- **状态**：已修复
- **修复方式**：添加 CHAT_MAX_RECENT=500 硬上限，超限时自动截断并标注 truncated/original_recent/applied_recent

### 12. 公式工具缺乏参数校验（Claude 实战反馈 P4）
- **问题描述**：formula_calc_ivi(sp=-1, ...) 接受负数并返回无意义结果
- **发生时间**：2026-07-01 Claude 实战测试
- **影响范围**：负数/越界值产生无意义结果
- **状态**：已修复
- **修复方式**：添加 _clamp_01/_clamp_params 函数，参数自动 clamp 到 [0,1] 并返回 param_warnings 列表

### 13. skill_search 返回 0 结果（Claude 实战反馈 P6）
- **问题描述**：skills/ 目录不存在，SkillRegistry 扫描到 0 个技能包
- **发生时间**：2026-07-01 Claude 实战测试
- **影响范围**：skill_search 功能完全不可用
- **状态**：已移除
- **修复方式**：skill_search 工具已整体删除，改用 wiki_search + .claude/skills/ 渐进式披露 skill 文件

### 14. wcd_status 语义错误（Claude 实战反馈 P8 + 用户反馈）
- **问题描述**：wcd_status 只调用 check_keys() 查密钥缓存，不检查 WCD 后端是否在线
- **发生时间**：2026-07-01 Claude 实战测试 + 用户反馈
- **影响范围**：Agent 误判 WCD 状态，同步调用失败
- **状态**：已修复
- **修复方式**：改为检查 WCD health + 密钥缓存状态，返回 online/keys_cached/message/suggestion 四字段。绝不自动调用 fetch_keys（封号风险）

### 15. test_bugfix.py wiki 路径断言过时（非关键）
- **问题描述**：test_bugfix.py::test_wiki_path 仍检查 `"docs/wiki/wiki/" not in path`，但 P1 修复后双 `wiki/` 是正确路径（文件实际在 `docs/wiki/wiki/` 下）
- **发生时间**：2026-07-01 v7.0 开发时发现
- **影响范围**：test_bugfix.py 测试失败
- **状态**：已修复
- **修复方式**：改为验证 wiki_search 返回的 path 能被 wiki_read 正确读取（用 wiki_show 读取并检查不含"文件不存在"）

### 16. test_final.py 工具数未更新 + stdin reconfigure 失败（非关键）
- **问题描述**：新增 person_stage 后工具数为 48，但 test_final.py 仍断言 47；server.py 的 `sys.stdin.reconfigure()` 在 pytest 环境下失败（stdin 被 DontReadFromInput 替换）
- **发生时间**：2026-07-01 v7.0 开发时发现
- **影响范围**：test_final.py 多个测试失败
- **状态**：已修复
- **修复方式**：更新断言为 48 + 添加 person_stage 到 P1 集合；server.py 添加 try/except 容错 stdin.reconfigure

### 17. test_final.py 缺少 tools fixture（非关键）
- **问题描述**：test_tool_categories/test_phase_distribution/test_fetch_keys_excluded 依赖 `tools` fixture，但 mcp_server/tests/ 下无 conftest.py 定义该 fixture
- **发生时间**：2026-07-01 v7.0 开发时发现
- **影响范围**：3 个测试报 ERROR（fixture not found）
- **状态**：已修复
- **修复方式**：新建 mcp_server/tests/conftest.py，定义 module 级 `tools` fixture

### 18. 事件检测对家庭成员误判 FIRST_FLIRT（非关键，已记录）
- **问题描述**：person_stage("妈") 返回"暧昧推进"阶段，因为事件检测器在母子对话中误检测到 FIRST_FLIRT 事件
- **发生时间**：2026-07-01 实际数据验证时发现
- **影响范围**：家庭成员的 person_stage 结果可能不准确
- **状态**：已记录（事件检测器的数据质量问题，非 stage_recognizer 的逻辑问题）
- **临时处理措施**：stage_recognizer 逻辑正确（有 FIRST_FLIRT 事件就判定为暧昧推进），根本修复需在 events.py 中改进 FIRST_FLIRT 检测逻辑（如排除亲属关系、增加关键词阈值等）
- **建议**：后续在 events.py 中添加亲属关系过滤或更严格的暧昧关键词匹配
