"""Server酱紧急通知 MCP 工具（v4 自动回复架构组件）。

本模块实现 v4 文档 12.4 节规格：紧急事件推送。
通过 Server酱 Turbo 版推送消息到用户微信。

工具契约：
  - 输入：title + content + priority（0=low, 1=medium, 2=high, 3=critical）
  - 输出：发送结果（sent/priority/timestamp/serverchan_response）
  - 明确不做：❌ 不决策"该不该通知" ❌ 不生成通知内容 ❌ 不预设事件分级规则

配置（data/system/config.yaml）：
  serverchan:
    enabled: true
    sckey: ""           # 用户在 https://sct.ftqq.com/ 注册后填入
    min_priority: 2     # 只有 priority >= min_priority 的事件才推送
"""

import os
import sys
import logging
import yaml
import urllib.request
import urllib.parse
import json
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

_CONFIG_FILE = os.path.join(_PROJECT_ROOT, "data", "system", "config.yaml")
_NOTIFY_LOG_FILE = os.path.join(_PROJECT_ROOT, "data", "system", "notify_log.yaml")

# 优先级名称映射
_PRIORITY_NAMES = {
    0: "low",
    1: "medium",
    2: "high",
    3: "critical",
}


def _load_config() -> dict:
    """加载系统配置。"""
    if not os.path.exists(_CONFIG_FILE):
        return {"serverchan": {"enabled": False, "sckey": "", "min_priority": 2}}
    try:
        with open(_CONFIG_FILE, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        logger.warning(f"config 加载失败: {e}")
        return {"serverchan": {"enabled": False, "sckey": "", "min_priority": 2}}


def _save_config(config: dict) -> None:
    """保存系统配置。"""
    os.makedirs(os.path.dirname(_CONFIG_FILE), exist_ok=True)
    with open(_CONFIG_FILE, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def _log_notify(log_entry: dict) -> None:
    """记录通知日志。"""
    logs = []
    if os.path.exists(_NOTIFY_LOG_FILE):
        try:
            with open(_NOTIFY_LOG_FILE, "r", encoding="utf-8") as f:
                logs = yaml.safe_load(f) or []
        except Exception:
            logs = []
    logs.append(log_entry)
    # 保留最近 200 条
    if len(logs) > 200:
        logs = logs[-200:]
    os.makedirs(os.path.dirname(_NOTIFY_LOG_FILE), exist_ok=True)
    with open(_NOTIFY_LOG_FILE, "w", encoding="utf-8") as f:
        yaml.dump(logs, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def server_chan_notify(
    title: str,
    content: str,
    priority: int = 2,
) -> dict:
    """通过 Server酱 推送紧急通知到用户微信。

    什么时候用：Agent 检测到需要立即通知的紧急事件，用户不在 Trae IDE 前面时。
    返回什么：dict 含 sent（是否发送成功）/ priority / timestamp / serverchan_response。
    边界是什么：不决策"该不该通知"（由 Agent 判断）；不生成通知内容（由 Agent 写）；
                不预设事件分级规则（由 Agent 自主决定 priority 值）。
    """
    # 1. 参数校验
    if not title:
        return {"error": "MISSING_PARAM", "message": "title 不能为空"}
    if len(title) > 32:
        title = title[:32]
    if priority not in (0, 1, 2, 3):
        return {"error": "INVALID_PRIORITY", "message": "priority 必须是 0/1/2/3"}

    # 2. 读取配置
    config = _load_config()
    serverchan = config.get("serverchan", {}) or {}

    if not serverchan.get("enabled", False):
        return {
            "sent": False,
            "reason": "disabled",
            "message": "Server酱未启用，请在 data/system/config.yaml 中设置 serverchan.enabled=true",
        }

    sckey = serverchan.get("sckey", "")
    if not sckey:
        return {
            "sent": False,
            "reason": "no_sckey",
            "message": "Server酱 sckey 未配置，请在 https://sct.ftqq.com/ 注册后填入",
        }

    min_priority = serverchan.get("min_priority", 2)
    if priority < min_priority:
        return {
            "sent": False,
            "reason": "below_threshold",
            "priority": priority,
            "min_priority": min_priority,
            "message": f"优先级 {priority} 低于阈值 {min_priority}，跳过推送",
        }

    # 3. 发送请求到 Server酱 Turbo
    timestamp = datetime.now().isoformat(timespec="seconds")
    try:
        url = f"https://sctapi.ftqq.com/{sckey}.send"
        data = urllib.parse.urlencode({
            "title": title,
            "desp": content,
        }).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")

        with urllib.request.urlopen(req, timeout=10) as response:
            resp_body = response.read().decode("utf-8")
            try:
                resp_json = json.loads(resp_body)
            except json.JSONDecodeError:
                resp_json = {"raw": resp_body}

        sent = resp_json.get("code", -1) == 0
        result = {
            "sent": sent,
            "priority": priority,
            "priority_name": _PRIORITY_NAMES.get(priority, "unknown"),
            "timestamp": timestamp,
            "serverchan_response": resp_json,
        }

        # 4. 记录日志
        _log_notify({
            "timestamp": timestamp,
            "title": title,
            "priority": priority,
            "sent": sent,
            "content_preview": content[:100],
        })

        return result

    except Exception as e:
        logger.exception("server_chan_notify 发送失败")
        error_result = {
            "sent": False,
            "reason": "send_error",
            "priority": priority,
            "timestamp": timestamp,
            "error": str(e),
        }
        _log_notify({
            "timestamp": timestamp,
            "title": title,
            "priority": priority,
            "sent": False,
            "error": str(e),
        })
        return error_result


def server_chan_config(
    action: str = "get",
    enabled: Optional[bool] = None,
    sckey: Optional[str] = None,
    min_priority: Optional[int] = None,
) -> dict:
    """管理 Server酱 配置。

    action：get（读取配置）/ update（更新配置）/ test（发送测试通知）。
    """
    config = _load_config()

    if action == "get":
        serverchan = config.get("serverchan", {}) or {}
        return {
            "enabled": serverchan.get("enabled", False),
            "sckey": "***" if serverchan.get("sckey") else "",
            "sckey_configured": bool(serverchan.get("sckey")),
            "min_priority": serverchan.get("min_priority", 2),
        }

    elif action == "update":
        if "serverchan" not in config:
            config["serverchan"] = {}
        if enabled is not None:
            config["serverchan"]["enabled"] = enabled
        if sckey is not None:
            config["serverchan"]["sckey"] = sckey
        if min_priority is not None:
            config["serverchan"]["min_priority"] = min_priority
        _save_config(config)
        return {
            "success": True,
            "message": "配置已更新",
            "enabled": config["serverchan"].get("enabled", False),
            "min_priority": config["serverchan"].get("min_priority", 2),
        }

    elif action == "test":
        return server_chan_notify(
            title="Server酱测试通知",
            content="这是一条来自 LoveMentor Agent 的测试通知。如果您能看到这条消息，说明 Server酱配置成功！",
            priority=2,
        )

    else:
        return {"error": "INVALID_ACTION", "message": f"未知 action: {action}"}
