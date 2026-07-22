"""联系人优先级管理 MCP 工具（v4 自动回复架构组件）。

本模块实现 v4 文档 10.6 节规格：联系人优先级持久化管理。
文件路径：data/system/contact_priority.yaml

工具契约（v4 23.10 节）：
  - 输入：action（get/list/set_eval/set_override/reset）+ name + 可选参数
  - 输出：优先级数据（user_eval / override_score / computed_priority）
  - 明确不做：❌ 不计算优先级分数（由 Agent 计算，工具只持久化）
              ❌ 不决策"先回谁" ❌ 不评估关系重要性 ❌ 不生成优先级调整建议

设计原则（v4 10.6 节）：
  优先级分数由 Agent 基于 person_stage / person_signals / person_metrics 数据自主计算，
  工具负责持久化管理（设置/查询/调整用户主观评价权重）。
  优先级影响约会安排顺序，但不机械影响每条消息的回复及时性。
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

_PRIORITY_FILE = os.path.join(_PROJECT_ROOT, "data", "system", "contact_priority.yaml")

# 合法 user_eval 值
_VALID_EVALS = {"high", "medium", "low"}


def contact_priority_manage(
    action: str,
    name: Optional[str] = None,
    user_eval: Optional[str] = None,
    override_score: Optional[float] = None,
    reason: Optional[str] = None,
) -> dict:
    """联系人优先级持久化管理工具。

    什么时候用：Agent 需查询/设置联系人优先级权重时。
    返回什么：get 返回单人优先级数据；list 返回排序后的优先级列表；
              set_eval/set_override/reset 返回操作结果。
    边界是什么：不计算优先级分数（Agent 计算）；不决策"先回谁"；
                不评估关系重要性；不生成调整建议。
    """
    try:
        if action == "get":
            if not name:
                return {"error": "MISSING_PARAM", "message": "get action 需要 name"}
            return _action_get(name)

        elif action == "list":
            return _action_list()

        elif action == "set_eval":
            if not name or not user_eval:
                return {"error": "MISSING_PARAM", "message": "set_eval 需要 name 和 user_eval"}
            if user_eval not in _VALID_EVALS:
                return {"error": "INVALID_PARAM", "message": f"user_eval 必须是 {sorted(_VALID_EVALS)} 之一"}
            return _action_set_eval(name, user_eval, reason or "")

        elif action == "set_override":
            if not name:
                return {"error": "MISSING_PARAM", "message": "set_override 需要 name"}
            if override_score is None or not (0 <= override_score <= 1):
                return {"error": "INVALID_PARAM", "message": "override_score 必须是 0-1 之间的浮点数"}
            return _action_set_override(name, override_score, reason or "")

        elif action == "reset":
            if not name:
                return {"error": "MISSING_PARAM", "message": "reset action 需要 name"}
            return _action_reset(name, reason or "")

        else:
            return {"error": "INVALID_ACTION", "message": f"未知 action: {action}"}

    except Exception as e:
        logger.exception(f"contact_priority_manage 异常 {action}")
        return {"error": "TOOL_ERROR", "message": str(e)}


# ── 数据加载/保存 ────────────────────────────────────────────────


def _load_priority() -> dict:
    """加载优先级数据文件。"""
    if not os.path.exists(_PRIORITY_FILE):
        return _empty_data()
    try:
        with open(_PRIORITY_FILE, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if "contacts" not in data:
            data["contacts"] = {}
        return data
    except Exception as e:
        logger.warning(f"contact_priority 加载失败: {e}，返回空结构")
        return _empty_data()


def _empty_data() -> dict:
    return {"contacts": {}, "last_updated": None}


def _save_priority(data: dict) -> None:
    """保存优先级数据文件。"""
    data["last_updated"] = datetime.now().isoformat(timespec="seconds")
    os.makedirs(os.path.dirname(_PRIORITY_FILE), exist_ok=True)
    with open(_PRIORITY_FILE, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def _ensure_contact(data: dict, name: str) -> dict:
    """确保联系人条目存在，返回该条目。"""
    contacts = data.setdefault("contacts", {})
    if name not in contacts:
        contacts[name] = {
            "user_eval": None,
            "override_score": None,
            "override_reason": None,
            "history": [],
        }
    return contacts[name]


# ── action 实现 ──────────────────────────────────────────────────


def _action_get(name: str) -> dict:
    """获取单个联系人的优先级数据。

    注意：score 和 breakdown 字段由 Agent 计算后传入（如果有），
    工具本身不计算优先级分数。此处返回持久化的 user_eval 和 override。
    """
    data = _load_priority()
    contact = data.get("contacts", {}).get(name)

    if not contact:
        return {
            "action": "get",
            "name": name,
            "found": False,
            "user_eval": None,
            "override_score": None,
            "message": "该联系人尚无优先级记录，可调用 set_eval 或 set_override 设置",
        }

    return {
        "action": "get",
        "name": name,
        "found": True,
        "user_eval": contact.get("user_eval"),
        "override_score": contact.get("override_score"),
        "override_reason": contact.get("override_reason"),
        "history": contact.get("history", []),
        "note": "优先级分数由 Agent 基于 person_stage/person_signals/person_metrics 计算，工具只持久化 user_eval 和 override",
    }


def _action_list() -> dict:
    """列出所有联系人的优先级数据（按 user_eval 降序排列）。

    工具不计算综合分数，只返回持久化的 user_eval 和 override。
    Agent 可基于此数据自主排序。
    """
    data = _load_priority()
    contacts = data.get("contacts", {})

    # user_eval 权重用于排序展示
    eval_weight = {"high": 3, "medium": 2, "low": 1, None: 0}

    items = []
    for name, info in contacts.items():
        items.append({
            "name": name,
            "user_eval": info.get("user_eval"),
            "override_score": info.get("override_score"),
            "override_reason": info.get("override_reason"),
        })

    # 排序：override_score 高的优先，其次 user_eval 高的
    items.sort(
        key=lambda x: (
            -(x.get("override_score") or 0),
            -eval_weight.get(x.get("user_eval"), 0),
        )
    )

    # 添加 rank
    for i, item in enumerate(items, 1):
        item["rank"] = i

    return {
        "action": "list",
        "count": len(items),
        "contacts": items,
        "note": "排序基于 override_score + user_eval，综合优先级分数由 Agent 计算",
    }


def _action_set_eval(name: str, user_eval: str, reason: str) -> dict:
    """设置用户主观评价（high/medium/low）。"""
    data = _load_priority()
    contact = _ensure_contact(data, name)

    old_eval = contact.get("user_eval")
    contact["user_eval"] = user_eval

    # 记录历史
    history = contact.setdefault("history", [])
    history.append({
        "time": datetime.now().isoformat(timespec="minutes"),
        "action": "set_eval",
        "old_value": old_eval,
        "new_value": user_eval,
        "reason": reason,
    })
    # 保留最近 20 条历史
    if len(history) > 20:
        contact["history"] = history[-20:]

    _save_priority(data)

    return {
        "success": True,
        "action": "set_eval",
        "name": name,
        "old_eval": old_eval,
        "new_eval": user_eval,
        "reason": reason,
        "message": f"已设置 {name} 的用户主观评价为 {user_eval}",
    }


def _action_set_override(name: str, override_score: float, reason: str) -> dict:
    """手动覆盖优先级分数（0-1）。"""
    if not reason:
        return {"error": "MISSING_PARAM", "message": "set_override 需要提供 reason（调整原因）"}

    data = _load_priority()
    contact = _ensure_contact(data, name)

    old_score = contact.get("override_score")
    contact["override_score"] = override_score
    contact["override_reason"] = reason

    # 记录历史
    history = contact.setdefault("history", [])
    history.append({
        "time": datetime.now().isoformat(timespec="minutes"),
        "action": "set_override",
        "old_value": old_score,
        "new_value": override_score,
        "reason": reason,
    })
    if len(history) > 20:
        contact["history"] = history[-20:]

    _save_priority(data)

    return {
        "success": True,
        "action": "set_override",
        "name": name,
        "old_score": old_score,
        "new_score": override_score,
        "reason": reason,
        "message": f"已覆盖 {name} 的优先级分数为 {override_score}",
    }


def _action_reset(name: str, reason: str) -> dict:
    """重置联系人的优先级设置（清除 user_eval 和 override）。"""
    data = _load_priority()
    contacts = data.get("contacts", {})

    if name not in contacts:
        return {
            "success": True,
            "action": "reset",
            "name": name,
            "message": f"{name} 无优先级记录，无需重置",
        }

    contact = contacts[name]
    old_eval = contact.get("user_eval")
    old_score = contact.get("override_score")

    contact["user_eval"] = None
    contact["override_score"] = None
    contact["override_reason"] = None

    # 记录历史
    history = contact.setdefault("history", [])
    history.append({
        "time": datetime.now().isoformat(timespec="minutes"),
        "action": "reset",
        "old_eval": old_eval,
        "old_score": old_score,
        "reason": reason or "用户重置",
    })
    if len(history) > 20:
        contact["history"] = history[-20:]

    _save_priority(data)

    return {
        "success": True,
        "action": "reset",
        "name": name,
        "cleared_eval": old_eval,
        "cleared_score": old_score,
        "reason": reason,
        "message": f"已重置 {name} 的优先级设置",
    }
