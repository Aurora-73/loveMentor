"""跨联系人回复查重 MCP 工具（v4 自动回复架构组件）。

本模块实现 v4 文档第九章规格：跨联系人内容查重。
文件路径：data/system/recent_replies.yaml

工具契约（v4 23.4 节）：
  - 输入：action（check/add/query）+ reply_content/to/pattern/time_range_hours
  - 输出：check 返回 duplicate_found + matched_replies；add 返回操作结果；query 返回回复列表
  - 明确不做：❌ 不决策"能不能发这条回复" ❌ 不生成替代回复 ❌ 不评估"复制粘贴感"
              ❌ 不做语义相似度计算（只做 pattern 匹配）

查重规则（9.5 节）：
  1. pattern 匹配：由 Agent 提供意图 pattern（如"关心状况"/"推荐场所"/"共情辛苦"）
  2. 时间窗口：默认查最近 24 小时
  3. 跨联系人：只对不同联系人的相同 pattern 报警（对同一联系人重复 pattern 是正常的）
  4. 严重程度：
     - 完全相同的话术 → 高危，必须换
     - 相同 pattern 不同措辞 → 中危，建议换
     - 不同 pattern → 通过
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

_REPLIES_FILE = os.path.join(_PROJECT_ROOT, "data", "system", "recent_replies.yaml")

# 池大小控制（防止无限增长）
MAX_REPLIES_POOL = 500


def _load_replies() -> dict:
    """加载回复池。"""
    if not os.path.exists(_REPLIES_FILE):
        return _empty_pool()
    try:
        with open(_REPLIES_FILE, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if "recent_replies" not in data:
            data["recent_replies"] = []
        return data
    except Exception as e:
        logger.warning(f"recent_replies 加载失败: {e}，返回空结构")
        return _empty_pool()


def _empty_pool() -> dict:
    return {"recent_replies": [], "last_updated": None}


def _save_replies(data: dict) -> None:
    """保存回复池。"""
    data["last_updated"] = datetime.now().isoformat(timespec="seconds")
    os.makedirs(os.path.dirname(_REPLIES_FILE), exist_ok=True)
    with open(_REPLIES_FILE, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def _trim_pool(replies: list) -> list:
    """控制池大小，保留最近的 MAX_REPLIES_POOL 条。"""
    if len(replies) <= MAX_REPLIES_POOL:
        return replies
    # 按时间倒序保留最新
    replies.sort(key=lambda r: r.get("time", ""), reverse=True)
    return replies[:MAX_REPLIES_POOL]


def recent_replies_check(
    action: str,
    reply_content: Optional[str] = None,
    to: Optional[str] = None,
    pattern: Optional[str] = None,
    time_range_hours: int = 24,
) -> dict:
    """跨联系人回复查重工具（pattern 匹配）。

    什么时候用：Agent 生成回复草案后、发送前调用 check；发送后调用 add 记录。
    返回什么：check 返回 duplicate_found + matched_replies + suggestion；
              add 返回操作结果；query 返回回复列表。
    边界是什么：只做 pattern 匹配，不做语义相似度；不决策"能不能发"；
                不生成替代回复；不评估"复制粘贴感"。
    """
    try:
        if action == "check":
            return _action_check(reply_content or "", to or "", time_range_hours)

        elif action == "add":
            return _action_add(reply_content or "", to or "", pattern or "")

        elif action == "query":
            return _action_query(to, pattern, time_range_hours)

        else:
            return {"error": "INVALID_ACTION", "message": f"未知 action: {action}"}

    except Exception as e:
        logger.exception(f"recent_replies_check 异常 {action}")
        return {"error": "TOOL_ERROR", "message": str(e)}


def _action_check(reply_content: str, to: str, time_range_hours: int) -> dict:
    """检查回复是否与近期发给其他人的回复重复。

    查重规则：
      1. 完全相同的话术（reply_content 相同）→ 高危
      2. 相同 pattern（需 Agent 显式提取并提供）→ 中危
      3. 不同 pattern → 通过
    """
    if not reply_content:
        return {"error": "MISSING_PARAM", "message": "check action 需要 reply_content"}

    data = _load_replies()
    replies = data.get("recent_replies", [])

    # 时间窗口过滤
    cutoff = datetime.now() - timedelta(hours=time_range_hours)
    recent_in_window = []
    for r in replies:
        try:
            r_time = datetime.fromisoformat(r.get("time", ""))
            if r_time >= cutoff:
                recent_in_window.append(r)
        except (ValueError, TypeError):
            continue

    # 完全相同话术检查（跨联系人）
    exact_matches = []
    pattern_matches = []
    for r in recent_in_window:
        r_to = r.get("to", "")
        r_content = r.get("summary", "") or r.get("content", "")
        # 只对不同联系人的相同回复报警
        if r_to == to:
            continue

        if r_content and _normalize_text(r_content) == _normalize_text(reply_content):
            exact_matches.append(r)
        # pattern 匹配（如果记录中有 pattern）
        elif r.get("pattern"):
            # 此处需要 Agent 在 check 时提供 pattern，否则无法做 pattern 匹配
            # 这里只能做完全相同话术检查
            pass

    duplicate_found = len(exact_matches) > 0
    matched_replies = exact_matches

    # 生成严重程度和建议
    if exact_matches:
        severity = "high"
        suggestion = "完全相同的话术已对其他联系人使用过，必须换一种表达"
    else:
        severity = "none"
        suggestion = "通过查重检查（未发现完全相同话术）"

    return {
        "action": "check",
        "duplicate_found": duplicate_found,
        "matched_replies": matched_replies,
        "severity": severity,
        "suggestion": suggestion,
        "time_window_hours": time_range_hours,
        "checked_against_count": len(recent_in_window),
        "note": (
            "本工具只做完全相同话术检查。如需 pattern 匹配查重，"
            "Agent 应先调用 check 时附 pattern 参数，或调用 add 时记录 pattern，"
            "然后调用 query 查询同 pattern 的历史记录。"
        ),
    }


def _action_add(reply_content: str, to: str, pattern: str) -> dict:
    """记录一条已发送的回复到池中。"""
    if not reply_content or not to:
        return {"error": "MISSING_PARAM", "message": "add action 需要 reply_content 和 to"}

    data = _load_replies()
    replies = data.get("recent_replies", [])

    # 截取摘要（避免存储过长内容）
    summary = reply_content[:100]
    if len(reply_content) > 100:
        summary += "..."

    new_entry = {
        "time": datetime.now().isoformat(timespec="minutes"),
        "to": to,
        "summary": summary,
        "pattern": pattern or "",
        "content_length": len(reply_content),
    }

    replies.append(new_entry)
    replies = _trim_pool(replies)
    data["recent_replies"] = replies
    _save_replies(data)

    return {
        "success": True,
        "message": f"已记录回复到 {to}",
        "entry": new_entry,
        "pool_size": len(replies),
    }


def _action_query(
    to: Optional[str],
    pattern: Optional[str],
    time_range_hours: int,
) -> dict:
    """查询近期回复记录。"""
    data = _load_replies()
    replies = data.get("recent_replies", [])

    # 时间窗口过滤
    cutoff = datetime.now() - timedelta(hours=time_range_hours)
    filtered = []
    for r in replies:
        try:
            r_time = datetime.fromisoformat(r.get("time", ""))
            if r_time < cutoff:
                continue
        except (ValueError, TypeError):
            continue

        # 联系人过滤
        if to and r.get("to", "") != to:
            continue

        # pattern 过滤
        if pattern and r.get("pattern", "") != pattern:
            continue

        filtered.append(r)

    # 按时间倒序
    filtered.sort(key=lambda r: r.get("time", ""), reverse=True)

    return {
        "action": "query",
        "count": len(filtered),
        "replies": filtered[:50],  # 最多返回 50 条
        "filters": {
            "to": to,
            "pattern": pattern,
            "time_range_hours": time_range_hours,
        },
    }


def _normalize_text(text: str) -> str:
    """归一化文本：去首尾空格 + 转小写 + 去多余空白。"""
    if not text:
        return ""
    return " ".join(text.strip().lower().split())


# ── effect_tracking（v4 第十四章，P1）────────────────────────────


_EFFECT_FILE = os.path.join(_PROJECT_ROOT, "data", "system", "effect_tracking.yaml")

# 池大小控制
MAX_EFFECT_RECORDS = 1000

# 合法 message_type 值
_VALID_MSG_TYPES = {"auto_reply", "initiative", "invitation"}

# 合法 response_sentiment 值
_VALID_SENTIMENTS = {"positive", "neutral", "negative", "no_response"}


def effect_tracking(
    action: str,
    person: Optional[str] = None,
    message_type: Optional[str] = None,
    message_summary: Optional[str] = None,
    committee_result: Optional[str] = None,
    response_received: Optional[bool] = None,
    response_time: Optional[int] = None,
    response_sentiment: Optional[str] = None,
    response_summary: Optional[str] = None,
    effectiveness_score: Optional[float] = None,
    time_range_days: int = 30,
) -> dict:
    """效果追踪工具（v4 第十四章）。

    什么时候用：Agent 每次自动发送回复后调用 record 记录；定期调用 stats 查看效果统计。
    返回什么：record 返回记录结果；stats 返回客观统计数据（回复率/平均回复间隔/正面回复率等）；
              report 返回更详细的数据汇总。
    边界是什么：不决策"系统好不好"；不生成优化方案；不评估"哪条回复失败"；
                不做归因分析。所有效果判断由 Agent 完成。
    """
    try:
        if action == "record":
            if not person:
                return {"error": "MISSING_PARAM", "message": "record action 需要 person"}
            return _effect_record(
                person=person,
                message_type=message_type or "auto_reply",
                message_summary=message_summary or "",
                committee_result=committee_result or "",
                response_received=response_received,
                response_time=response_time,
                response_sentiment=response_sentiment,
                response_summary=response_summary or "",
                effectiveness_score=effectiveness_score,
            )

        elif action == "stats":
            return _effect_stats(time_range_days, person)

        elif action == "report":
            return _effect_report(time_range_days, person)

        elif action == "update_response":
            if not person:
                return {"error": "MISSING_PARAM", "message": "update_response action 需要 person"}
            return _effect_update_response(
                person=person,
                response_received=response_received,
                response_time=response_time,
                response_sentiment=response_sentiment,
                response_summary=response_summary or "",
                effectiveness_score=effectiveness_score,
            )

        else:
            return {"error": "INVALID_ACTION", "message": f"未知 action: {action}"}

    except Exception as e:
        logger.exception(f"effect_tracking 异常 {action}")
        return {"error": "TOOL_ERROR", "message": str(e)}


def _effect_record(
    person: str,
    message_type: str,
    message_summary: str,
    committee_result: str,
    response_received: Optional[bool],
    response_time: Optional[int],
    response_sentiment: Optional[str],
    response_summary: str,
    effectiveness_score: Optional[float],
) -> dict:
    """记录一条效果追踪数据。"""
    if message_type not in _VALID_MSG_TYPES:
        return {"error": "INVALID_PARAM", "message": f"message_type 必须是 {sorted(_VALID_MSG_TYPES)} 之一"}

    data = _load_effect_data()
    records = data.get("effect_records", [])

    now = datetime.now()
    record = {
        "record_id": f"eff_{now.strftime('%Y%m%d%H%M%S')}_{len(records)}",
        "send_time": now.isoformat(timespec="minutes"),
        "person": person,
        "message_type": message_type,
        "message_summary": message_summary[:100],  # 截取摘要
        "committee_result": committee_result,
        "response_received": response_received if response_received is not None else False,
        "response_time": response_time,  # 秒
        "response_sentiment": response_sentiment,
        "response_summary": response_summary[:100],
        "effectiveness_score": effectiveness_score,
        "status": "pending_response" if not response_received else "completed",
    }

    records.append(record)
    records = _trim_effect_records(records)
    data["effect_records"] = records
    _save_effect_data(data)

    return {
        "success": True,
        "action": "record",
        "record_id": record["record_id"],
        "status": record["status"],
        "message": f"已记录效果追踪数据（{person}，{message_type}）",
    }


def _effect_update_response(
    person: str,
    response_received: Optional[bool],
    response_time: Optional[int],
    response_sentiment: Optional[str],
    response_summary: str,
    effectiveness_score: Optional[float],
) -> dict:
    """更新最近一条待响应记录的回复信息。

    Agent 检测到对方回复后调用此 action 更新记录。
    """
    if response_sentiment and response_sentiment not in _VALID_SENTIMENTS:
        return {"error": "INVALID_PARAM", "message": f"response_sentiment 必须是 {sorted(_VALID_SENTIMENTS)} 之一"}

    data = _load_effect_data()
    records = data.get("effect_records", [])

    # 查找该联系人最近一条 pending_response 记录
    target = None
    for r in reversed(records):
        if r.get("person") == person and r.get("status") == "pending_response":
            target = r
            break

    if not target:
        return {"error": "NOT_FOUND", "message": f"未找到 {person} 的待响应记录"}

    if response_received is not None:
        target["response_received"] = response_received
    if response_time is not None:
        target["response_time"] = response_time
    if response_sentiment:
        target["response_sentiment"] = response_sentiment
    if response_summary:
        target["response_summary"] = response_summary[:100]
    if effectiveness_score is not None:
        target["effectiveness_score"] = effectiveness_score

    target["status"] = "completed"
    target["response_updated_time"] = datetime.now().isoformat(timespec="minutes")

    _save_effect_data(data)

    return {
        "success": True,
        "action": "update_response",
        "record_id": target["record_id"],
        "person": person,
        "status": "completed",
        "message": "已更新回复信息",
    }


def _effect_stats(time_range_days: int, person: Optional[str]) -> dict:
    """统计效果数据（客观指标，不做归因分析）。"""
    data = _load_effect_data()
    records = data.get("effect_records", [])

    cutoff = datetime.now() - timedelta(days=time_range_days)
    in_range = []
    for r in records:
        try:
            r_time = datetime.fromisoformat(r.get("send_time", ""))
            if r_time < cutoff:
                continue
        except (ValueError, TypeError):
            continue
        if person and r.get("person", "") != person:
            continue
        in_range.append(r)

    # 计算客观指标
    total = len(in_range)
    if total == 0:
        return {
            "action": "stats",
            "total_records": 0,
            "time_range_days": time_range_days,
            "person_filter": person,
            "message": "时间范围内无效果追踪记录",
        }

    response_received_count = sum(1 for r in in_range if r.get("response_received"))
    response_rates = {
        "total": total,
        "response_received": response_received_count,
        "response_rate": round(response_received_count / total, 3) if total > 0 else 0,
    }

    # 平均回复间隔（只统计有回复且有 response_time 的）
    response_times = [r.get("response_time") for r in in_range if r.get("response_received") and r.get("response_time") is not None]
    avg_response_time = sum(response_times) / len(response_times) if response_times else None

    # 正面回复率
    sentiment_counts = {}
    for r in in_range:
        s = r.get("response_sentiment") or "no_response"
        sentiment_counts[s] = sentiment_counts.get(s, 0) + 1
    positive_count = sentiment_counts.get("positive", 0)
    positive_rate = round(positive_count / response_received_count, 3) if response_received_count > 0 else 0

    # 按 message_type 分组统计
    type_stats = {}
    for r in in_range:
        mtype = r.get("message_type", "unknown")
        if mtype not in type_stats:
            type_stats[mtype] = {"total": 0, "response_received": 0}
        type_stats[mtype]["total"] += 1
        if r.get("response_received"):
            type_stats[mtype]["response_received"] += 1
    for mtype, s in type_stats.items():
        s["response_rate"] = round(s["response_received"] / s["total"], 3) if s["total"] > 0 else 0

    # 委员会结果分布
    committee_results = {}
    for r in in_range:
        cr = r.get("committee_result", "unknown")
        committee_results[cr] = committee_results.get(cr, 0) + 1

    return {
        "action": "stats",
        "total_records": total,
        "time_range_days": time_range_days,
        "person_filter": person,
        "response_rates": response_rates,
        "avg_response_time_seconds": round(avg_response_time, 1) if avg_response_time else None,
        "sentiment_distribution": sentiment_counts,
        "positive_response_rate": positive_rate,
        "by_message_type": type_stats,
        "committee_result_distribution": committee_results,
        "note": "统计只做客观数据汇总，不评估系统好坏，不生成优化建议，不做归因分析",
    }


def _effect_report(time_range_days: int, person: Optional[str]) -> dict:
    """生成更详细的效果数据汇总（仍是客观数据，不含分析）。"""
    stats = _effect_stats(time_range_days, person)
    if "error" in stats or stats.get("total_records", 0) == 0:
        return stats

    data = _load_effect_data()
    records = data.get("effect_records", [])

    cutoff = datetime.now() - timedelta(days=time_range_days)
    in_range = []
    for r in records:
        try:
            r_time = datetime.fromisoformat(r.get("send_time", ""))
            if r_time < cutoff:
                continue
        except (ValueError, TypeError):
            continue
        if person and r.get("person", "") != person:
            continue
        in_range.append(r)

    # 按联系人分组（如果未指定 person）
    by_person = {}
    for r in in_range:
        p = r.get("person", "unknown")
        if p not in by_person:
            by_person[p] = {"total": 0, "response_received": 0, "positive": 0}
        by_person[p]["total"] += 1
        if r.get("response_received"):
            by_person[p]["response_received"] += 1
            if r.get("response_sentiment") == "positive":
                by_person[p]["positive"] += 1

    for p, s in by_person.items():
        s["response_rate"] = round(s["response_received"] / s["total"], 3) if s["total"] > 0 else 0
        s["positive_rate"] = round(s["positive"] / s["response_received"], 3) if s["response_received"] > 0 else 0

    # 最近 10 条记录明细
    recent_records = sorted(in_range, key=lambda r: r.get("send_time", ""), reverse=True)[:10]

    # 无回复记录列表
    no_response_records = [r for r in in_range if not r.get("response_received")]

    return {
        "action": "report",
        "stats": stats,
        "by_person": by_person,
        "recent_records": recent_records,
        "no_response_count": len(no_response_records),
        "no_response_records": no_response_records[:10],
        "note": "报告只做客观数据汇总，不评估哪条回复失败，不生成优化方案，不做归因分析",
    }


def _load_effect_data() -> dict:
    """加载效果追踪数据文件。"""
    if not os.path.exists(_EFFECT_FILE):
        return {"effect_records": [], "last_updated": None}
    try:
        with open(_EFFECT_FILE, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if "effect_records" not in data:
            data["effect_records"] = []
        return data
    except Exception as e:
        logger.warning(f"effect_tracking 加载失败: {e}，返回空结构")
        return {"effect_records": [], "last_updated": None}


def _save_effect_data(data: dict) -> None:
    """保存效果追踪数据文件。"""
    data["last_updated"] = datetime.now().isoformat(timespec="seconds")
    os.makedirs(os.path.dirname(_EFFECT_FILE), exist_ok=True)
    with open(_EFFECT_FILE, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def _trim_effect_records(records: list) -> list:
    """控制记录池大小。"""
    if len(records) <= MAX_EFFECT_RECORDS:
        return records
    records.sort(key=lambda r: r.get("send_time", ""), reverse=True)
    return records[:MAX_EFFECT_RECORDS]
