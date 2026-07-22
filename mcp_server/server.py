"""MCP 服务器入口。

使用 FastMCP 在 stdio 上提供工具服务。
"""

import sys

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
        sys.stdin.reconfigure(encoding='utf-8')
    except (AttributeError, ValueError):
        # stdin 可能在测试环境下被替换（DontReadFromInput），忽略
        pass

import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

from fastmcp import FastMCP

from mcp_server import tools_read, tools_write, tools_formula, tools_guide, tools_config, tools_workflow, tools_live, tools_wechat, tools_avatar
from mcp_server import tools_thread, tools_schedule, tools_profile, tools_date, tools_replies
from mcp_server import tools_notify, tools_priority, tools_override

mcp = FastMCP("LoveMentor")

# ── 注册 guide 工具（使用指南和工作流文档）──────────────────────

mcp.tool(
    name="guide",
    description="获取 LoveMentor MCP 使用指南和工作流文档。Agent 在不确定操作流程时调用。"
               "主题：getting-started（快速入门）/ workflow/analysis（分析流程）/ "
               "report-template（报告模板）/ methodology（方法论）/ "
               "rules/evidence（事实写入规则）/ rules/permissions（权限规范）/ "
               "rules/reply（回复构造规则）/ workflow/maintain（维持关系）/ "
               "reference/sync（同步策略）/ reference/formula（公式指南）/ "
               "reference/stickers（贴纸系统）/ reference/wechat（微信发消息工具）",
    annotations={"readOnlyHint": True},
)(tools_guide.guide_func)

# ── 注册工作流导航工具（Skill-MCP 融合）──────────────────────────

mcp.tool(
    name="skill_map",
    description="【Skill-MCP 融合】查询工具与 Skill 的双向映射关系。"
               "输入工具名返回下一步建议和 Skill 参考；不输入则返回所有工具的映射概览。"
               "示例：skill_map('person_brief') → 显示下一步建议和对应 Skill 页面",
    annotations={"readOnlyHint": True},
)(tools_workflow.skill_map)

mcp.tool(
    name="workflow_step",
    description="【Skill-MCP 融合】按步骤执行工作流，返回下一步指引。"
               "工作流：analysis（人物分析）/ emergency_reply（紧急回复）/ weekly（周报）/ maintain（维持关系）。"
               "示例：workflow_step('analysis') → 显示分析流程概览；workflow_step('analysis', 0) → 获取第0步详情",
    annotations={"readOnlyHint": True},
)(tools_workflow.workflow_step)

# ── 注册配置工具（后端切换，不重启即可生效）───────────────────────

mcp.tool(
    name="get_backend",
    description="查看当前数据后端配置（wcd/weflow）",
    annotations={"readOnlyHint": True},
)(tools_config.get_backend)

mcp.tool(
    name="set_backend",
    description="切换数据后端（wcd 或 weflow），可选同时更新 base_url 和 token。写入 config.yaml 后即时生效，不需要重启 MCP Server",
)(tools_config.set_backend)

# ── 注册只读工具 ──────────────────────────────────────────────

mcp.tool(
    name="person_brief",
    description="获取人物简要信息（身份/消息统计/指标/事件/信号/最近消息/Wiki推荐/relationship_stage/recommended_wiki_queries）。"
               "⚠️调此工具前必须先调 person_sync 同步最新消息。"
               "看到信号后，将 recommended_wiki_queries + relationship_stage 传给 wiki_context 建立方法论框架。"
               "详见 guide('workflow/analysis')",
    annotations={"readOnlyHint": True},
)(tools_read.person_brief)

mcp.tool(
    name="person_chat",
    description="获取人物聊天记录（按日期分组，已标注'我'/'对方'名字）。"
               "重要：默认 recent=30 只返回最近 30 条，查特定时间段必须传 from_date/to_date（格式 YYYY-MM-DD 或 YYYY-MM-DD HH:MM）。"
               "查某天某时段用 from_date='2026-07-21 06:00' to_date='2026-07-21 06:53'；查整天用 from_date='2026-07-21' to_date='2026-07-21'。"
               "看到聊天模式后调 wiki_search 找话术策略。详见 guide('workflow/analysis')",
    annotations={"readOnlyHint": True},
)(tools_read.person_chat)

mcp.tool(
    name="person_metrics",
    description="获取人物关系指标（回复率、回复速度、情绪评分等）。"
               "看到数值后调 wiki_search 解读指标含义。详见 guide('workflow/analysis')",
    annotations={"readOnlyHint": True},
)(tools_read.person_metrics)

mcp.tool(
    name="person_rank",
    description="获取所有人的关系热度排名。对感兴趣的人调 person_brief 获取详情",
    annotations={"readOnlyHint": True},
)(tools_read.person_rank)

mcp.tool(
    name="person_status",
    description="获取人物状态概览。如需详细数据调 person_metrics",
    annotations={"readOnlyHint": True},
)(tools_read.person_status)

mcp.tool(
    name="wiki_search",
    description="【推理第一依据】搜索 Wiki 知识库（恋爱知识、技巧、场景应对策略）。Agent 推理的方法论主轴，应优先调用。"
               "找到条目后用 wiki_read 读全文。详见 guide('methodology')",
    annotations={"readOnlyHint": True},
)(tools_read.wiki_search)

# ── Phase 2 P0: wiki_read ────────────────────────────────────

mcp.tool(
    name="wiki_read",
    description="【推理第一依据】读取 Wiki 页面完整正文（wiki_search 找到路径后用此工具读全文）。Agent 推理的方法论主轴。"
               "读完后结合 person_chat/person_metrics 验证框架。详见 guide('methodology')",
    annotations={"readOnlyHint": True},
)(tools_read.wiki_read)

# ── wiki_context（推荐主入口）───────────────────────────────────

mcp.tool(
    name="wiki_context",
    description="【推荐·Wiki 主入口】批量构建 Wiki 知识上下文。传入多条查询 + 当前关系阶段 + 分析焦点，"
               "一次返回格式化 prompt 段落（合并去重+阶段加权+预算裁剪）。"
               "替代分析流程中多次 wiki_search+wiki_read 的重复调用。"
               "参数：queries（查询列表，最多5条，超出自动截断）/ task_type（reply/meet/ask/analyze，默认analyze）/ "
               "stage（关系阶段，从 person_brief 的 relationship_stage 或 person_stage 的 current_stage 获取）/ "
               "focus（signals/strategy/risk/date/chat）/ max_chars（默认8000）/ max_pages（默认8）。"
               "返回：prompt_section（可直接嵌入推理的 Markdown 段落）+ meta + page_list。"
               "注意：wiki_search+wiki_read 保留用于精确单页钻取，wiki_context 是批量建框架的主入口。",
    annotations={"readOnlyHint": True},
)(tools_read.wiki_context)

# ── 注册写入工具 ──────────────────────────────────────────────

mcp.tool(
    name="person_note",
    description="添加人物备注到事实档案",
)(tools_write.person_note)

mcp.tool(
    name="person_date_record",
    description="记录约会信息",
)(tools_write.person_date_record)

# ── Phase 2 P0: sync_person + save_analysis ──────────────────

mcp.tool(
    name="person_sync",
    description="⚠️【分析前置·必须调用】增量同步单个人最新消息。分析任何人之前必须先调此工具，否则看到的是旧数据。"
               "一般几秒完成。同步后调 person_brief 获取全局视图，或调 workflow_step('analysis') 查看下一步。"
               "如果联系人搜不到，改用 system_sync(meta_only=True)。"
               "可选参数 transcribe_mode 控制语音/图片转写："
               "async（默认，后台异步转写，不阻塞同步，下次查询可见）、"
               "sync（同步等待转写完成，耗时长）、off（不转写）",
)(tools_write.person_sync)

mcp.tool(
    name="person_save_analysis",
    description="⚠️【覆盖写入·可选】保存结构化分析到 YAML（用于 person_compare 对比）。"
               "覆盖 latest.yaml，旧版本自动转为 previous.yaml，同时 history/ 目录保留带时间戳的历史副本。"
               "返回 previous_info（被覆盖的旧版本路径/大小/生成时间）和 changed_fields（本次变更字段），调用方可据此告知用户。"
               "如需保存完整 Markdown 报告请用 save_from_markdown。"
               "参数：stage（阶段）/ confidence（置信度 0-1）/ reasoning（推理过程）/ diagnosis（诊断）/ "
               "strategy（策略）/ risks（风险列表）/ signals（信号列表）/ "
               "evidence_refs（证据引用: message_id+quote+note）/ metric_snapshot（指标快照）/ data_window（数据窗口）",
)(tools_write.person_save_analysis)

# ── Phase 2 P1: 只读工具 ──────────────────────────────────────

mcp.tool(
    name="person_timeline",
    description="获取关系时间线（关键事件按时间排列）",
    annotations={"readOnlyHint": True},
)(tools_read.person_timeline)

mcp.tool(
    name="person_signals",
    description="获取信号详情（基础信号 + 操控信号 + 朋友圈联动信号）。"
               "看到信号类型后用 wiki_read 读取对应框架全文。详见 guide('workflow/analysis')",
    annotations={"readOnlyHint": True},
)(tools_read.person_signals)

mcp.tool(
    name="person_evidence",
    description="获取事实档案（已记录的笔记、评价、约会等客观事实）。"
               "对比历史事实与 Wiki 框架判断当前状态。详见 guide('rules/evidence')",
    annotations={"readOnlyHint": True},
)(tools_read.person_evidence)

mcp.tool(
    name="person_stage",
    description="关系阶段自动识别（基于指标+事件推断当前阶段，给出推进信号和阻碍）。"
               "看到阶段后调 wiki_search 找阶段策略。详见 guide('workflow/analysis')",
    annotations={"readOnlyHint": True},
)(tools_read.person_stage)

mcp.tool(
    name="person_compare",
    description="对比 latest 和 previous 分析的变化趋势",
    annotations={"readOnlyHint": True},
)(tools_read.person_compare)

mcp.tool(
    name="weekly_report",
    description="生成周报（本周关系维护总结）",
    annotations={"readOnlyHint": True},
)(tools_read.weekly_report)

mcp.tool(
    name="person_moments_stats",
    description="获取朋友圈互动统计",
    annotations={"readOnlyHint": True},
)(tools_read.person_moments_stats)

mcp.tool(
    name="maintain_list",
    description="获取需要维持关系的候选人列表。拿结果后对每人调 person_brief/person_chat/person_metrics 获取详情，输出具体可发送的消息。详细流程见 guide('workflow/maintain')",
    annotations={"readOnlyHint": True},
)(tools_read.maintain_list)

# ── Phase 2 P1: events 拆分 ───────────────────────────────────

mcp.tool(
    name="events_scan",
    description="扫描关系事件（只读，不写入）",
    annotations={"readOnlyHint": True},
)(tools_read.events_scan)

mcp.tool(
    name="events_save",
    description="检测并写入关系事件到事实档案（一步完成检测+写入）。"
               "建议先调 events_scan 展示结果供用户确认，但非强制——直接调用本工具会自动检测并写入。"
               "disconnect_days 控制断联判定阈值（默认 7 天）",
)(tools_write.events_save)

# ── Phase 2 P1: 同步 + 评价 ───────────────────────────────────

mcp.tool(
    name="person_evaluate",
    description="添加主观评价到事实档案（⚠️概念上属于分析归档，优先级低于客观事实）。Agent 读取时应保持批判性，不能与 note/date/events 的客观事实同等对待",
)(tools_write.person_evaluate)

mcp.tool(
    name="system_sync",
    description="全量/增量数据同步（⚠️ 可能耗时 1-5 分钟，需 WCD 后端运行）",
)(tools_read.system_sync)

mcp.tool(
    name="wcd_status",
    description="检查 WCD 后端在线状态和密钥缓存状态（只读检测，不启动进程）。如果显示 offline，请调 wcd_start 启动后端",
    annotations={"readOnlyHint": True},
)(tools_read.wcd_status)

mcp.tool(
    name="wcd_start",
    description="启动 WCD 后端进程并等待健康检查通过。如果 WCD 已在运行则直接返回成功。"
               "默认等待 90s（WCD 冷启动通常需要 40-60s）。超时返回 process_alive 字段区分"
               "'进程仍在运行但健康检查未就绪'和'进程已退出'两种情况。"
               "使用场景：wcd_status 显示 offline 时调此工具启动后端",
)(tools_read.wcd_start)

mcp.tool(
    name="weflow_status",
    description="检查 WeFlow 后端在线状态（只读检测，不启动进程）。如果显示 offline，请调 weflow_start 启动后端",
    annotations={"readOnlyHint": True},
)(tools_read.weflow_status)

mcp.tool(
    name="weflow_start",
    description="启动 WeFlow 后端进程（D:\\WeFlow\\WeFlow.exe）并等待健康检查通过。如果 WeFlow 已在运行则直接返回成功。默认等待 60s",
)(tools_read.weflow_start)

# ── WeChat 进程管理 ──────────────────────────────────────────

mcp.tool(
    name="wechat_status",
    description="检查微信（Weixin.exe）是否在运行。WCD 后端需要微信已登录才能工作，同步前建议先检查微信状态",
    annotations={"readOnlyHint": True},
)(tools_read.wechat_status)

mcp.tool(
    name="wechat_start",
    description="启动微信（D:\\Weixin\\Weixin.exe）。如果微信已在运行则直接返回成功。"
               "启动后自动点击登录按钮（click_login=True，默认启用），只需扫码即可登录。"
               "参数 click_login=False 可禁用自动点击",
)(tools_read.wechat_start)

mcp.tool(
    name="wechat_stop",
    description="关闭微信（Weixin.exe）进程。force=False（默认）优雅关闭，force=True 强制终止。"
               "配合 wechat_start 可实现重启：wechat_stop → wechat_start",
)(tools_read.wechat_stop)

# ── Phase 2 P2: 只读工具拆分 ─────────────────────────────────

mcp.tool(
    name="contact_search",
    description="搜索联系人信息（身份目录查询）",
    annotations={"readOnlyHint": True},
)(tools_read.contact_search)

mcp.tool(
    name="sticker_scan",
    description="扫描聊天中的贴纸表情（⚠️ 可能耗时）",
    annotations={"readOnlyHint": True},
)(tools_read.sticker_scan)

mcp.tool(
    name="sticker_list",
    description="列出贴纸词典",
    annotations={"readOnlyHint": True},
)(tools_read.sticker_list)

mcp.tool(
    name="exclude_list",
    description="查看排除列表（硬排除 + 标签排除 + 手动排除）",
    annotations={"readOnlyHint": True},
)(tools_read.exclude_list)

mcp.tool(
    name="failure_list",
    description="查看所有失败案例",
    annotations={"readOnlyHint": True},
)(tools_read.failure_list)

mcp.tool(
    name="message_context",
    description="根据消息 ID 获取前后上下文消息（不跨会话）",
    annotations={"readOnlyHint": True},
)(tools_read.message_context)

# ── Phase 2 P2: 写入工具拆分 ─────────────────────────────────

mcp.tool(
    name="contact_alias",
    description="为联系人添加别名（写错可调 contact_alias_remove 删除后重设）",
)(tools_write.contact_alias)

mcp.tool(
    name="contact_alias_remove",
    description="删除联系人的别名（alias_type 必填，value 空则删该类型全部）",
)(tools_write.contact_alias_remove)

mcp.tool(
    name="contact_merge",
    description="⚠️【必须确认】合并两个联系人（不可逆！source 的所有 account 和 alias 转移到 target，source 记录被删除）。执行前必须征得用户明确同意",
)(tools_write.contact_merge)

mcp.tool(
    name="sticker_label",
    description="标注贴纸含义（情绪、内容类型）",
)(tools_write.sticker_label)

mcp.tool(
    name="exclude_add",
    description="将联系人加入手动排除列表",
)(tools_write.exclude_add)

mcp.tool(
    name="exclude_remove",
    description="将联系人从手动排除列表移除",
)(tools_write.exclude_remove)

mcp.tool(
    name="failure_add",
    description="记录失败案例（关系结束后记录教训）",
)(tools_write.failure_add)

mcp.tool(
    name="save_from_markdown",
    description="⚠️【分析完成·必须调用】保存完整 Markdown 分析报告。"
               "同时生成两个文件：latest.md（完整 Markdown 报告）+ latest.yaml（结构化数据）。"
               "报告必须详细（8 段式），不能只列公式数值和一句话结论。"
               "建议先用 guide('report-template') 获取报告模板。",
)(tools_write.save_from_markdown_tool)

mcp.tool(
    name="sync_moments",
    description="同步朋友圈互动到事实档案",
)(tools_write.sync_moments_tool)

# ── Phase 3 P3: 公式工具（9 个，辅助参考视角，核验而非套用）──

mcp.tool(
    name="formula_get_params",
    description="【辅助参考】获取公式参数（从数据库自动计算战态分析所需参数）。先调此工具获取自动参数，manual 参数需自行判断。"
               "接下来代入 formula_calc_ivi/spe/ews 计算。详见 guide('reference/formula')",
    annotations={"readOnlyHint": True},
)(tools_formula.formula_get_params)

mcp.tool(
    name="formula_calc_ivi",
    description="【辅助参考·核验而非套用】计算 IVI（意图真实度）。阈值（>1.0真实好感，<0.5没戏）仅是参考视角，不是裁判。"
               "先调 formula_get_params 获取自动参数，manual 参数（Pface 等）需自行判断。"
               "结果只在数据全貌表出现一次，不主导策略。最终判断依据 Wiki 知识 + 事实档案",
    annotations={"readOnlyHint": True},
)(tools_formula.formula_calc_ivi)

mcp.tool(
    name="formula_calc_spe",
    description="【辅助参考·核验而非套用】计算 SPE（社交势能）。阈值（0.8-1.5健康，<0.6红线）仅是参考视角，不是裁判。"
               "先调 formula_get_params 获取自动参数，manual 参数需自行判断。"
               "结果只在数据全貌表出现一次，不主导策略。最终判断依据 Wiki 知识 + 事实档案",
    annotations={"readOnlyHint": True},
)(tools_formula.formula_calc_spe)

mcp.tool(
    name="formula_calc_ews",
    description="【辅助参考·核验而非套用】计算 EWS（升温窗口期）。阈值（>0.8出击，<0.3关闭）仅是参考视角，不是裁判。"
               "先调 formula_get_params 获取自动参数，manual 参数需自行判断。"
               "结果只在数据全貌表出现一次，不主导策略。最终判断依据 Wiki 知识 + 事实档案",
    annotations={"readOnlyHint": True},
)(tools_formula.formula_calc_ews)

mcp.tool(
    name="formula_calc_is",
    description="【辅助参考·核验而非套用】计算 IS（真实亲密度）。阈值（>0.5高亲密度）仅是参考视角，不是裁判。"
               "先调 formula_get_params 获取自动参数，manual 参数需自行判断。"
               "结果只在数据全貌表出现一次，不主导策略。最终判断依据 Wiki 知识 + 事实档案",
    annotations={"readOnlyHint": True},
)(tools_formula.formula_calc_is)

mcp.tool(
    name="formula_calc_gap_effect",
    description="【辅助参考·核验而非套用】计算 Gap_Effect（情绪落差刺激）。结果仅是参考视角，不是裁判。"
               "先调 formula_get_params 获取自动参数。"
               "结果只在数据全貌表出现一次，不主导策略。最终判断依据 Wiki 知识 + 事实档案",
    annotations={"readOnlyHint": True},
)(tools_formula.formula_calc_gap_effect)

mcp.tool(
    name="formula_calc_eev",
    description="【辅助参考·核验而非套用】计算 EEV（升温期望值）。阈值（>0.3值得出击）仅是参考视角，不是裁判。"
               "先调 formula_get_params 获取自动参数，manual 参数需自行判断。"
               "结果只在数据全貌表出现一次，不主导策略。最终判断依据 Wiki 知识 + 事实档案",
    annotations={"readOnlyHint": True},
)(tools_formula.formula_calc_eev)

mcp.tool(
    name="formula_calc_cs",
    description="【辅助参考·核验而非套用】计算 CS（矛盾演化状态）。阈值（>0欲望占主导）仅是参考视角，不是裁判。"
               "先调 formula_get_params 获取自动参数，manual 参数需自行判断。"
               "结果只在数据全貌表出现一次，不主导策略。最终判断依据 Wiki 知识 + 事实档案",
    annotations={"readOnlyHint": True},
)(tools_formula.formula_calc_cs)

mcp.tool(
    name="formula_calc_action",
    description="【辅助参考·核验而非套用】终极行动决策 — 基于 IVI/SPE/EWS 的策略分发（进攻/拉扯/重置/维持）。"
               "参考视角，不是裁判。结果只在数据全貌表出现一次，不主导策略。最终判断依据 Wiki 知识 + 事实档案",
    annotations={"readOnlyHint": True},
)(tools_formula.formula_calc_action)

# ── 注册实时监听工具 ──────────────────────────────────────────

mcp.tool(
    name="live_monitor_start",
    description="【实时聊天场景】开始监听联系人的最新消息。"
               "自动拉取最近30分钟消息，然后按 poll_interval 秒轮询刷新（默认10s）。"
               "监听期间用 live_chat_read 读取最新消息，无需每次手动 person_sync。"
               "场景：正在和对方聊天，需要 agent 实时辅助回复。"
               "结束后用 live_monitor_stop 停止。"
               "参数：poll_interval=10（轮询间隔秒），fetch_limit=500，include_brief=False，"
               "auto_stop=600（无读取自动停止秒数，默认10分钟，0=禁用）",
)(tools_live.live_monitor_start)

mcp.tool(
    name="live_monitor_stop",
    description="停止实时监听。传入 name 停止指定联系人，不传则停止所有监听。",
)(tools_live.live_monitor_stop)

mcp.tool(
    name="live_monitor_status",
    description="查看当前监听状态（正在监听哪些联系人、未读消息数、轮询间隔等）。",
    annotations={"readOnlyHint": True},
)(tools_live.live_monitor_status)

mcp.tool(
    name="live_chat_read",
    description="【实时聊天场景】读取实时监听缓存的消息。"
               "比 person_sync + person_chat 快得多，适合聊天中频繁调用。"
               "必须在 live_monitor_start 之后使用。"
               "参数：recent=0（返回最后N条，0=全部），since_last_read=False（增量模式，只返回上次读取后的新消息）",
    annotations={"readOnlyHint": True},
)(tools_live.live_chat_read)

# ── 注册微信自动发消息工具 ────────────────────────────────────

mcp.tool(
    name="wechat_send",
    description="【微信自动发消息·v4 三重硬约束】向微信联系人自动发送消息（通过视觉识别操作微信 PC 客户端）。"
               "⚠️ 会抢鼠标：执行期间会移动鼠标并占用键鼠，调用前 Agent 应当口头提醒用户"
               "'即将发送微信消息，执行期间请勿操作鼠标键盘'（不需要阻塞等待确认，说出来即可）。"
               "前置条件：微信已运行并登录，联系人头像模板已存放在 data/avatars/<display_name>.jpg。"
               "参数：name（联系人标识符：微信号/wxid/昵称/备注名 均可），message（要发送的消息内容），"
               "urgent（可选，默认 False；True 时绕过回复冷却校验，用于对方连续追问等紧急场景，但仍然校验线索已读）。"
               "v4 三重硬约束（自动校验）："
               "① 线索已读校验 — conversation_thread.last_processed_message_id 必须 >= 数据库最新消息 ID，"
               "未读取最新消息时返回 THREAD_NOT_CAUGHT_UP 错误，需先调 conversation_thread(action='catch_up')；"
               "② 回复冷却校验 — 按关系阶段最小冷却（Stage 1-2: 30min / Stage 3: 5min / Stage 4+: 3min），"
               "冷却中返回 COOLDOWN_ACTIVE 错误和 wait_seconds；urgent=True 可绕过；"
               "③ 互斥锁校验 — 视觉自动化串行。"
               "联系人解析：name 会先在数据库中查找对应的微信号（alias），用微信号搜索（唯一，避免重名）。"
               "若按昵称匹配到多个联系人 → 拒绝发送，返回 matches 列表，需用微信号或 wxid 重新调用。"
               "流程：硬约束校验→解析联系人→搜索微信号→点击头像→输入消息→点击发送。"
               "内置防封号机制：分段随机输入+点击位置抖动+间隔随机化，无需配置。"
               "如果微信在后台运行但窗口不可见，会自动恢复窗口。"
               "示例：wechat_send('[REDACTED]', '你好') / wechat_send('[REDACTED]', '在的', urgent=True)。"
               "详细说明：guide('reference/wechat')",
)(tools_wechat.wechat_send)

mcp.tool(
    name="wechat_send_emoji",
    description="【微信自动发表情包】向微信联系人自动发送表情包（通过视觉识别操作微信 PC 客户端）。"
               "⚠️ 会抢鼠标：执行期间会移动鼠标并占用键鼠，调用前 Agent 应当口头提醒用户"
               "'即将发送微信表情包，执行期间请勿操作鼠标键盘'（不需要阻塞等待确认，说出来即可）。"
               "前置条件：微信已运行并登录，联系人头像模板已存放在 data/avatars/<wxid>.jpg。"
               "参数：name（联系人标识符：微信号/wxid/昵称/备注名 均可），emoji_keyword（表情搜索关键词，如'猫猫'、'感谢'、'开心'、'晚安'）。"
               "流程：解析联系人→搜索微信号→点击头像进入聊天→点击表情按钮→打开表情面板（独立小窗口）→"
               "点击搜索键→输入关键词→点击搜索结果中的第一个表情（直接发送，无需点发送按钮）。"
               "与 wechat_send 的区别：阶段一/二相同，阶段三用表情面板搜索发送，不输入文字。"
               "表情面板是独立小窗口（类似搜索候选框），发送后面板自动关闭。"
               "如果微信在后台运行但窗口不可见，会自动恢复窗口。"
               "示例：wechat_send_emoji('[REDACTED]', '猫猫') → 发送搜索'猫猫'得到的第一个表情包",
)(tools_wechat.wechat_send_emoji)

mcp.tool(
    name="wechat_ocr",
    description="【微信截图OCR】截图微信窗口并进行 OCR 文字识别，返回带位置信息的文字列表。"
               "适用于：读取聊天界面文字、提取联系人信息、识别界面元素等场景。"
               "参数：region（截图区域，full=整个窗口/chat=聊天区域/session=会话列表，默认full），"
               "use_cache（是否使用缓存，默认false因为界面内容会变化）。"
               "前置条件：微信已运行并登录。如果窗口不可见会自动恢复。"
               "返回：texts（文字列表含bbox/confidence/center）、full_text（拼接文字）、screenshot_path。"
               "示例：wechat_ocr('chat') → 截图聊天区域并返回识别到的文字",
    annotations={"readOnlyHint": True},
)(tools_wechat.wechat_ocr)

mcp.tool(
    name="open_wechat_window",
    description="【打开微信窗口】在微信已启动但窗口不可见（被关闭/最小化到托盘）时，"
               "通过点击任务栏右下角托盘的微信绿色图标唤醒主窗口。"
               "实现：HSV颜色匹配托盘区域→物理点击图标→轮询等待窗口出现。"
               "基于录屏分析：闪烁周期约1.867秒，常态下图标稳定绿色，单次截图即可匹配。"
               "使用场景：wechat_send失败提示'微信窗口未打开'时，先调用本工具唤醒窗口。"
               "前置条件：微信进程已启动（Weixin.exe 在运行）。"
               "参数：timeout（等待窗口出现的最大秒数，默认10.0）。"
               "返回：success/action/window/elapsed。action 可能值：already_visible/tray_click/failed。",
)(tools_wechat.open_wechat_window)

# ── 注册头像获取工具 ────────────────────────────────────────────

mcp.tool(
    name="person_avatar",
    description="【头像获取】获取联系人头像并保存到 data/avatars/<name>.jpg。"
               "支持任意标识符：昵称、wxid、微信号、备注名、alias 均可。"
               "保存的 .jpg 文件可直接用于 wechat_send 工具的模板匹配。"
               "头像更新策略：默认比较 URL 检测变化（check_update=True），URL 不变则跳过下载。"
               "数据源优先级：本地缓存 → core.db → WeFlow API → contacts.json 缓存（CDN 直链，不需要服务运行）。"
               "参数：name（联系人标识符），force_refresh（强制重新下载，默认false），"
               "check_update（检查URL变化，默认true）。"
               "示例：person_avatar('[REDACTED]') → 获取 [REDACTED] 的头像并保存为 [REDACTED].jpg",
)(tools_avatar.person_avatar)

# ── 注册 v4 自动回复架构新工具（P0）──────────────────────────────

mcp.tool(
    name="conversation_thread",
    description="【v4 对话线索管理】每个联系人独立一个对话线索文件，自动回复前必读。"
               "管理 recent_summary / current_threads / pending_items / her_emotion / key_context / "
               "landmine_topics / avoid_topics / initiative_tracker 等字段。"
               "action：get（读取线索）/ update（更新字段，支持乐观锁 expected_version）/ "
               "append_summary（追加消息摘要）/ clear（清空线索，保留 landmine 和 avoid_topics）/ "
               "check_expired（检查线索是否过期，按关系阶段阈值）/ catch_up（标记线索已追上最新消息）/ "
               "add_landmine（添加雷区话题）/ add_avoid_topic（添加避谈话题）。"
               "wechat_send 发送前会校验线索的 last_processed_message_id，未追上时会拒绝发送。"
               "工具只做 CRUD，不判断'该不该回复'、不评估关系阶段、不生成回复建议。",
    annotations={"readOnlyHint": False},
)(tools_thread.conversation_thread)

mcp.tool(
    name="schedule_manage",
    description="【v4 用户日程管理】管理用户日程（纯 CRUD，不解析自然语言，不冲突检测，不推荐时间）。"
               "action：query（按日期/联系人查询日程）/ add（添加事件）/ update（更新事件）/ "
               "remove（删除事件）/ list_slots（查询可用时段，返回空时段列表）/ "
               "update_preferences（更新用户偏好）/ add_note（添加备注）。"
               "文件路径：data/schedule.yaml（单一文件，全局用户日程）。"
               "事件 ID 格式：evt_{timestamp}_{person}。"
               "Agent 邀约前应先调 list_slots 查询可用时段，再基于 Wiki 邀约三步法生成邀约话术。",
    annotations={"readOnlyHint": False},
)(tools_schedule.schedule_manage)

mcp.tool(
    name="user_profile_manage",
    description="【v4 用户画像管理·三类文件】管理用户事实画像/风格画像/坏习惯（CRUD）。"
               "profile_type：fact（事实画像，grounding，高优先级）/ style（表达风格，smoothing，低优先级）/ "
               "bad_patterns（坏习惯，avoid，高优先级）。"
               "action：get（读取画像）/ update（更新段落，fact 会记录 change_history）/ "
               "add_asset（添加素材：话题/故事）/ query_assets（查询素材）/ "
               "add_bad_pattern（添加坏习惯）/ mark_pattern_corrected（标记坏习惯已纠正）/ "
               "reset_style_override（重置联系人特化层）。"
               "文件：data/user_profile_fact.yaml + data/user_style_profile.yaml + "
               "data/user_style_overrides/<id>.yaml + data/user_bad_patterns.yaml。"
               "工具不生成回复风格建议，不决策'对这个人该用什么语气'，不评估人设是否合适。",
    annotations={"readOnlyHint": False},
)(tools_profile.user_profile_manage)

mcp.tool(
    name="date_briefing",
    description="【v4 约会前简报】生成 5 段式约会前简报（数据聚合 + 模板填充）。"
               "触发时机：用户确认确定邀约后 / 约会前 1 天主动提醒。"
               "参数：name（联系人），date_plan（dict，含 date/time_range/location/activity，可选）。"
               "返回：briefing_markdown（5 段式模板：关系阶段/注意事项/可讨论话题/需交流信息/约会后计划）+ "
               "data_sources（各段原始数据：person_snapshot/conversation_thread/fact_excerpts/schedule_info/user_profile）+ "
               "wiki_queries（Agent 应调用的 Wiki 查询列表）。"
               "工具只做数据聚合，分析性内容（如'不要面对面坐'）由 Agent 调 wiki_context 获取方法论后填充。"
               "明确不做：❌ 不生成约会方案 ❌ 不决策'要不要赴约' ❌ 不评估约会成功概率 ❌ 不生成约会中话术。",
    annotations={"readOnlyHint": True},
)(tools_date.date_briefing)

mcp.tool(
    name="recent_replies_check",
    description="【v4 跨联系人回复查重】防止 Agent 对不同联系人发相同话术（破坏拟人度）。"
               "action：check（检查回复是否与近期发给其他人的回复重复）/ add（发送成功后记录到池中）/ "
               "query（查询近期回复记录）。"
               "参数：reply_content（回复内容），to（目标联系人），pattern（意图 pattern，由 Agent 提取，"
               "如'关心状况'/'推荐场所'/'共情辛苦'），time_range_hours（时间窗口，默认 24）。"
               "查重规则：完全相同话术 → 高危（必须换）；相同 pattern 不同措辞 → 中危（建议换）；"
               "不同 pattern → 通过。跨联系人查重（对同一联系人重复 pattern 是正常的）。"
               "工具只做 pattern 匹配，不做语义相似度计算；不决策'能不能发'；不生成替代回复。"
               "文件：data/system/recent_replies.yaml（最多 500 条，超出自动裁剪）。",
    annotations={"readOnlyHint": False},
)(tools_replies.recent_replies_check)

# ── 注册 v4 自动回复架构新工具（P1）──────────────────────────────

mcp.tool(
    name="server_chan_notify",
    description="【v4 Server酱推送】将紧急事件推送到用户微信（Server酱）。"
               "参数：title（标题），content（正文，支持 Markdown），priority（0-3，"
               "0=Debug 1=Info 2=Warning 3=Urgent，默认 2）。"
               "推送条件：enabled=true 且 priority >= min_priority 时推送。"
               "Agent 自主判断事件紧急程度并决定是否调用，参考场景（非硬性规则）："
               "邀约窗口开启/成功、对方情绪突变/断联风险、委员会连续驳回、系统异常。"
               "明确不做：❌ 不决策'该不该通知' ❌ 不生成通知内容（Agent 撰写）"
               "❌ 不评估紧急程度 ❌ 不做频率控制（Agent 判断）。",
    annotations={"readOnlyHint": False},
)(tools_notify.server_chan_notify)

mcp.tool(
    name="server_chan_config",
    description="【v4 Server酱配置】管理 Server酱推送配置（get/set）。"
               "action=get 返回当前配置；action=set 更新配置（enabled/sckey/min_priority）。"
               "配置文件：data/system/config.yaml 的 serverchan 段。"
               "sckey 需用户在 https://sct.ftqq.com/ 注册后获取。",
    annotations={"readOnlyHint": False},
)(tools_notify.server_chan_config)

mcp.tool(
    name="date_feedback_loop",
    description="【v4 约会后反馈循环】约会结束后记录反馈并生成待分析项列表。"
               "触发时机：日程时间到点（约会计划结束+1小时）/ 用户手动告知约会结束。"
               "参数：name（联系人），date_event_id（约会事件 ID），"
               "feedback_text（用户手动输入的反馈，可选），feedback_structured（结构化反馈，可选）。"
               "返回：record_id + pending_items（Agent 应询问用户的问题 + 应更新的数据条目）。"
               "pending_items 包含问题模板（整体感觉/对方反应/关键信号/下次意向）+ "
               "数据更新指引（events_save/person_note/conversation_thread/person_stage）+ Wiki 依据。"
               "明确不做：❌ 不评估约会是否成功 ❌ 不生成改进建议 ❌ 不决策'下一步怎么做' ❌ 不做情感分析。"
               "Agent 应基于 pending_items 调 AskUserQuestion 询问用户，然后更新数据。",
    annotations={"readOnlyHint": False},
)(tools_date.date_feedback_loop)

mcp.tool(
    name="date_feedback_mark_analyzed",
    description="【v4 约会反馈标记已分析】标记某条约会反馈记录为已分析状态。"
               "Agent 完成约会反馈分析（询问用户 + 更新数据）后调用。"
               "参数：record_id（反馈记录 ID），analysis_summary（分析摘要，可选）。"
               "只更新状态字段，不生成任何分析内容。",
    annotations={"readOnlyHint": False},
)(tools_date.mark_analyzed)

mcp.tool(
    name="effect_tracking",
    description="【v4 效果追踪】追踪自动发送回复的效果（对方是否回复/回复延迟/回复情感）。"
               "action：record（记录一条发送效果，需 person + message_type）/ "
               "update_response（更新待响应记录的回复信息）/ stats（统计：回复率/平均回复间隔/"
               "正面回复率/按类型分组/委员会结果分布）/ report（详细报告：含按联系人分组 + "
               "最近 10 条记录 + 无回复记录列表）。"
               "message_type：auto_reply（自动回复）/ initiative（主动发起）/ invitation（邀约）。"
               "response_sentiment：positive/neutral/negative/no_response。"
               "文件：data/system/effect_tracking.yaml（最多 1000 条）。"
               "明确不做：❌ 不决策'系统好不好' ❌ 不生成优化方案 ❌ 不评估'哪条回复失败' ❌ 不做归因分析。"
               "所有效果判断由 Agent 基于 stats/report 数据自主完成。",
    annotations={"readOnlyHint": False},
)(tools_replies.effect_tracking)

mcp.tool(
    name="contact_priority_manage",
    description="【v4 联系人优先级管理】持久化管理联系人优先级权重（get/list/set_eval/set_override/reset）。"
               "⚠️ 工具不计算优先级分数（分数由 Agent 基于 person_stage/person_signals/person_metrics 计算），"
               "工具只持久化 user_eval（用户主观评价 high/medium/low）和 override_score（手动覆盖分数 0-1）。"
               "action=get（查单人）/ list（列出所有，按 override+eval 排序）/ "
               "set_eval（设置用户主观评价）/ set_override（手动覆盖分数，需 reason）/ reset（重置）。"
               "优先级影响约会安排顺序，但不机械影响每条消息的回复及时性（回复间隔按各自关系阶段决定）。"
               "文件：data/system/contact_priority.yaml。"
               "明确不做：❌ 不计算优先级分数 ❌ 不决策'先回谁' ❌ 不评估关系重要性 ❌ 不生成调整建议。",
    annotations={"readOnlyHint": False},
)(tools_priority.contact_priority_manage)

mcp.tool(
    name="override_learning",
    description="【v4 手动覆盖学习闭环】记录用户手动回复（绕过 Agent）的差异并生成学习规则候选。"
               "触发：Agent 检测到用户手动回复后，对比 Agent 草案与用户实际发送内容。"
               "action：record（记录差异 + 生成学习候选）/ query（查询历史事件）/ "
               "stats（统计：按差异类型/按联系人/已应用数）/ mark_applied（标记事件已应用）。"
               "record 参数：original_draft（Agent 草案）+ final_sent（用户实际发送）+ "
               "context（上下文 dict）+ person（联系人）。"
               "差异类型：identical（一致）/ style（风格差异）/ strategy（策略差异）/ content（内容差异）。"
               "差异分析只做客观对比（长度/标点/问句/语气词），不做语义分析。"
               "学习规则候选需 Agent 审核后决定是否应用（应用后调 mark_applied）。"
               "文件：data/system/override_learning.yaml（最多 500 条）。"
               "明确不做：❌ 不自动应用学习规则 ❌ 不决策'下次该怎么回' ❌ 不评估编辑好坏 ❌ 不做人设推断。",
    annotations={"readOnlyHint": False},
)(tools_override.override_learning)

if __name__ == "__main__":
    try:
        mcp.run()
    finally:
        # MCP Server 退出时自动停止所有实时监听
        from engine.live_monitor import get_manager
        get_manager().stop()
