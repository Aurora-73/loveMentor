"""实时监听 MCP 工具。

在聊天场景中实时获取最新消息，避免每次手动同步。
- live_monitor_start: 开始监听（可配置轮询间隔、拉取条数、附带brief）
- live_monitor_stop: 停止监听
- live_monitor_status: 查看状态（含未读消息数）
- live_chat_read: 读取缓存消息（支持增量读取）
"""
from __future__ import annotations

from engine.live_monitor import get_manager
from engine.agent.core import _get_conn, _resolve_person


def live_monitor_start(name: str, poll_interval: int = 10,
                       fetch_limit: int = 500, include_brief: bool = False,
                       auto_stop: int = 600) -> str:
    """开始实时监听联系人消息。

    自动拉取最近30分钟消息（且至少30条，不足时扩展到最近30条），然后按 poll_interval 秒轮询刷新。
    监听期间用 live_chat_read 读取最新消息，无需手动同步。

    Args:
        name: 联系人名称或 wxid
        poll_interval: 轮询间隔秒数，默认 10s。聊天场景建议 5-15s
        fetch_limit: 每次拉取消息上限，默认 500。密集聊天可调大
        include_brief: 是否附带 person_brief 快照，省去额外调用 brief
        auto_stop: 无读取自动停止秒数，默认 600（10 分钟）。设为 0 禁用
    """
    manager = get_manager()
    conn, config = _get_conn()
    try:
        person = _resolve_person(conn, name)
        if not person:
            return f"未找到联系人: {name}"
        if not person.accounts:
            return f"联系人 {person.display_name} 没有关联的微信账号"

        account = person.accounts[0]
        wxid = account.conversation_id or account.wxid
        if not wxid:
            return f"联系人 {person.display_name} 没有有效的 wxid"

        result = manager.start(
            name, wxid, person.display_name, config,
            poll_interval=poll_interval,
            fetch_limit=fetch_limit,
            include_brief=include_brief,
            auto_stop_timeout=auto_stop,
        )
        if result["status"] == "already_running":
            return f"已在监听: {person.display_name}（无需重复启动）"

        auto_stop_min = auto_stop // 60 if auto_stop > 0 else "永不"
        lines = [
            f"# 实时监听已启动: {person.display_name}\n",
            f"- 状态: 初始化中（后台拉取，不阻塞）",
            f"- 轮询间隔: {result['poll_interval']}s",
            f"- 拉取上限: {result['fetch_limit']} 条",
            f"- 自动停止: {auto_stop_min} 分钟无读取自动关闭",
            f"- 缓存文件: {result['cache_path']}",
        ]

        if include_brief and result.get("brief"):
            lines.append(f"\n## 关系快照\n{result['brief']}")

        lines.append(f"\n初始化在后台进行，请等几秒后用 `live_chat_read('{name}')` 读取。")
        lines.append(f"用 `live_monitor_status()` 查看初始化进度。")
        lines.append(f"结束时调用 `live_monitor_stop('{name}')` 停止监听。")
        return "\n".join(lines)
    finally:
        conn.close()


def live_monitor_stop(name: str | None = None) -> str:
    """停止实时监听。传入 name 停止指定联系人，不传则停止所有监听。"""
    manager = get_manager()
    result = manager.stop(name)

    if result["status"] == "not_found":
        return f"未在监听: {name}"

    monitors = result["monitors"]
    if not monitors:
        return "当前没有正在进行的监听"

    lines = ["# 已停止监听\n"]
    for m in monitors:
        lines.append(
            f"- {m['name']}: 新增 {m['new_messages']} 条，"
            f"未读 {m['unread_count']} 条，缓存: {m['cache_path']}"
        )
    return "\n".join(lines)


def live_monitor_status() -> str:
    """查看当前监听状态（正在监听哪些联系人、未读消息数等）。"""
    manager = get_manager()
    result = manager.status()

    monitors = result["monitors"]
    if not monitors:
        return "当前没有正在进行的监听"

    from datetime import datetime
    lines = [f"# 实时监听状态（{result['total']} 个）\n"]
    for m in monitors:
        last_msg = datetime.fromtimestamp(m["last_msg_ts"]).strftime("%H:%M:%S") if m["last_msg_ts"] else "N/A"
        unread_badge = f" 🔴{m['unread_count']}未读" if m["unread_count"] > 0 else ""
        init_badge = ""
        if not m.get("initialized"):
            init_badge = " ⏳初始化中"
        elif m.get("init_error"):
            init_badge = f" ❌初始化失败"
        lines.append(f"## {m['display_name']}{unread_badge}{init_badge}")
        lines.append(f"- 开始时间: {m['started_at']}")
        lines.append(f"- 最后消息: {last_msg}")
        lines.append(f"- 轮询间隔: {m['poll_interval']}s")
        lines.append(f"- 新增消息: {m['new_msg_count']} 条")
        lines.append(f"- 最后轮询: {m['last_poll_at'] or '尚未轮询'}")
        if m.get("init_error"):
            lines.append(f"- ❌ 初始化错误: {m['init_error']}")
        if m["last_error"]:
            lines.append(f"- ⚠️ 最后错误: {m['last_error']}")
        lines.append("")
    return "\n".join(lines)


def live_chat_read(name: str, recent: int = 0, since_last_read: bool = False) -> str:
    """读取实时监听缓存的消息。

    比 person_sync + person_chat 快得多，适合聊天中频繁调用。

    Args:
        name: 联系人名称
        recent: 返回最后 N 条消息。0 = 返回全部。
        since_last_read: 只返回上次读取后的新消息（增量模式）。
                        设为 True 时 recent 参数被忽略。
    """
    manager = get_manager()
    return manager.read_cache(name, recent=recent, since_last_read=since_last_read)
