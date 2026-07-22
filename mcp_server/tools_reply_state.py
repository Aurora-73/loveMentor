"""回复状态管理 MCP 工具（v4 7.7 + 7.8.4 节 — Agent 行为层状态机）。

本模块实现 v4 文档 7.7 节（失败退避策略）+ 7.8.4 节（发送失败重试状态机）。
维护每条回复的状态机（pending/sending/sent/failed/abandoned）+ 连续失败保护。

工具契约：
  - 输入：action（record/update/check_retry/check_suspended/clear_suspended/stats）+ 回复状态参数
  - 输出：状态记录 / 重试判断 / 暂停状态 / 统计数据
  - 明确不做：❌ 不决策"该不该重试"（只提供状态数据和重试上限判断）
              ❌ 不执行重试（由 Agent 调用 wechat_send）
              ❌ 不生成退避策略建议（由 Agent 基于 7.7 节表决策）

数据存储：data/system/reply_states.yaml（单一文件，集中管理）
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

_STATE_FILE = os.path.join(_PROJECT_ROOT, "data", "system", "reply_states.yaml")

# 7.8.4 节：重试上限表
RETRY_LIMITS = {
    "send_error": {"max_retries": 2, "backoff_seconds": 1800, "abandon_action": "notify_user"},
    "committee_reject": {"max_retries": 3, "backoff_seconds": 0, "abandon_action": "skip_wait_next"},
    "hard_constraint": {"max_retries": 1, "backoff_seconds": 0, "abandon_action": "fix_and_retry"},
    "timeout": {"max_retries": 1, "backoff_seconds": 0, "abandon_action": "degrade_retry"},
    "intent_verify": {"max_retries": 0, "backoff_seconds": 0, "abandon_action": "notify_user_no_retry"},
}

# 7.7 节：连续失败保护
CONSECUTIVE_FAILURE_THRESHOLD = 3  # 24h 内连续失败 ≥ 3 次
CONSECUTIVE_FAILURE_WINDOW_HOURS = 24
SUSPEND_DURATION_HOURS = 24  # 暂停 24 小时

# 合法状态值
VALID_STATES = {"pending", "sending", "sent", "failed", "abandoned"}

# 池大小控制
MAX_STATE_RECORDS = 2000


def _load_states() -> dict:
    """加载回复状态文件。"""
    if not os.path.exists(_STATE_FILE):
        return _empty_states()
    try:
        with open(_STATE_FILE, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if "reply_states" not in data:
            data["reply_states"] = []
        if "suspended_contacts" not in data:
            data["suspended_contacts"] = {}
        return data
    except Exception as e:
        logger.warning(f"reply_states 加载失败: {e}，返回空结构")
        return _empty_states()


def _empty_states() -> dict:
    return {"reply_states": [], "suspended_contacts": {}, "last_updated": None}


def _save_states(data: dict) -> None:
    """保存回复状态文件。"""
    data["last_updated"] = datetime.now().isoformat(timespec="seconds")
    os.makedirs(os.path.dirname(_STATE_FILE), exist_ok=True)
    with open(_STATE_FILE, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def _trim_records(records: list) -> list:
    """控制记录池大小。"""
    if len(records) <= MAX_STATE_RECORDS:
        return records
    # 保留 abandoned 和最近 1000 条非 abandoned
    abandoned = [r for r in records if r.get("state") == "abandoned"]
    non_abandoned = [r for r in records if r.get("state") != "abandoned"]
    non_abandoned.sort(key=lambda r: r.get("updated_at", ""), reverse=True)
    return (abandoned + non_abandoned)[:MAX_STATE_RECORDS]


def reply_state_manage(
    action: str,
    message_id: Optional[str] = None,
    person: Optional[str] = None,
    state: Optional[str] = None,
    failure_type: Optional[str] = None,
    failure_reason: Optional[str] = None,
    time_range_days: int = 7,
) -> dict:
    """回复状态管理工具（v4 7.7 + 7.8.4 节）。

    什么时候用：Agent 每次开始回复流程时调 record；发送结果后调 update；
                重试前调 check_retry；轮询前调 check_suspended。
    返回什么：record/update 返回操作结果；check_retry 返回是否可重试 + 退避信息；
              check_suspended 返回是否暂停；stats 返回统计。
    边界是什么：不决策"该不该重试"（只提供状态数据）；不执行重试；不生成退避策略建议。
    """
    try:
        if action == "record":
            if not message_id or not person:
                return {"error": "MISSING_PARAM", "message": "record action 需要 message_id 和 person"}
            return _action_record(message_id, person)

        elif action == "update":
            if not message_id:
                return {"error": "MISSING_PARAM", "message": "update action 需要 message_id"}
            if state and state not in VALID_STATES:
                return {"error": "INVALID_PARAM", "message": f"state 必须是 {sorted(VALID_STATES)} 之一"}
            return _action_update(message_id, state, failure_type, failure_reason or "")

        elif action == "check_retry":
            if not message_id:
                return {"error": "MISSING_PARAM", "message": "check_retry action 需要 message_id"}
            return _action_check_retry(message_id)

        elif action == "check_suspended":
            if not person:
                return {"error": "MISSING_PARAM", "message": "check_suspended action 需要 person"}
            return _action_check_suspended(person)

        elif action == "clear_suspended":
            if not person:
                return {"error": "MISSING_PARAM", "message": "clear_suspended action 需要 person"}
            return _action_clear_suspended(person)

        elif action == "stats":
            return _action_stats(time_range_days, person)

        else:
            return {"error": "INVALID_ACTION", "message": f"未知 action: {action}"}

    except Exception as e:
        logger.exception(f"reply_state_manage 异常 {action}")
        return {"error": "TOOL_ERROR", "message": str(e)}


def _action_record(message_id: str, person: str) -> dict:
    """记录新回复状态（进入回复流程时调用）。"""
    data = _load_states()
    records = data.get("reply_states", [])

    # 检查是否已存在（幂等性）
    for r in records:
        if r.get("message_id") == message_id:
            return {
                "success": True,
                "message": f"回复状态已存在: {message_id}",
                "state": r.get("state"),
                "retry_count": r.get("retry_count", 0),
                "already_exists": True,
            }

    now = datetime.now().isoformat(timespec="seconds")
    record = {
        "message_id": message_id,
        "person": person,
        "state": "pending",
        "retry_count": 0,
        "max_retries": None,  # 由 failure_type 决定
        "last_retry_at": None,
        "failure_type": None,
        "failure_reason": None,
        "consecutive_failures": _count_recent_failures(records, person),
        "created_at": now,
        "updated_at": now,
    }

    records.append(record)
    records = _trim_records(records)
    data["reply_states"] = records
    _save_states(data)

    return {
        "success": True,
        "action": "record",
        "message_id": message_id,
        "state": "pending",
        "consecutive_failures": record["consecutive_failures"],
        "message": f"已记录回复状态（{person}，message_id={message_id}）",
    }


def _action_update(message_id: str, state: Optional[str], failure_type: Optional[str], failure_reason: str) -> dict:
    """更新回复状态（发送结果后调用）。"""
    data = _load_states()
    records = data.get("reply_states", [])

    target = None
    for r in records:
        if r.get("message_id") == message_id:
            target = r
            break

    if not target:
        return {"error": "NOT_FOUND", "message": f"未找到回复状态: {message_id}"}

    now = datetime.now().isoformat(timespec="seconds")

    if state:
        target["state"] = state

    if failure_type:
        if failure_type not in RETRY_LIMITS:
            return {"error": "INVALID_PARAM", "message": f"failure_type 必须是 {sorted(RETRY_LIMITS.keys())} 之一"}
        target["failure_type"] = failure_type
        target["max_retries"] = RETRY_LIMITS[failure_type]["max_retries"]

    if failure_reason:
        target["failure_reason"] = failure_reason

    # 状态转换逻辑
    if state == "failed":
        target["retry_count"] = target.get("retry_count", 0) + 1
        target["last_retry_at"] = now
        # 检查是否达到重试上限
        max_retries = target.get("max_retries", 0) or 0
        if target["retry_count"] >= max_retries + 1:  # +1 因为初始尝试也算
            target["state"] = "abandoned"
            target["abandoned_at"] = now
            target["abandon_action"] = RETRY_LIMITS.get(failure_type, {}).get("abandon_action", "notify_user")

    elif state == "sent":
        # 发送成功，重置连续失败计数
        target["state"] = "sent"
        target["sent_at"] = now

    target["updated_at"] = now

    # 更新连续失败计数（7.7 节）
    if state == "failed" or state == "abandoned":
        _update_consecutive_failures(data, target.get("person", ""), is_failure=True)
    elif state == "sent":
        _update_consecutive_failures(data, target.get("person", ""), is_failure=False)

    _save_states(data)

    result = {
        "success": True,
        "action": "update",
        "message_id": message_id,
        "state": target["state"],
        "retry_count": target.get("retry_count", 0),
        "updated_at": now,
    }

    if target["state"] == "abandoned":
        result["abandoned"] = True
        result["abandon_action"] = target.get("abandon_action", "notify_user")
        result["message"] = f"已放弃重试（{target.get('failure_type', 'unknown')}），建议: {target.get('abandon_action', 'notify_user')}"
    else:
        result["message"] = f"已更新状态为 {target['state']}"

    return result


def _action_check_retry(message_id: str) -> dict:
    """检查是否可以重试（按失败类型上限，7.8.4 节）。"""
    data = _load_states()
    records = data.get("reply_states", [])

    target = None
    for r in records:
        if r.get("message_id") == message_id:
            target = r
            break

    if not target:
        return {"error": "NOT_FOUND", "message": f"未找到回复状态: {message_id}"}

    # 已放弃或已发送，不能重试
    if target.get("state") == "abandoned":
        return {
            "can_retry": False,
            "reason": "已放弃重试",
            "abandon_action": target.get("abandon_action", "notify_user"),
        }
    if target.get("state") == "sent":
        return {"can_retry": False, "reason": "已发送成功"}

    failure_type = target.get("failure_type")
    if not failure_type:
        return {"can_retry": True, "reason": "无失败记录，可重试", "retry_count": target.get("retry_count", 0)}

    limit = RETRY_LIMITS.get(failure_type, {"max_retries": 1, "backoff_seconds": 0})
    retry_count = target.get("retry_count", 0)
    max_retries = limit["max_retries"]

    if retry_count >= max_retries + 1:  # +1 因为初始尝试也算
        return {
            "can_retry": False,
            "reason": f"已达重试上限（{failure_type}: {max_retries} 次）",
            "retry_count": retry_count,
            "max_retries": max_retries,
            "should_abandon": True,
            "abandon_action": limit.get("abandon_action", "notify_user"),
        }

    # 检查退避时间
    backoff = limit.get("backoff_seconds", 0)
    last_retry_str = target.get("last_retry_at")
    if backoff > 0 and last_retry_str:
        try:
            last_retry = datetime.fromisoformat(last_retry_str)
            elapsed = (datetime.now() - last_retry).total_seconds()
            if elapsed < backoff:
                return {
                    "can_retry": False,
                    "reason": f"退避中，还需等待 {backoff - elapsed:.0f} 秒",
                    "retry_count": retry_count,
                    "max_retries": max_retries,
                    "backoff_remaining_seconds": backoff - elapsed,
                }
        except (ValueError, TypeError):
            pass

    return {
        "can_retry": True,
        "reason": f"可重试（{failure_type}: {retry_count}/{max_retries}）",
        "retry_count": retry_count,
        "max_retries": max_retries,
        "backoff_seconds": backoff,
    }


def _action_check_suspended(person: str) -> dict:
    """检查联系人是否被暂停（7.7 节连续失败保护）。"""
    data = _load_states()
    suspended = data.get("suspended_contacts", {})

    info = suspended.get(person)
    if not info:
        return {
            "suspended": False,
            "person": person,
            "reason": "未暂停",
        }

    # 检查暂停是否已过期
    suspended_until = info.get("suspended_until")
    if suspended_until:
        try:
            until_time = datetime.fromisoformat(suspended_until)
            if datetime.now() > until_time:
                # 暂停已过期，自动清除
                del suspended[person]
                _save_states(data)
                return {
                    "suspended": False,
                    "person": person,
                    "reason": "暂停已过期，自动恢复",
                }
        except (ValueError, TypeError):
            pass

    return {
        "suspended": True,
        "person": person,
        "reason": info.get("reason", "连续失败 ≥ 3 次"),
        "suspended_at": info.get("suspended_at"),
        "suspended_until": suspended_until,
        "consecutive_failures": info.get("consecutive_failures", 0),
    }


def _action_clear_suspended(person: str) -> dict:
    """清除暂停状态（用户通过 talk.md 恢复时调用）。"""
    data = _load_states()
    suspended = data.get("suspended_contacts", {})

    if person not in suspended:
        return {"success": True, "message": f"{person} 未被暂停，无需清除"}

    del suspended[person]
    _save_states(data)

    return {"success": True, "message": f"已清除 {person} 的暂停状态，自动回复已恢复"}


def _action_stats(time_range_days: int, person: Optional[str]) -> dict:
    """统计回复状态数据（客观统计，不做归因分析）。"""
    data = _load_states()
    records = data.get("reply_states", [])

    cutoff = datetime.now() - timedelta(days=time_range_days)
    in_range = []
    for r in records:
        try:
            r_time = datetime.fromisoformat(r.get("updated_at", r.get("created_at", "")))
            if r_time < cutoff:
                continue
        except (ValueError, TypeError):
            continue
        if person and r.get("person", "") != person:
            continue
        in_range.append(r)

    total = len(in_range)
    if total == 0:
        return {
            "action": "stats",
            "total_records": 0,
            "time_range_days": time_range_days,
            "person_filter": person,
            "message": "时间范围内无回复状态记录",
        }

    # 按状态统计
    state_counts = {}
    for r in in_range:
        s = r.get("state", "unknown")
        state_counts[s] = state_counts.get(s, 0) + 1

    # 按失败类型统计
    failure_type_counts = {}
    abandoned_records = []
    for r in in_range:
        ft = r.get("failure_type")
        if ft:
            failure_type_counts[ft] = failure_type_counts.get(ft, 0) + 1
        if r.get("state") == "abandoned":
            abandoned_records.append(r)

    # 计算成功率
    sent_count = state_counts.get("sent", 0)
    success_rate = round(sent_count / total, 3) if total > 0 else 0

    # 计算放弃率
    abandoned_count = state_counts.get("abandoned", 0)
    abandon_rate = round(abandoned_count / total, 3) if total > 0 else 0

    # 当前暂停的联系人
    suspended = data.get("suspended_contacts", {})

    return {
        "action": "stats",
        "total_records": total,
        "time_range_days": time_range_days,
        "person_filter": person,
        "state_distribution": state_counts,
        "failure_type_distribution": failure_type_counts,
        "success_rate": success_rate,
        "abandon_rate": abandon_rate,
        "suspended_contacts": list(suspended.keys()),
        "suspended_count": len(suspended),
        "note": "统计只做客观数据汇总，不评估系统好坏，不生成优化建议，不做归因分析",
    }


# ── 工具函数 ────────────────────────────────────────────────────


def _count_recent_failures(records: list, person: str) -> int:
    """统计联系人最近 24h 内的连续失败次数。"""
    cutoff = datetime.now() - timedelta(hours=CONSECUTIVE_FAILURE_WINDOW_HOURS)
    count = 0
    for r in reversed(records):  # 从最近开始
        if r.get("person") != person:
            continue
        try:
            r_time = datetime.fromisoformat(r.get("updated_at", r.get("created_at", "")))
            if r_time < cutoff:
                break
        except (ValueError, TypeError):
            continue
        if r.get("state") in ("failed", "abandoned"):
            count += 1
        elif r.get("state") == "sent":
            break  # 成功，中断连续失败
    return count


def _update_consecutive_failures(data: dict, person: str, is_failure: bool) -> None:
    """更新联系人连续失败计数（7.7 节）。

    is_failure=True: 增加计数，达到阈值则暂停
    is_failure=False: 重置计数
    """
    if not person:
        return

    suspended = data.setdefault("suspended_contacts", {})

    if not is_failure:
        # 发送成功，清除暂停状态（如果有）
        if person in suspended:
            del suspended[person]
        return

    # 失败：检查是否达到暂停阈值
    records = data.get("reply_states", [])
    consecutive = _count_recent_failures(records, person)

    if consecutive >= CONSECUTIVE_FAILURE_THRESHOLD:
        now = datetime.now()
        suspended[person] = {
            "suspended_at": now.isoformat(timespec="seconds"),
            "suspended_until": (now + timedelta(hours=SUSPEND_DURATION_HOURS)).isoformat(timespec="seconds"),
            "consecutive_failures": consecutive,
            "reason": f"24h 内连续失败 {consecutive} 次（≥ {CONSECUTIVE_FAILURE_THRESHOLD}）",
        }
        logger.warning(f"联系人 {person} 已暂停自动回复（连续失败 {consecutive} 次）")
