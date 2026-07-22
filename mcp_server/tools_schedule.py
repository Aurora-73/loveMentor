"""用户日程管理 MCP 工具（v4 自动回复架构组件）。

本模块实现 v4 文档第十章规格：日程管理。
文件路径：data/schedule.yaml（单一文件，全局用户日程）。

工具只做 CRUD，不解析自然语言日程（由 Agent 理解），不冲突检测（由 Agent 判断），
不推荐约会时间（由 Agent 基于 Wiki 决策）。详见 v4 23.3 节契约。
"""

import os
import sys
import logging
import yaml
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

SCHEDULE_FILE = os.path.join(_PROJECT_ROOT, "data", "schedule.yaml")


def _load_schedule() -> dict:
    """加载日程文件。"""
    if not os.path.exists(SCHEDULE_FILE):
        return _empty_schedule()
    try:
        with open(SCHEDULE_FILE, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return _normalize(data)
    except Exception as e:
        logger.warning(f"日程文件加载失败: {e}，返回空结构")
        return _empty_schedule()


def _empty_schedule() -> dict:
    """空日程结构。"""
    return {
        "user_preferences": {
            "available_times": [],
            "preferred_date_duration": "",
            "preferred_date_types": [],
        },
        "scheduled_events": [],
        "user_notes": [],
        "last_updated": None,
    }


def _normalize(data: dict) -> dict:
    """确保结构完整。"""
    empty = _empty_schedule()
    for key, default_val in empty.items():
        if key not in data:
            data[key] = default_val
    return data


def _save_schedule(data: dict) -> None:
    """保存日程文件。"""
    data["last_updated"] = datetime.now().isoformat(timespec="seconds")
    os.makedirs(os.path.dirname(SCHEDULE_FILE), exist_ok=True)
    with open(SCHEDULE_FILE, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def _gen_event_id(person: str) -> str:
    """生成事件 ID：evt_{timestamp}_{person}。"""
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    safe_person = person.replace(" ", "_")[:20]
    return f"evt_{timestamp}_{safe_person}"


def schedule_manage(
    action: str,
    date: Optional[str] = None,
    event: Optional[dict] = None,
    preference: Optional[dict] = None,
    note: Optional[str] = None,
    event_id: Optional[str] = None,
    person: Optional[str] = None,
    time_range: Optional[str] = None,
) -> dict:
    """用户日程管理工具（纯 CRUD）。

    什么时候用：邀约前查询可用时段、记录约会安排、更新用户偏好。
    返回什么：query 返回日程列表；list_slots 返回可用时段；其他 action 返回操作结果。
    边界是什么：不解析自然语言（由 Agent 理解），不冲突检测（由 Agent 判断），
                不推荐约会时间（由 Agent 基于 Wiki 决策）。
    """
    try:
        if action == "query":
            return _action_query(date, person)

        elif action == "add":
            return _action_add(event or {}, person or "")

        elif action == "update":
            return _action_update(event_id or "", event or {})

        elif action == "remove":
            return _action_remove(event_id or "")

        elif action == "list_slots":
            return _action_list_slots(date)

        elif action == "update_preferences":
            return _action_update_preferences(preference or {})

        elif action == "add_note":
            return _action_add_note(note or "")

        else:
            return {"error": "INVALID_ACTION", "message": f"未知 action: {action}"}

    except Exception as e:
        logger.exception(f"schedule_manage 异常 {action}")
        return {"error": "TOOL_ERROR", "message": str(e)}


def _action_query(date_filter: Optional[str], person_filter: Optional[str]) -> dict:
    """查询日程事件。"""
    data = _load_schedule()
    events = data.get("scheduled_events", [])
    if date_filter:
        events = [e for e in events if e.get("date", "").startswith(date_filter)]
    if person_filter:
        events = [e for e in events if e.get("person", "") == person_filter]
    return {
        "success": True,
        "events": events,
        "total": len(events),
        "preferences": data.get("user_preferences", {}),
        "notes": data.get("user_notes", []),
    }


def _action_add(event: dict, person: str) -> dict:
    """添加日程事件。"""
    if not event.get("date"):
        return {"error": "INVALID_PARAMS", "message": "event 必须包含 date 字段"}
    data = _load_schedule()
    new_event = {
        "event_id": event.get("event_id") or _gen_event_id(person or "unknown"),
        "person": person or event.get("person", ""),
        "date": event["date"],
        "time_range": event.get("time_range", ""),
        "activity": event.get("activity", ""),
        "location": event.get("location", ""),
        "priority": event.get("priority", "medium"),
        "status": event.get("status", "confirmed"),
        "created_by": event.get("created_by", "agent"),
        "wiki_ref": event.get("wiki_ref", ""),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    data["scheduled_events"].append(new_event)
    _save_schedule(data)
    return {"success": True, "message": f"已添加日程: {new_event['event_id']}", "event": new_event}


def _action_update(event_id: str, updates: dict) -> dict:
    """更新日程事件。"""
    if not event_id:
        return {"error": "INVALID_PARAMS", "message": "event_id 不能为空"}
    data = _load_schedule()
    for event in data["scheduled_events"]:
        if event.get("event_id") == event_id:
            for key, value in updates.items():
                if key != "event_id":  # 不允许修改 event_id
                    event[key] = value
            _save_schedule(data)
            return {"success": True, "message": f"已更新日程: {event_id}", "event": event}
    return {"error": "NOT_FOUND", "message": f"未找到日程: {event_id}"}


def _action_remove(event_id: str) -> dict:
    """删除日程事件。"""
    if not event_id:
        return {"error": "INVALID_PARAMS", "message": "event_id 不能为空"}
    data = _load_schedule()
    original_count = len(data["scheduled_events"])
    data["scheduled_events"] = [e for e in data["scheduled_events"] if e.get("event_id") != event_id]
    if len(data["scheduled_events"]) < original_count:
        _save_schedule(data)
        return {"success": True, "message": f"已删除日程: {event_id}"}
    return {"error": "NOT_FOUND", "message": f"未找到日程: {event_id}"}


def _action_list_slots(date: Optional[str]) -> dict:
    """列出可用时段（基于 user_preferences）。"""
    data = _load_schedule()
    prefs = data.get("user_preferences", {})
    available = prefs.get("available_times", [])
    # 查找该日期已占用时段
    occupied = []
    if date:
        for event in data.get("scheduled_events", []):
            if event.get("date", "").startswith(date):
                occupied.append({
                    "time_range": event.get("time_range", ""),
                    "activity": event.get("activity", ""),
                    "person": event.get("person", ""),
                })
    # 判断该日期是星期几
    weekday_info = ""
    if date:
        try:
            dt = datetime.fromisoformat(date)
            weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
            weekday_info = weekdays[dt.weekday()]
        except (ValueError, TypeError):
            pass
    # 查找该星期几的偏好
    preferred_slots = []
    if weekday_info:
        for slot in available:
            if slot.get("weekday") == weekday_info:
                preferred_slots.append(slot)
    return {
        "success": True,
        "date": date or "all",
        "weekday": weekday_info,
        "preferred_slots": preferred_slots,
        "occupied": occupied,
        "all_preferences": available,
        "preferred_date_types": prefs.get("preferred_date_types", []),
        "preferred_duration": prefs.get("preferred_date_duration", ""),
    }


def _action_update_preferences(preference: dict) -> dict:
    """更新用户偏好。"""
    data = _load_schedule()
    prefs = data.get("user_preferences", {})
    if "available_times" in preference:
        prefs["available_times"] = preference["available_times"]
    if "preferred_date_duration" in preference:
        prefs["preferred_date_duration"] = preference["preferred_date_duration"]
    if "preferred_date_types" in preference:
        prefs["preferred_date_types"] = preference["preferred_date_types"]
    data["user_preferences"] = prefs
    _save_schedule(data)
    return {"success": True, "message": "偏好已更新", "preferences": prefs}


def _action_add_note(note: str) -> dict:
    """添加用户备注。"""
    if not note:
        return {"error": "INVALID_PARAMS", "message": "note 不能为空"}
    data = _load_schedule()
    data["user_notes"].append({
        "text": note,
        "added_at": datetime.now().isoformat(timespec="seconds"),
    })
    _save_schedule(data)
    return {"success": True, "message": "备注已添加", "total_notes": len(data["user_notes"])}
