"""约会前简报 MCP 工具（v4 自动回复架构组件）。

本模块实现 v4 文档 10.4 节规格：约会前简报生成。
工具契约（v4 23.2 节）：
  - 输入：name + date_context（约会时间/地点，可选）
  - 输出：5 段式简报 Markdown + 数据载荷（人物快照 + Wiki 指引 + 行程注意事项 + 话题储备 + 风险提醒）
  - 明确不做：❌ 不生成约会方案 ❌ 不决策"要不要赴约" ❌ 不评估约会成功概率 ❌ 不生成约会中话术

设计原则（v4 23.x 工具契约）：
  - 工具只做数据聚合 + 模板填充，不生成分析性内容
  - 分析性内容（如"不要面对面坐"）由 Agent 基于 Wiki 自主生成
  - 工具提供 Wiki 查询建议，由 Agent 调用 wiki_context 获取方法论
"""

import os
import sys
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


def date_briefing(name: str, date_plan: Optional[dict] = None) -> dict:
    """生成约会前简报（5 段式数据聚合 + 模板）。

    什么时候用：用户确认确定邀约后 / 约会前 1 天主动提醒时。
    返回什么：dict 含 briefing_markdown（5 段式模板）+ data_sources（各段原始数据）+
              wiki_queries（Agent 应调用的 Wiki 查询列表）。
    边界是什么：只聚合数据，不生成分析性内容；不生成约会方案；不评估约会成功概率；
                不生成约会中话术。Agent 需自行调 wiki_context 获取方法论后填充分析。
    """
    date_plan = date_plan or {}

    try:
        # 1. 聚合人物快照
        person_snapshot = _fetch_person_snapshot(name)
        if "error" in person_snapshot:
            return person_snapshot

        # 2. 聚合对话线索
        thread_data = _fetch_conversation_thread(name)

        # 3. 聚合事实档案关键信息
        fact_excerpts = _fetch_fact_excerpts(name)

        # 4. 聚合用户日程
        schedule_info = _fetch_schedule_conflicts(date_plan)

        # 5. 聚合用户画像（事实）
        user_profile = _fetch_user_profile()

        # 6. 生成 Wiki 查询建议（基于阶段 + 信号）
        wiki_queries = _build_wiki_queries(
            person_snapshot.get("relationship_stage", ""),
            person_snapshot.get("signals", {}),
        )

        # 7. 填充 5 段式简报模板
        briefing_markdown = _render_briefing(
            name=name,
            date_plan=date_plan,
            person_snapshot=person_snapshot,
            thread_data=thread_data,
            fact_excerpts=fact_excerpts,
            schedule_info=schedule_info,
            user_profile=user_profile,
            wiki_queries=wiki_queries,
        )

        return {
            "success": True,
            "name": name,
            "date_plan": date_plan,
            "briefing_markdown": briefing_markdown,
            "data_sources": {
                "person_snapshot": person_snapshot,
                "conversation_thread": thread_data,
                "fact_excerpts": fact_excerpts,
                "schedule_info": schedule_info,
                "user_profile": user_profile,
            },
            "wiki_queries": wiki_queries,
            "next_step": (
                "Agent 应调用 wiki_context(queries=wiki_queries, task_type='meet', "
                "stage=relationship_stage, focus='date') 获取方法论，"
                "然后基于返回的 prompt_section 填充 briefing_markdown 中的分析性段落。"
            ),
        }
    except Exception as e:
        logger.exception("date_briefing 异常")
        return {
            "error": "TOOL_ERROR",
            "message": str(e),
            "suggestion": "请检查联系人姓名是否正确，以及约会计划参数格式",
        }


# ── 数据聚合函数 ────────────────────────────────────────────────


def _fetch_person_snapshot(name: str) -> dict:
    """从 person_brief_data 提取人物快照（阶段/指标/信号）。"""
    try:
        from engine.tools import brief_data

        data = brief_data(name)
        if "error" in data:
            return data

        recommendations = data.get("recommendations", {})
        metrics = data.get("metrics", {}) or {}

        # 提取关键信号
        signals = data.get("signals", {}) or {}
        key_signals = []
        for category, items in signals.items():
            if isinstance(items, list):
                for item in items[:3]:  # 每类最多 3 条
                    key_signals.append(f"[{category}] {item}")
            elif isinstance(items, (str, int, float)):
                key_signals.append(f"[{category}] {items}")

        return {
            "person_id": data.get("identity", {}).get("person_id", ""),
            "display_name": data.get("identity", {}).get("display_name", name),
            "relationship_stage": recommendations.get("relationship_stage", "unknown"),
            "message_stats": data.get("message_stats", {}),
            "metrics_snapshot": {
                "composite": metrics.get("composite"),
                "signal_level": metrics.get("signal_level"),
                "reply_rate": metrics.get("reply_rate"),
                "initiative_ratio": metrics.get("initiative_ratio"),
                "recent_days": metrics.get("recent_days"),
            },
            "signals": signals,
            "key_signals": key_signals[:10],  # 最多 10 条
            "events": data.get("events", [])[:5],
            "latest_analysis": data.get("latest_analysis"),
        }
    except Exception as e:
        logger.warning(f"person_snapshot 聚合失败 {name}: {e}")
        return {"error": "PERSON_NOT_FOUND", "message": f"未找到联系人或数据加载失败: {name}"}


def _fetch_conversation_thread(name: str) -> dict:
    """从 conversation_thread 提取对话线索关键信息。"""
    try:
        from mcp_server.tools_thread import conversation_thread

        result = conversation_thread(action="get", name=name)
        if "error" in result:
            return {"available": False, "reason": result.get("message", "")}

        thread = result.get("thread", {})
        return {
            "available": True,
            "current_threads": thread.get("current_threads", [])[:3],
            "key_context": thread.get("key_context", [])[:5],
            "her_emotion": thread.get("her_emotion", {}),
            "landmine_topics": thread.get("landmine_topics", []),
            "avoid_topics": thread.get("avoid_topics", []),
            "pending_items": thread.get("pending_items", []),
            "initiative_tracker": thread.get("initiative_tracker", {}),
            "last_updated": thread.get("last_updated"),
        }
    except Exception as e:
        logger.warning(f"conversation_thread 聚合失败 {name}: {e}")
        return {"available": False, "reason": str(e)}


def _fetch_fact_excerpts(name: str) -> dict:
    """从事实档案提取兴趣点 / 上次提到的事 / 评价。"""
    try:
        from engine.tools import evidence

        text = evidence(name, section="all")
        if not text:
            return {"available": False, "excerpt": ""}

        # 截取前 2000 字符作为简报参考
        excerpt = text[:2000]
        if len(text) > 2000:
            excerpt += "\n... (更多内容请调 person_evidence)"

        return {
            "available": True,
            "excerpt": excerpt,
            "full_length": len(text),
        }
    except Exception as e:
        logger.warning(f"fact_excerpts 聚合失败 {name}: {e}")
        return {"available": False, "reason": str(e)}


def _fetch_schedule_conflicts(date_plan: dict) -> dict:
    """检查约会时间与用户日程的冲突。"""
    if not date_plan:
        return {"available": False, "reason": "未提供 date_plan"}

    date_str = date_plan.get("date")
    if not date_str:
        return {"available": False, "reason": "date_plan 缺少 date 字段"}

    try:
        from mcp_server.tools_schedule import schedule_manage

        result = schedule_manage(action="query", date=date_str)
        events = result.get("events", [])

        # 检查时间冲突
        time_range = date_plan.get("time_range", "")
        conflicts = []
        for evt in events:
            evt_time = evt.get("time_range", "") or evt.get("time", "")
            if time_range and evt_time and _time_overlaps(time_range, evt_time):
                conflicts.append(evt)

        return {
            "available": True,
            "date": date_str,
            "scheduled_events": events,
            "conflicts": conflicts,
            "has_conflict": len(conflicts) > 0,
        }
    except Exception as e:
        logger.warning(f"schedule_conflicts 聚合失败: {e}")
        return {"available": False, "reason": str(e)}


def _fetch_user_profile() -> dict:
    """获取用户事实画像。"""
    try:
        from mcp_server.tools_profile import user_profile_manage

        fact_result = user_profile_manage(action="get", profile_type="fact")

        fact_data = fact_result.get("profile", {}) or {}

        return {
            "available": True,
            "user_hobbies": fact_data.get("hobbies", [])[:5],
            "user_values": fact_data.get("values", [])[:3],
            "user_material_topics": (fact_data.get("material_library", {}) or {}).get("topics", [])[:5],
            "user_material_stories": (fact_data.get("material_library", {}) or {}).get("stories", [])[:3],
        }
    except Exception as e:
        logger.warning(f"user_profile 聚合失败: {e}")
        return {"available": False, "reason": str(e)}


# ── Wiki 查询建议 ────────────────────────────────────────────────


def _build_wiki_queries(stage: str, signals: dict) -> list[str]:
    """构建约会相关的 Wiki 查询话题列表（供 Agent 参考，Agent 自行决定用哪些）。

    设计原则（2026-07-24）：代码不替 agent 做决策。
    - 不按 stage 过滤话题（stage 是 agent 的决策维度）
    - 不按 signals 推荐话题（agent 看到 signals 自行决定是否需要查）
    - 只提供通用约会相关话题列表，Agent 基于 person_snapshot 自行选择
    """
    # 通用约会相关话题（不按 stage/signals 过滤，Agent 自行决定哪些相关）
    queries = [
        "第一次约会怎么安排",
        "约会话题",
        "高频聊天转见面",
        "邀约三步法",
        "第二次约会",
        "约会后跟进",
        "IOI 窗口识别",
        "操控信号识别",
    ]
    return queries


# ── 简报模板渲染 ────────────────────────────────────────────────


def _render_briefing(
    name: str,
    date_plan: dict,
    person_snapshot: dict,
    thread_data: dict,
    fact_excerpts: dict,
    schedule_info: dict,
    user_profile: dict,
    wiki_queries: list[str],
) -> str:
    """渲染 5 段式简报 Markdown 模板。

    模板中数据已填充，分析性段落以 [Agent 基于 Wiki 填充] 标记，
    由 Agent 调用 wiki_context 后补充。
    """
    display_name = person_snapshot.get("display_name", name)
    date_str = date_plan.get("date", "未指定")
    time_str = date_plan.get("time_range", "")
    location = date_plan.get("location", "")
    activity = date_plan.get("activity", "")

    # 头部
    lines = [
        f"# 约会前简报：{display_name}",
        f"## 约会时间：{date_str} {time_str}".rstrip(),
    ]
    if location:
        lines.append(f"**地点**：{location}")
    if activity:
        lines.append(f"**活动**：{activity}")
    lines.append("")

    # ── 第一段：关系发展阶段 ─────────────────────────────────
    lines.append("### 一、关系发展阶段")
    stage = person_snapshot.get("relationship_stage", "unknown")
    metrics_snap = person_snapshot.get("metrics_snapshot", {}) or {}
    lines.append(f"- 当前阶段：{stage}")
    if metrics_snap.get("signal_level"):
        lines.append(f"- 信号等级：{metrics_snap['signal_level']}")
    if metrics_snap.get("reply_rate") is not None:
        lines.append(f"- 回复率：{metrics_snap['reply_rate']}")
    if metrics_snap.get("initiative_ratio") is not None:
        lines.append(f"- 主动率：{metrics_snap['initiative_ratio']}")
    if metrics_snap.get("recent_days") is not None:
        lines.append(f"- 近期热度（天数）：{metrics_snap['recent_days']}")
    lines.append("- Wiki 依据：[Agent 调用 wiki_context 获取关系阶段定义+频率操作手册]")
    lines.append("")

    # ── 第二段：这次约会要注意什么 ───────────────────────────
    lines.append("### 二、这次约会要注意什么")
    lines.append("**核心目标**：[Agent 基于 Wiki 填充 — 根据当前阶段确定核心目标]")
    lines.append("**Wiki 依据**：[Agent 调用 wiki_context 获取『第一次约会怎么安排』]")
    lines.append("**注意事项**：")
    lines.append("1. [Agent 基于 Wiki 填充]")
    lines.append("2. [Agent 基于 Wiki 填充]")
    lines.append("3. [Agent 基于 Wiki 填充]")
    # 风险提醒（来自对话线索）
    if thread_data.get("available"):
        landmines = thread_data.get("landmine_topics", [])
        avoids = thread_data.get("avoid_topics", [])
        if landmines or avoids:
            lines.append("**对话中已识别的风险话题**：")
            for lm in landmines[:3]:
                topic = lm.get("topic", lm) if isinstance(lm, dict) else str(lm)
                lines.append(f"- ⚠️ 雷区：{topic}")
            for av in avoids[:3]:
                lines.append(f"- 🚫 避谈：{av}")
    lines.append("")

    # ── 第三段：可讨论的话题 ────────────────────────────────
    lines.append("### 三、可讨论的话题")
    lines.append("**Wiki 依据**：[Agent 调用 wiki_context 获取『各阶段聊天话题库』]")
    if thread_data.get("available"):
        current_threads = thread_data.get("current_threads", [])
        if current_threads:
            lines.append("**从对话线索延续的话题**：")
            for t in current_threads[:3]:
                topic = t.get("topic", "") if isinstance(t, dict) else str(t)
                lines.append(f"- {topic}")
        key_context = thread_data.get("key_context", [])
        if key_context:
            lines.append("**对话关键上下文**：")
            for ctx in key_context[:3]:
                ctx_text = ctx.get("summary", "") if isinstance(ctx, dict) else str(ctx)
                lines.append(f"- {ctx_text}")
    # 用户素材库
    if user_profile.get("available"):
        material_topics = user_profile.get("user_material_topics", [])
        material_stories = user_profile.get("user_material_stories", [])
        if material_topics:
            lines.append("**用户素材库·可聊话题**：")
            for t in material_topics[:3]:
                lines.append(f"- {t}")
        if material_stories:
            lines.append("**用户素材库·可讲故事**：")
            for s in material_stories[:2]:
                s_title = s.get("title", "") if isinstance(s, dict) else str(s)
                lines.append(f"- {s_title}")
    lines.append("")

    # ── 第四段：需要交流的信息 ───────────────────────────────
    lines.append("### 四、需要交流的信息")
    if fact_excerpts.get("available"):
        lines.append("**事实档案摘要（她曾提到的事）**：")
        lines.append("```")
        lines.append(fact_excerpts.get("excerpt", "")[:800])
        lines.append("```")
    lines.append("**需要补充了解的**：[Agent 基于对话线索 + 事实档案判断]")
    lines.append("")

    # ── 第五段：约会后计划 ──────────────────────────────────
    lines.append("### 五、约会后计划")
    lines.append("**Wiki 依据**：[Agent 调用 wiki_context 获取『第一次约会回来之后』]")
    lines.append("- [Agent 基于 Wiki 填充：当晚跟进时间窗口]")
    lines.append("- [Agent 基于 Wiki 填充：保持聊天频率建议]")
    lines.append("- [Agent 基于 Wiki 填充：约第二次的时间间隔]")
    lines.append("- Agent 会在约会后通过 date_feedback_loop 询问反馈")
    lines.append("")

    # ── 附录：Wiki 查询建议 ─────────────────────────────────
    lines.append("---")
    lines.append("## 附录：Agent 下一步操作")
    lines.append("**可选的 Wiki 查询话题**（Agent 自行判断哪些相关，不需要全部查询）：")
    lines.append(f"```")
    lines.append(f"可用话题：{', '.join(wiki_queries)}")
    lines.append(f"```")
    lines.append("Agent 基于 person_snapshot（stage/signals）自行选择相关话题，调用：")
    lines.append("```python")
    lines.append("wiki_context(")
    lines.append("    queries=[...],  # Agent 自行选择上述话题中相关的子集")
    lines.append("    task_type='meet',")
    lines.append(f"    stage='{stage}',  # 可选，用于 Wiki 内容排名（非过滤）")
    lines.append("    focus='date'")
    lines.append(")")
    lines.append("```")
    lines.append("获取 Wiki 方法论后，填充上述简报中 [Agent 基于 Wiki 填充] 标记的段落。")

    return "\n".join(lines)


# ── 工具函数 ────────────────────────────────────────────────────


def _time_overlaps(range_a: str, range_b: str) -> bool:
    """粗略判断两个时间范围是否重叠（格式：HH:MM-HH:MM）。"""
    try:
        a_start, a_end = _parse_time_range(range_a)
        b_start, b_end = _parse_time_range(range_b)
        return not (a_end <= b_start or b_end <= a_start)
    except Exception:
        return False


def _parse_time_range(s: str) -> tuple[int, int]:
    """解析 HH:MM-HH:MM 格式，返回 (start_minutes, end_minutes)。"""
    parts = s.split("-")
    if len(parts) != 2:
        raise ValueError(f"无法解析时间范围: {s}")

    def to_minutes(t: str) -> int:
        t = t.strip()
        h, m = t.split(":")
        return int(h) * 60 + int(m)

    return to_minutes(parts[0]), to_minutes(parts[1])


# ── date_feedback_loop（v4 10.5 节，P1）──────────────────────────


def date_feedback_loop(
    name: str,
    date_event_id: str,
    feedback_text: Optional[str] = None,
    feedback_structured: Optional[dict] = None,
) -> dict:
    """约会后反馈循环工具。

    什么时候用：约会结束（日程时间到点 +1 小时 / 用户手动告知回来了）后。
    返回什么：反馈记录结果 + 待分析项列表（Agent 应询问用户的问题 +
              应更新的数据条目）。
    边界是什么：不评估约会是否成功；不生成改进建议；不决策"下一步怎么做"；
                不做情感分析。Agent 需自行调 AskUserQuestion 询问用户，
                然后调用 events_save / person_note / conversation_thread 更新数据。
    """
    import yaml as _yaml

    feedback_file = os.path.join(_PROJECT_ROOT, "data", "system", "date_feedback.yaml")

    try:
        # 加载已有反馈记录
        data = _load_feedback_file(feedback_file)

        # 构建反馈记录
        now = datetime.now().isoformat(timespec="minutes")
        record = {
            "record_id": f"fb_{now.replace(':', '').replace('-', '')}",
            "time": now,
            "person": name,
            "date_event_id": date_event_id,
            "feedback_text": feedback_text or "",
            "feedback_structured": feedback_structured or {},
            "status": "pending_analysis",  # pending_analysis / analyzed
            "pending_items": _build_pending_items(name, date_event_id),
        }

        # 追加到记录列表
        records = data.setdefault("feedback_records", [])
        records.append(record)
        # 保留最近 200 条
        if len(records) > 200:
            data["feedback_records"] = records[-200:]

        # 保存
        data["last_updated"] = now
        os.makedirs(os.path.dirname(feedback_file), exist_ok=True)
        with open(feedback_file, "w", encoding="utf-8") as f:
            _yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

        return {
            "success": True,
            "record_id": record["record_id"],
            "status": "pending_analysis",
            "pending_items": record["pending_items"],
            "next_step": (
                "Agent 应使用 AskUserQuestion 询问用户约会反馈（参考 pending_items 中的问题），"
                "然后根据用户回答调用 events_save（记录关键事件）、person_note（记录观察要点）、"
                "conversation_thread（更新 key_context 和 her_emotion）。"
                "分析完成后可调用 mark_analyzed 标记此记录已分析。"
            ),
        }
    except Exception as e:
        logger.exception("date_feedback_loop 异常")
        return {"error": "TOOL_ERROR", "message": str(e)}


def mark_analyzed(record_id: str, analysis_summary: str = "") -> dict:
    """标记反馈记录已分析（Agent 完成分析后调用）。

    只更新状态字段，不生成任何分析内容。
    """
    import yaml as _yaml

    feedback_file = os.path.join(_PROJECT_ROOT, "data", "system", "date_feedback.yaml")

    try:
        if not os.path.exists(feedback_file):
            return {"error": "NOT_FOUND", "message": f"反馈记录文件不存在: {record_id}"}

        with open(feedback_file, "r", encoding="utf-8") as f:
            data = _yaml.safe_load(f) or {}

        records = data.get("feedback_records", [])
        found = False
        for r in records:
            if r.get("record_id") == record_id:
                r["status"] = "analyzed"
                r["analyzed_time"] = datetime.now().isoformat(timespec="minutes")
                r["analysis_summary"] = analysis_summary
                found = True
                break

        if not found:
            return {"error": "NOT_FOUND", "message": f"未找到反馈记录: {record_id}"}

        with open(feedback_file, "w", encoding="utf-8") as f:
            _yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

        return {
            "success": True,
            "record_id": record_id,
            "status": "analyzed",
            "message": "已标记为已分析",
        }
    except Exception as e:
        logger.exception("mark_analyzed 异常")
        return {"error": "TOOL_ERROR", "message": str(e)}


def _load_feedback_file(filepath: str) -> dict:
    """加载约会反馈记录文件。"""
    import yaml as _yaml
    if not os.path.exists(filepath):
        return {"feedback_records": [], "last_updated": None}
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = _yaml.safe_load(f) or {}
        if "feedback_records" not in data:
            data["feedback_records"] = []
        return data
    except Exception:
        return {"feedback_records": [], "last_updated": None}


def _build_pending_items(name: str, date_event_id: str) -> list:
    """构建待分析项列表（Agent 应询问用户的问题 + 应更新的数据条目）。

    问题列表来自 v4 10.5 节"约会后询问的关键问题"。
    工具只提供问题模板，不生成分析性内容。
    """
    return [
        {
            "type": "question",
            "question": "整体感觉：约会总体怎么样？（好/一般/不好）",
            "target": "user_input",
        },
        {
            "type": "question",
            "question": "对方反应：她的态度如何？（热情/平淡/冷淡）",
            "target": "user_input",
        },
        {
            "type": "question",
            "question": "关键信号：有没有观察到特别的好感信号或警示信号？",
            "target": "user_input",
        },
        {
            "type": "question",
            "question": "下次意向：还想约第二次吗？（想/不确定/不想）",
            "target": "user_input",
        },
        {
            "type": "data_update",
            "description": "根据用户反馈更新约会记录",
            "target_tool": "events_save",
            "target_action": "记录关键事件（正面/中性/负面）",
        },
        {
            "type": "data_update",
            "description": "记录 Agent 观察和用户反馈要点",
            "target_tool": "person_note",
            "target_action": "添加备注到事实档案",
        },
        {
            "type": "data_update",
            "description": "更新对话线索的关键上下文和对方情绪",
            "target_tool": "conversation_thread",
            "target_action": "update key_context + her_emotion",
        },
        {
            "type": "data_update",
            "description": "如关系阶段可能变化，重新计算阶段",
            "target_tool": "person_stage",
            "target_action": "重新计算关系阶段（Agent 判断是否需要）",
        },
        {
            "type": "wiki_ref",
            "description": "Wiki 依据：第一次约会回来之后 — 黄金窗口 2-6 小时",
            "target_tool": "wiki_context",
            "queries": ["第一次约会回来之后", "约会后如何回访"],
        },
    ]
