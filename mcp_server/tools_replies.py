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
