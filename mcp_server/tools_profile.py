"""用户画像管理 MCP 工具（v4 补充 4 — 画像文件管理）。

本模块实现 v4 文档 7.2 节（画像拆分）+ 11.4 节（工具规格）。
管理文件：
  - data/user_profile_fact.yaml           用户事实画像（grounding，高优先级）
  - data/user_facts_topics_profile.yaml   用户话题画像（话题选择层，自动提取）
  - data/user_style_overrides/<id>.yaml   联系人特化层

架构调整（2026-07-24）：
  - 旧文件 user_style_profile.yaml 已删除（不包含对话风格，Agent 不模仿用户语言习惯）
  - 替换为 user_facts_topics_profile.yaml（事实+可谈论话题，非对话风格）

工具只做 CRUD，不生成回复风格建议，不决策"对这个人该用什么语气"，
不评估用户人设是否合适，不做人设优化。详见 v4 23.5 节契约。
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

_DATA_DIR = os.path.join(_PROJECT_ROOT, "data")
FACT_FILE = os.path.join(_DATA_DIR, "user_profile_fact.yaml")
FACTS_TOPICS_FILE = os.path.join(_DATA_DIR, "user_facts_topics_profile.yaml")
STYLE_OVERRIDES_DIR = os.path.join(_DATA_DIR, "user_style_overrides")


def _load_yaml(path: str, default: dict) -> dict:
    """加载 YAML 文件，不存在返回 default。"""
    if not os.path.exists(path):
        return dict(default)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data
    except Exception as e:
        logger.warning(f"YAML 加载失败 {path}: {e}")
        return dict(default)


def _save_yaml(path: str, data: dict) -> None:
    """保存 YAML 文件。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def _empty_fact() -> dict:
    return {
        "basic_info": {},
        "hobbies": [],
        "values": [],
        "experiences": [],
        "contact_specific_experiences": [],
        "material_library": {"topics": [], "stories": []},
        "change_history": [],
        "last_updated": None,
    }


def _empty_facts_topics() -> dict:
    return {
        "topics": {
            "frequent_topics": [],
            "recent_topics": [],
            "avoid_topics": [],
        },
        "soft_facts": {
            "frequent_places": [],
            "frequent_people": [],
            "attitudes": [],
        },
        "last_updated": None,
    }


def _resolve_person_id(name: str) -> str:
    """解析联系人名称 → person_id。"""
    from engine.tools import _resolve
    conn, config, person = _resolve(name)
    conn.close()
    return person.id


def user_profile_manage(
    action: str,
    profile_type: str = "fact",
    section: Optional[str] = None,
    data: Optional[dict] = None,
    asset: Optional[dict] = None,
    contact: Optional[str] = None,
) -> dict:
    """用户画像管理工具（支持三类画像文件）。

    什么时候用：初始化用户画像、更新事实信息、重置特化层。
    返回什么：get 返回对应画像数据；其他 action 返回操作结果。
    边界是什么：不生成回复风格建议，不决策"对这个人该用什么语气"，
                不评估用户人设是否合适，不做人设优化。
    """
    try:
        if action == "get":
            return _action_get(profile_type, section, contact)

        elif action == "update":
            return _action_update(profile_type, section, data or {}, contact)

        elif action == "add_asset":
            return _action_add_asset(asset or {})

        elif action == "query_assets":
            return _action_query_assets()

        elif action == "reset_style_override":
            return _action_reset_style_override(contact or "")

        else:
            return {"error": "INVALID_ACTION", "message": f"未知 action: {action}"}

    except Exception as e:
        logger.exception(f"user_profile_manage 异常 {action} {profile_type}")
        return {"error": "TOOL_ERROR", "message": str(e)}


def _action_get(profile_type: str, section: Optional[str], contact: Optional[str]) -> dict:
    """读取画像数据。"""
    if profile_type == "fact":
        data = _load_yaml(FACT_FILE, _empty_fact())
        result = data.get(section, data) if section else data
        return {"success": True, "profile_type": "fact", "data": result}

    elif profile_type == "facts_topics":
        base = _load_yaml(FACTS_TOPICS_FILE, _empty_facts_topics())
        if contact:
            person_id = _resolve_person_id(contact)
            override_path = os.path.join(STYLE_OVERRIDES_DIR, f"{person_id}.yaml")
            override = _load_yaml(override_path, {})
            return {"success": True, "profile_type": "facts_topics", "base": base, "override": override, "contact": contact}
        result = base.get(section, base) if section else base
        return {"success": True, "profile_type": "facts_topics", "data": result}

    else:
        return {"error": "INVALID_PROFILE_TYPE", "message": f"未知 profile_type: {profile_type}，支持 fact/facts_topics"}


def _action_update(profile_type: str, section: Optional[str], data: dict, contact: Optional[str]) -> dict:
    """更新画像数据。"""
    now = datetime.now().isoformat(timespec="seconds")

    if profile_type == "fact":
        file_data = _load_yaml(FACT_FILE, _empty_fact())
        if section:
            file_data[section] = data
        else:
            file_data.update(data)
        # 记录变更历史
        file_data.setdefault("change_history", []).append({
            "timestamp": now,
            "section": section or "multiple",
            "fields": list(data.keys()) if isinstance(data, dict) else [],
        })
        file_data["last_updated"] = now
        _save_yaml(FACT_FILE, file_data)
        return {"success": True, "message": f"用户事实画像已更新: {section or 'multiple'}", "last_updated": now}

    elif profile_type == "facts_topics":
        if contact:
            # 更新联系人特化层
            person_id = _resolve_person_id(contact)
            override_path = os.path.join(STYLE_OVERRIDES_DIR, f"{person_id}.yaml")
            override = _load_yaml(override_path, {})
            if section:
                override[section] = data
            else:
                override.update(data)
            override["contact_display_name"] = contact
            override["last_updated"] = now
            _save_yaml(override_path, override)
            return {"success": True, "message": f"联系人 {contact} 特化层已更新", "last_updated": now}
        else:
            # 更新基准层
            file_data = _load_yaml(FACTS_TOPICS_FILE, _empty_facts_topics())
            if section:
                file_data[section] = data
            else:
                file_data.update(data)
            file_data["last_updated"] = now
            _save_yaml(FACTS_TOPICS_FILE, file_data)
            return {"success": True, "message": f"用户话题画像已更新: {section or 'multiple'}", "last_updated": now}

    else:
        return {"error": "INVALID_PROFILE_TYPE", "message": f"update 不支持 profile_type: {profile_type}"}


def _action_add_asset(asset: dict) -> dict:
    """添加用户素材到 fact.material_library。"""
    if not asset.get("path"):
        return {"error": "INVALID_PARAMS", "message": "asset 必须包含 path 字段"}
    file_data = _load_yaml(FACT_FILE, _empty_fact())
    material = file_data.setdefault("material_library", {"topics": [], "stories": []})
    entry = {
        "path": asset["path"],
        "tag": asset.get("tag", ""),
        "description": asset.get("description", ""),
        "added_at": datetime.now().isoformat(timespec="seconds"),
    }
    if asset.get("type") == "story":
        material.setdefault("stories", []).append(entry)
    else:
        material.setdefault("topics", []).append(entry)
    file_data["last_updated"] = datetime.now().isoformat(timespec="seconds")
    _save_yaml(FACT_FILE, file_data)
    return {"success": True, "message": "素材已添加", "entry": entry}


def _action_query_assets() -> dict:
    """查询用户素材库。"""
    file_data = _load_yaml(FACT_FILE, _empty_fact())
    material = file_data.get("material_library", {"topics": [], "stories": []})
    return {"success": True, "material_library": material}


def _action_reset_style_override(contact: str) -> dict:
    """重置联系人特化层。"""
    if not contact:
        return {"error": "INVALID_PARAMS", "message": "contact 不能为空"}
    person_id = _resolve_person_id(contact)
    override_path = os.path.join(STYLE_OVERRIDES_DIR, f"{person_id}.yaml")
    if os.path.exists(override_path):
        os.remove(override_path)
        return {"success": True, "message": f"已重置联系人 {contact} 的特化层"}
    return {"success": True, "message": f"联系人 {contact} 无特化层，无需重置"}
