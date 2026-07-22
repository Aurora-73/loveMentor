"""手动覆盖学习闭环 MCP 工具（v4 自动回复架构组件）。

本模块实现 v4 文档第十三章规格：手动覆盖学习闭环。
文件路径：data/system/override_learning.yaml

工具契约（v4 23.8 节）：
  - 输入：action（record/query/stats/mark_applied）+ original_draft + final_sent + context
  - 输出：差异分析结果 + 学习规则候选（不直接应用，需 Agent 审核后写入 user_profile_manage）
  - 明确不做：❌ 不自动应用学习规则 ❌ 不决策"下次该怎么回"
              ❌ 不评估用户编辑好坏 ❌ 不做人设推断

设计原则（v4 第十三章）：
  用户可能自己手动回复（用手机），绕过 Agent。这是宝贵的"强化学习"信号。
  工具负责记录差异 + 提供候选学习规则，由 Agent 审核后决定是否应用。
  差异类型：风格差异 / 策略差异 / 内容差异 / 节奏差异。
"""

import os
import sys
import logging
import yaml
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

_OVERRIDE_FILE = os.path.join(_PROJECT_ROOT, "data", "system", "override_learning.yaml")

# 池大小控制
MAX_EVENTS = 500


def override_learning(
    action: str,
    original_draft: Optional[str] = None,
    final_sent: Optional[str] = None,
    context: Optional[dict] = None,
    person: Optional[str] = None,
    event_id: Optional[str] = None,
    time_range_days: int = 30,
) -> dict:
    """手动覆盖学习闭环工具。

    什么时候用：Agent 检测到用户手动回复（绕过 Agent）后，对比 Agent 草案与用户实际发送内容。
    返回什么：record 返回差异分析 + 学习规则候选；query 返回历史事件列表；
              stats 返回统计；mark_applied 返回标记结果。
    边界是什么：不自动应用学习规则；不决策"下次该怎么回"；
                不评估用户编辑好坏；不做人设推断。
    """
    try:
        if action == "record":
            if not original_draft or not final_sent:
                return {"error": "MISSING_PARAM", "message": "record action 需要 original_draft 和 final_sent"}
            return _action_record(original_draft, final_sent, context or {}, person or "")

        elif action == "query":
            return _action_query(person, time_range_days)

        elif action == "stats":
            return _action_stats(time_range_days)

        elif action == "mark_applied":
            if not event_id:
                return {"error": "MISSING_PARAM", "message": "mark_applied action 需要 event_id"}
            return _action_mark_applied(event_id)

        else:
            return {"error": "INVALID_ACTION", "message": f"未知 action: {action}"}

    except Exception as e:
        logger.exception(f"override_learning 异常 {action}")
        return {"error": "TOOL_ERROR", "message": str(e)}


# ── 数据加载/保存 ────────────────────────────────────────────────


def _load_events() -> dict:
    """加载覆盖学习事件文件。"""
    if not os.path.exists(_OVERRIDE_FILE):
        return _empty_data()
    try:
        with open(_OVERRIDE_FILE, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if "override_events" not in data:
            data["override_events"] = []
        return data
    except Exception as e:
        logger.warning(f"override_learning 加载失败: {e}，返回空结构")
        return _empty_data()


def _empty_data() -> dict:
    return {"override_events": [], "last_updated": None}


def _save_events(data: dict) -> None:
    """保存覆盖学习事件文件。"""
    data["last_updated"] = datetime.now().isoformat(timespec="seconds")
    os.makedirs(os.path.dirname(_OVERRIDE_FILE), exist_ok=True)
    with open(_OVERRIDE_FILE, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def _trim_events(events: list) -> list:
    """控制事件池大小。"""
    if len(events) <= MAX_EVENTS:
        return events
    # 保留最新
    events.sort(key=lambda e: e.get("time", ""), reverse=True)
    return events[:MAX_EVENTS]


# ── action 实现 ──────────────────────────────────────────────────


def _action_record(original_draft: str, final_sent: str, context: dict, person: str) -> dict:
    """记录一次覆盖事件并生成差异分析 + 学习规则候选。

    差异分析只做客观对比（长度/关键词/标点），不做语义分析。
    学习规则候选由模板生成，需 Agent 审核后决定是否应用。
    """
    data = _load_events()
    events = data.get("override_events", [])

    # 客观差异分析
    diff_analysis = _analyze_diff(original_draft, final_sent)

    # 生成学习规则候选（模板化，非语义推断）
    learning_candidates = _build_learning_candidates(diff_analysis, person, context)

    event_id = f"ovr_{datetime.now().strftime('%Y%m%d%H%M%S')}_{len(events)}"
    now = datetime.now().isoformat(timespec="minutes")

    event = {
        "event_id": event_id,
        "time": now,
        "person": person,
        "agent_suggestion": original_draft,
        "user_actual": final_sent,
        "context": context,
        "diff_type": diff_analysis["diff_type"],
        "diff_metrics": diff_analysis["metrics"],
        "learning_candidates": learning_candidates,
        "applied": False,
    }

    events.append(event)
    events = _trim_events(events)
    data["override_events"] = events
    _save_events(data)

    return {
        "success": True,
        "action": "record",
        "event_id": event_id,
        "diff_type": diff_analysis["diff_type"],
        "diff_metrics": diff_analysis["metrics"],
        "learning_candidates": learning_candidates,
        "next_step": (
            "Agent 应审核 learning_candidates，决定是否应用。"
            "如应用，调用 user_profile_manage 或 conversation_thread 更新对应数据，"
            "然后调用 mark_applied 标记此事件已处理。"
        ),
    }


def _action_query(person: Optional[str], time_range_days: int) -> dict:
    """查询历史覆盖事件。"""
    data = _load_events()
    events = data.get("override_events", [])

    cutoff = datetime.now() - timedelta(days=time_range_days)
    filtered = []
    for e in events:
        try:
            e_time = datetime.fromisoformat(e.get("time", ""))
            if e_time < cutoff:
                continue
        except (ValueError, TypeError):
            continue
        if person and e.get("person", "") != person:
            continue
        filtered.append(e)

    # 按时间倒序
    filtered.sort(key=lambda e: e.get("time", ""), reverse=True)

    return {
        "action": "query",
        "count": len(filtered),
        "events": filtered[:50],
        "filters": {"person": person, "time_range_days": time_range_days},
    }


def _action_stats(time_range_days: int) -> dict:
    """统计覆盖学习事件（只做客观数据统计，不做归因分析）。"""
    data = _load_events()
    events = data.get("override_events", [])

    cutoff = datetime.now() - timedelta(days=time_range_days)
    in_range = []
    for e in events:
        try:
            e_time = datetime.fromisoformat(e.get("time", ""))
            if e_time >= cutoff:
                in_range.append(e)
        except (ValueError, TypeError):
            continue

    # 按差异类型统计
    type_counts = {}
    applied_count = 0
    for e in in_range:
        dtype = e.get("diff_type", "unknown")
        type_counts[dtype] = type_counts.get(dtype, 0) + 1
        if e.get("applied"):
            applied_count += 1

    # 按联系人统计
    person_counts = {}
    for e in in_range:
        p = e.get("person", "")
        if p:
            person_counts[p] = person_counts.get(p, 0) + 1

    return {
        "action": "stats",
        "total_events": len(in_range),
        "time_range_days": time_range_days,
        "by_diff_type": type_counts,
        "by_person": person_counts,
        "applied_count": applied_count,
        "pending_count": len(in_range) - applied_count,
        "note": "统计只做客观数据汇总，不评估学习效果好坏，不生成优化建议",
    }


def _action_mark_applied(event_id: str) -> dict:
    """标记某个覆盖学习事件已应用（Agent 审核并写入 user_profile_manage 后调用）。"""
    data = _load_events()
    events = data.get("override_events", [])

    found = False
    for e in events:
        if e.get("event_id") == event_id:
            e["applied"] = True
            e["applied_time"] = datetime.now().isoformat(timespec="minutes")
            found = True
            break

    if not found:
        return {"error": "NOT_FOUND", "message": f"未找到 event_id: {event_id}"}

    _save_events(data)

    return {
        "success": True,
        "action": "mark_applied",
        "event_id": event_id,
        "message": "已标记为已应用",
    }


# ── 差异分析（客观对比，非语义分析）────────────────────────────


def _analyze_diff(original: str, final_sent: str) -> dict:
    """客观差异分析（长度/标点/问句/语气词等可量化指标）。

    不做语义相似度计算，不做意图推断。
    diff_type 基于可量化指标粗分，由 Agent 最终判定。
    """
    orig_len = len(original)
    final_len = len(final_sent)

    # 可量化指标
    metrics = {
        "original_length": orig_len,
        "final_length": final_len,
        "length_diff": final_len - orig_len,
        "length_ratio": round(final_len / orig_len, 2) if orig_len > 0 else 0,
        "original_has_question": "?" in original or "？" in original,
        "final_has_question": "?" in final_sent or "？" in final_sent,
        "original_emoji_count": _count_emojis(original),
        "final_emoji_count": _count_emojis(final_sent),
        "original_punctuation_density": _punctuation_density(original),
        "final_punctuation_density": _punctuation_density(final_sent),
        "identical": original.strip() == final_sent.strip(),
    }

    # 粗分差异类型（基于可量化指标，非语义推断）
    if metrics["identical"]:
        diff_type = "identical"
    elif abs(metrics["length_diff"]) > max(orig_len, 10) * 0.5:
        # 长度差异超过 50% → 可能是策略差异
        diff_type = "strategy"
    elif metrics["original_has_question"] != metrics["final_has_question"]:
        # 问句结构改变 → 可能是策略差异
        diff_type = "strategy"
    elif metrics["original_emoji_count"] != metrics["final_emoji_count"]:
        # 表情使用变化 → 可能是风格差异
        diff_type = "style"
    elif metrics["length_ratio"] < 0.5 or metrics["length_ratio"] > 2.0:
        # 长度大幅变化 → 可能是内容差异
        diff_type = "content"
    else:
        # 默认归为风格差异
        diff_type = "style"

    return {"diff_type": diff_type, "metrics": metrics}


def _build_learning_candidates(diff: dict, person: str, context: dict) -> list:
    """基于差异类型生成学习规则候选（模板化，非语义推断）。

    每个候选规则需 Agent 审核后决定是否应用。
    """
    candidates = []
    diff_type = diff["diff_type"]
    metrics = diff["metrics"]

    if diff_type == "identical":
        # 完全相同，无需学习
        return [{
            "candidate_id": "c1",
            "type": "no_action",
            "description": "用户实际发送与 Agent 草案完全一致，委员会标准合适",
            "target_tool": None,
            "applied_action": "无需操作",
        }]

    if diff_type == "style":
        candidates.append({
            "candidate_id": "c1",
            "type": "style",
            "description": f"用户编辑了回复风格（长度变化 {metrics['length_diff']}，表情变化 {metrics['final_emoji_count'] - metrics['original_emoji_count']}）",
            "target_tool": "user_profile_manage",
            "target_action": "update profile_type=style",
            "applied_action": "Agent 审核后更新用户风格画像",
        })

    if diff_type == "strategy":
        candidates.append({
            "candidate_id": "c2",
            "type": "strategy",
            "description": "用户改变了回复策略（问句结构或长度大幅变化）",
            "target_tool": "conversation_thread",
            "target_action": "update strategy_preference",
            "applied_action": f"Agent 审核后更新 {person} 的策略偏好到对话线索",
        })

    if diff_type == "content":
        candidates.append({
            "candidate_id": "c3",
            "type": "content",
            "description": "用户大幅修改了回复内容（可能避免了 Agent 建议的话题）",
            "target_tool": "conversation_thread",
            "target_action": "update landmine_topics",
            "applied_action": "Agent 审核后可能将 Agent 草案中的话题加入 landmine_topics",
        })

    # 通用候选：记录到 conversation_thread
    candidates.append({
        "candidate_id": "c_generic",
        "type": "general",
        "description": "记录此次覆盖事件到对话线索，供后续回复参考",
        "target_tool": "conversation_thread",
        "target_action": "add to override_history",
        "applied_action": "Agent 在 conversation_thread 中记录用户偏好",
    })

    return candidates


# ── 工具函数 ────────────────────────────────────────────────────


def _count_emojis(text: str) -> int:
    """粗略统计 emoji 数量（非 ASCII 可见字符）。"""
    count = 0
    for ch in text:
        if ord(ch) > 0x1F000:  # emoji 范围粗略判断
            count += 1
    return count


def _punctuation_density(text: str) -> float:
    """标点密度（标点字符数 / 总字符数）。"""
    if not text:
        return 0.0
    puncts = sum(1 for ch in text if ch in "，。！？、；：,.!?;:")
    return round(puncts / len(text), 3)
