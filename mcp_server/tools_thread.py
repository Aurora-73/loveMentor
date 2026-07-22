"""对话线索管理 MCP 工具（v4 自动回复架构核心组件）。

本模块实现 v4 文档第六章规格：对话线索管理。
每个联系人独立一个线索文件 data/conversation_threads/<person_id>.yaml。

工具层硬约束（6.4 节）：wechat_send 发送前校验线索已读 + 回复冷却。
本工具只做 CRUD，不判断"该不该回复"等语义决策（23.1 节契约）。
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

_THREADS_DIR = os.path.join(_PROJECT_ROOT, "data", "conversation_threads")

# 线索大小控制（6.11 节）
MAX_RECENT_SUMMARY = 20
MAX_CURRENT_THREADS = 5
MAX_KEY_CONTEXT = 10
MAX_EMOTION_TRAJECTORY = 5

# 过期阈值（小时，6.6 节）
STAGE_EXPIRY_HOURS = {
    1: 12,  # Stage 1 初识
    2: 12,  # Stage 2 基本互动
    3: 6,   # Stage 3 高频聊天
    4: 3,   # Stage 4 已约见
    5: 3,   # Stage 5+ 持续接触
}


def _resolve_person_id(name: str) -> str:
    """解析联系人名称 → person_id（用于文件命名）。"""
    from engine.tools import _resolve
    conn, config, person = _resolve(name)
    conn.close()
    return person.id


def _thread_path(person_id: str) -> str:
    """线索文件路径。"""
    return os.path.join(_THREADS_DIR, f"{person_id}.yaml")


def _load_thread(person_id: str) -> dict:
    """加载线索文件，不存在则返回空结构。"""
    path = _thread_path(person_id)
    if not os.path.exists(path):
        return _empty_thread()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        # 确保必要字段存在
        return _normalize_thread(data)
    except Exception as e:
        logger.warning(f"线索文件加载失败 {person_id}: {e}，返回空结构")
        return _empty_thread()


def _empty_thread() -> dict:
    """空线索结构。"""
    return {
        "version": 0,
        "last_updated": None,
        "last_message_id": 0,
        "last_message_time": None,
        "last_processed_message_id": 0,
        "user_took_over": False,
        "user_took_over_time": None,  # 7.8.2 节：用户接管时间戳
        "processed_message_ids": [],
        "recent_summary": [],
        "current_threads": [],
        "pending_items": [],
        "her_emotion": {"trajectory": [], "trend": "unknown", "current_state": "unknown", "last_updated": None},
        "landmine_topics": [],
        "avoid_topics": [],
        "key_context": [],
        "initiative_tracker": {
            "last_5_initiatives": [],
            "my_initiative_ratio": 0.0,
            "target": "0.4-0.5",
            "status": "unknown",
        },
    }


def _normalize_thread(data: dict) -> dict:
    """确保线索结构完整。"""
    empty = _empty_thread()
    for key, default_val in empty.items():
        if key not in data:
            data[key] = default_val
        elif isinstance(default_val, dict) and isinstance(data[key], dict):
            for sub_key, sub_val in default_val.items():
                if sub_key not in data[key]:
                    data[key][sub_key] = sub_val
    return data


def _save_thread(person_id: str, thread: dict) -> None:
    """保存线索文件。"""
    path = _thread_path(person_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    thread["last_updated"] = datetime.now().isoformat(timespec="seconds")
    thread["version"] = thread.get("version", 0) + 1
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(thread, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def _trim_lists(thread: dict) -> None:
    """线索大小控制（6.11 节）。"""
    if len(thread.get("recent_summary", [])) > MAX_RECENT_SUMMARY:
        thread["recent_summary"] = thread["recent_summary"][-MAX_RECENT_SUMMARY:]
    if len(thread.get("current_threads", [])) > MAX_CURRENT_THREADS:
        thread["current_threads"] = thread["current_threads"][-MAX_CURRENT_THREADS:]
    if len(thread.get("key_context", [])) > MAX_KEY_CONTEXT:
        thread["key_context"] = thread["key_context"][-MAX_KEY_CONTEXT:]
    emotion = thread.get("her_emotion", {})
    if len(emotion.get("trajectory", [])) > MAX_EMOTION_TRAJECTORY:
        emotion["trajectory"] = emotion["trajectory"][-MAX_EMOTION_TRAJECTORY:]
    # processed_message_ids 保留最近 7 天（7.8.1 节）
    # 工程近似：限制 1000 条（按日均 100 条消息估算，约覆盖 7-10 天）
    # 如需精确按时间清理，可改为按 timestamp 字段过滤 7 天前的记录
    pids = thread.get("processed_message_ids", [])
    if len(pids) > 1000:
        thread["processed_message_ids"] = pids[-1000:]


def conversation_thread(
    action: str,
    name: str,
    summary: Optional[dict] = None,
    update_fields: Optional[dict] = None,
    current_stage: int = 3,
    landmine: Optional[dict] = None,
    avoid_topic: Optional[str] = None,
    last_message_id: Optional[int] = None,
    last_message_time: Optional[str] = None,
    expected_version: Optional[int] = None,
) -> dict:
    """对话线索管理工具。

    什么时候用：自动回复前必读线索，回复后更新线索。
    返回什么：get 返回完整线索；check_expired 返回过期状态；其他 action 返回操作结果。
    边界是什么：只做 CRUD，不判断"该不该回复""对方什么意思"等语义决策。
    """
    try:
        person_id = _resolve_person_id(name)
    except Exception as e:
        return {"error": "RESOLVE_FAILED", "message": f"无法解析联系人: {e}"}

    try:
        if action == "get":
            return _action_get(person_id)

        elif action == "update":
            return _action_update(person_id, update_fields or {}, expected_version)

        elif action == "append_summary":
            return _action_append_summary(person_id, summary or {})

        elif action == "clear":
            return _action_clear(person_id)

        elif action == "check_expired":
            return _action_check_expired(person_id, current_stage)

        elif action == "catch_up":
            return _action_catch_up(person_id, last_message_id, last_message_time)

        elif action == "add_landmine":
            return _action_add_landmine(person_id, landmine or {})

        elif action == "add_avoid_topic":
            return _action_add_avoid_topic(person_id, avoid_topic or "")

        elif action == "clear_cancel_flag":
            return _action_clear_cancel_flag(person_id)

        else:
            return {"error": "INVALID_ACTION", "message": f"未知 action: {action}"}

    except Exception as e:
        logger.exception(f"conversation_thread 异常 {action} {name}")
        return {"error": "TOOL_ERROR", "message": str(e)}


def _action_get(person_id: str) -> dict:
    """读取完整线索。"""
    thread = _load_thread(person_id)
    return {"success": True, "thread": thread}


def _action_update(person_id: str, updates: dict, expected_version: Optional[int]) -> dict:
    """更新线索字段（乐观锁，7.8.3 节）。

    版本冲突处理：
    1. expected_version 匹配 → 直接更新
    2. expected_version 不匹配 → 字段级合并，最多重试 3 次
    3. 3 次仍冲突 → 强制写入 + 记录冲突日志
    """
    MAX_CONFLICT_RETRIES = 3  # 7.8.3 节：最多重试 3 次

    thread = _load_thread(person_id)
    current_version = thread.get("version", 0)

    # 乐观锁校验
    if expected_version is not None and expected_version != current_version:
        # 版本冲突，执行字段级合并（最多重试 3 次）
        conflict_count = 0
        merged = thread
        for attempt in range(1, MAX_CONFLICT_RETRIES + 1):
            merged = _merge_fields(merged, updates)
            _trim_lists(merged)
            # 重新读取检查版本是否变化
            fresh = _load_thread(person_id)
            if fresh.get("version", 0) == current_version:
                # 版本未变，可以安全写入
                break
            else:
                # 版本又变了，再次合并
                conflict_count += 1
                merged = _merge_fields(fresh, merged)
                current_version = fresh.get("version", 0)
                if attempt == MAX_CONFLICT_RETRIES:
                    # 3 次仍冲突，强制写入 + 记录冲突日志
                    _log_thread_conflict(person_id, updates, expected_version, current_version, conflict_count)
                    _save_thread(person_id, merged)
                    return {
                        "success": True,
                        "message": f"版本冲突 {conflict_count} 次，已强制写入并记录冲突日志",
                        "version": merged["version"],
                        "conflict_resolved": True,
                        "conflict_count": conflict_count,
                        "forced_write": True,
                    }

        _save_thread(person_id, merged)
        return {
            "success": True,
            "message": "版本冲突，已执行字段级合并",
            "version": merged["version"],
            "conflict_resolved": True,
            "conflict_count": conflict_count,
        }

    # 版本匹配，直接更新
    for key, value in updates.items():
        if key in ("recent_summary", "current_threads", "key_context", "landmine_topics", "avoid_topics", "pending_items"):
            # 列表字段：追加模式
            existing = thread.get(key, [])
            if isinstance(value, list):
                existing.extend(value)
            else:
                existing.append(value)
            thread[key] = existing
        elif key == "her_emotion":
            # 嵌套字典：字段级合并
            for sub_key, sub_val in value.items():
                if sub_key == "trajectory" and isinstance(sub_val, list):
                    thread["her_emotion"]["trajectory"].extend(sub_val)
                else:
                    thread["her_emotion"][sub_key] = sub_val
        elif key in ("last_message_id", "last_message_time", "last_processed_message_id"):
            thread[key] = value
        elif key == "initiative_tracker":
            for sub_key, sub_val in value.items():
                thread["initiative_tracker"][sub_key] = sub_val
        elif key == "user_took_over":
            thread["user_took_over"] = value
            # 7.8.2 节：同步记录接管时间戳
            if value:
                thread["user_took_over_time"] = datetime.now().isoformat(timespec="seconds")
            else:
                thread["user_took_over_time"] = None
        else:
            thread[key] = value

    _trim_lists(thread)
    _save_thread(person_id, thread)
    return {"success": True, "message": "线索已更新", "version": thread["version"]}


def _log_thread_conflict(person_id: str, updates: dict, expected_version: int, actual_version: int, conflict_count: int) -> None:
    """记录版本冲突日志（7.8.3 节，3 次仍冲突时调用）。"""
    import json
    log_file = os.path.join(_PROJECT_ROOT, "data", "system", "thread_conflicts.log")
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    log_entry = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "person_id": person_id,
        "expected_version": expected_version,
        "actual_version": actual_version,
        "conflict_count": conflict_count,
        "conflict_fields": list(updates.keys()),
    }
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")


def _merge_fields(current: dict, updates: dict) -> dict:
    """字段级合并（7.8.3 节）。

    合并规则：
    - recent_summary / current_threads / key_context：追加模式（不覆盖）
    - her_emotion：trajectory 追加去重，current_state/trend 按 last_updated 取最新
    - initiative_tracker：按 last_updated 取最新（若有）
    - landmine_topics / avoid_topics：并集（去重）
    - pending_items：按 item_id（或 description）去重合并
    """
    merged = dict(current)
    for key, value in updates.items():
        if key in ("recent_summary", "current_threads", "key_context", "landmine_topics", "avoid_topics"):
            existing = merged.get(key, [])
            if isinstance(value, list):
                for item in value:
                    if item not in existing:
                        existing.append(item)
            elif value not in existing:
                existing.append(value)
            merged[key] = existing
        elif key == "pending_items":
            # 7.8.3 节：按 item_id（或 description）去重合并
            existing = merged.get(key, [])
            if isinstance(value, list):
                for item in value:
                    _dedup_append(existing, item, key_fields=("item_id", "description"))
            elif value not in existing:
                _dedup_append(existing, value, key_fields=("item_id", "description"))
            merged[key] = existing
        elif key == "her_emotion":
            # 7.8.3 节：trajectory 追加去重，current_state/trend 按 last_updated 取最新
            for sub_key, sub_val in value.items():
                if sub_key == "trajectory" and isinstance(sub_val, list):
                    for item in sub_val:
                        if item not in merged["her_emotion"]["trajectory"]:
                            merged["her_emotion"]["trajectory"].append(item)
                elif sub_key == "last_updated":
                    # 比较 last_updated，取最新
                    current_updated = merged["her_emotion"].get("last_updated")
                    if current_updated is None or (sub_val and sub_val > current_updated):
                        merged["her_emotion"]["last_updated"] = sub_val
                        # last_updated 更新时，同步取 updates 中的 current_state/trend
                        if "current_state" in value:
                            merged["her_emotion"]["current_state"] = value["current_state"]
                        if "trend" in value:
                            merged["her_emotion"]["trend"] = value["trend"]
                else:
                    # current_state/trend：只有当 last_updated 更新时才覆盖（上面已处理）
                    # 如果 updates 中没有 last_updated，直接覆盖（兼容旧调用）
                    if "last_updated" not in value:
                        merged["her_emotion"][sub_key] = sub_val
        elif key == "initiative_tracker":
            # 7.8.3 节：按 last_updated 取最新（若有）
            current_updated = merged.get("initiative_tracker", {}).get("last_updated")
            new_updated = value.get("last_updated") if isinstance(value, dict) else None
            if current_updated is None or (new_updated and new_updated > current_updated):
                merged["initiative_tracker"] = value
            # 如果没有 last_updated，按字段级合并
            elif isinstance(value, dict):
                for sub_key, sub_val in value.items():
                    merged["initiative_tracker"][sub_key] = sub_val
        else:
            merged[key] = value
    return merged


def _dedup_append(lst: list, item, key_fields: tuple) -> None:
    """按 key_fields 去重追加。item 是 dict 时按 key_fields 去重，否则按值去重。"""
    if isinstance(item, dict):
        # 提取去重键值
        for kf in key_fields:
            if kf in item:
                # 检查是否已存在相同键值的项
                for existing in lst:
                    if isinstance(existing, dict) and existing.get(kf) == item.get(kf):
                        # 已存在，用新项覆盖旧项（取最新）
                        lst[lst.index(existing)] = item
                        return
                # 不存在，追加
                lst.append(item)
                return
        # 没有匹配的 key_fields，按整个 dict 去重
        if item not in lst:
            lst.append(item)
    else:
        if item not in lst:
            lst.append(item)


def _action_append_summary(person_id: str, summary: dict) -> dict:
    """追加对话摘要。"""
    if not summary:
        return {"error": "INVALID_PARAMS", "message": "summary 不能为空"}
    thread = _load_thread(person_id)
    thread["recent_summary"].append({
        "time": summary.get("time", datetime.now().isoformat(timespec="minutes")),
        "who": summary.get("who", "unknown"),
        "summary": summary.get("summary", ""),
    })
    _trim_lists(thread)
    _save_thread(person_id, thread)
    return {"success": True, "message": "摘要已追加", "total_summaries": len(thread["recent_summary"])}


def _action_clear(person_id: str) -> dict:
    """清空线索（保留 landmine_topics 和 avoid_topics）。"""
    thread = _load_thread(person_id)
    preserved_landmines = thread.get("landmine_topics", [])
    preserved_avoid = thread.get("avoid_topics", [])
    new_thread = _empty_thread()
    new_thread["landmine_topics"] = preserved_landmines
    new_thread["avoid_topics"] = preserved_avoid
    _save_thread(person_id, new_thread)
    return {"success": True, "message": "线索已清空（保留禁忌列表）"}


def _action_check_expired(person_id: str, current_stage: int) -> dict:
    """检查线索是否过期（6.6 节）。"""
    thread = _load_thread(person_id)
    last_updated = thread.get("last_updated")
    if not last_updated:
        return {"expired": True, "elapsed_hours": float("inf"), "threshold_hours": STAGE_EXPIRY_HOURS.get(current_stage, 6), "last_updated": None, "message": "线索不存在或从未更新"}

    try:
        last_time = datetime.fromisoformat(last_updated)
    except (ValueError, TypeError):
        return {"expired": True, "elapsed_hours": float("inf"), "threshold_hours": STAGE_EXPIRY_HOURS.get(current_stage, 6), "last_updated": last_updated, "message": "线索时间格式异常"}

    elapsed = (datetime.now() - last_time).total_seconds() / 3600
    threshold = STAGE_EXPIRY_HOURS.get(current_stage, 6)
    expired = elapsed > threshold
    return {
        "expired": expired,
        "elapsed_hours": round(elapsed, 2),
        "threshold_hours": threshold,
        "last_updated": last_updated,
        "message": f"线索{'已过期' if expired else '有效'}，经过 {elapsed:.1f}h / 阈值 {threshold}h",
    }


def _action_catch_up(person_id: str, last_message_id: Optional[int], last_message_time: Optional[str]) -> dict:
    """补读后更新线索（6.5 节）。"""
    thread = _load_thread(person_id)
    old_processed = thread.get("last_processed_message_id", 0)
    if last_message_id is not None:
        thread["last_processed_message_id"] = last_message_id
    if last_message_time is not None:
        thread["last_message_time"] = last_message_time
    _save_thread(person_id, thread)
    caught_up = (last_message_id or 0) - old_processed if last_message_id else 0
    return {
        "success": True,
        "caught_up_messages": max(0, caught_up),
        "previous_processed_id": old_processed,
        "current_processed_id": last_message_id or old_processed,
        "message": f"已补读线索，处理到 message_id={last_message_id or old_processed}",
    }


def _action_add_landmine(person_id: str, landmine: dict) -> dict:
    """添加已消耗话题（6.3 节 landmine_topics）。"""
    if not landmine or "topic" not in landmine:
        return {"error": "INVALID_PARAMS", "message": "landmine 必须包含 topic 字段"}
    thread = _load_thread(person_id)
    entry = {
        "topic": landmine["topic"],
        "reason": landmine.get("reason", ""),
        "added_by": landmine.get("added_by", "auto_detect"),
        "added_at": landmine.get("added_at", datetime.now().strftime("%Y-%m-%d")),
    }
    # 去重
    existing_topics = [t.get("topic") for t in thread["landmine_topics"]]
    if entry["topic"] not in existing_topics:
        thread["landmine_topics"].append(entry)
        _save_thread(person_id, thread)
        return {"success": True, "message": f"已添加禁忌话题: {entry['topic']}", "total_landmines": len(thread["landmine_topics"])}
    else:
        return {"success": True, "message": f"禁忌话题已存在: {entry['topic']}", "total_landmines": len(thread["landmine_topics"])}


def _action_add_avoid_topic(person_id: str, avoid_topic: str) -> dict:
    """添加短期禁忌（6.3 节 avoid_topics）。"""
    if not avoid_topic:
        return {"error": "INVALID_PARAMS", "message": "avoid_topic 不能为空"}
    thread = _load_thread(person_id)
    if avoid_topic not in thread["avoid_topics"]:
        thread["avoid_topics"].append(avoid_topic)
        _save_thread(person_id, thread)
        return {"success": True, "message": f"已添加短期禁忌: {avoid_topic}", "total_avoid": len(thread["avoid_topics"])}
    else:
        return {"success": True, "message": f"短期禁忌已存在: {avoid_topic}", "total_avoid": len(thread["avoid_topics"])}


def _action_clear_cancel_flag(person_id: str) -> dict:
    """清除用户接管标记（7.8.2 节，用户通过 talk.md 恢复时调用）。"""
    thread = _load_thread(person_id)
    if thread.get("user_took_over", False):
        thread["user_took_over"] = False
        thread["user_took_over_time"] = None
        _save_thread(person_id, thread)
        return {"success": True, "message": "已清除用户接管标记，自动回复已恢复"}
    else:
        return {"success": True, "message": "用户未接管，无需清除"}
