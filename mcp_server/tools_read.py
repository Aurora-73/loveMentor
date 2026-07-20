"""MCP 只读工具函数（无装饰器，由 server.py 注册）。"""

from typing import Optional

from engine.tools import (
    brief_data, chat_data, metrics, rank_data, status_data,
    wiki_search_data, wiki_show, wiki_context_data,
    timeline, signals, stage_data,
    evidence, compare_analysis, weekly, moments_stats,
    maintain_candidates, format_candidates,
    events, check_keys,
    contact, exclude, failure, sticker,
    message_context_data, save_from_markdown as _save_from_markdown,
    sync_moments as _sync_moments,
)


def person_brief(name: str) -> dict:
    """获取人物简要信息。"""
    try:
        return brief_data(name)
    except Exception as e:
        return {"error": "PERSON_NOT_FOUND", "message": str(e), "suggestion": "请检查联系人姓名是否正确，或先使用 sync 同步数据"}


CHAT_MAX_RECENT = 500


def person_chat(
    name: str, recent: int = 30, keyword: Optional[str] = None,
    from_date: Optional[str] = None, to_date: Optional[str] = None,
    context_lines: int = 0,
) -> dict:
    """获取人物聊天记录。

    什么时候用：需要查看与某人的具体对话内容时。
    返回什么：dict 含 messages 列表，每条消息含 id/sender_id/is_mine/timestamp/content。
    边界是什么：recent 控制返回消息数量（硬上限 500，防止返回超限）；keyword 按关键词过滤（context_lines 仅在 keyword 模式下生效，控制匹配消息的上下文条数）；
    from_date/to_date 按日期范围过滤（格式 YYYY-MM-DD）。
    """
    original_recent = recent
    if recent <= 0 or recent > CHAT_MAX_RECENT:
        recent = CHAT_MAX_RECENT
    try:
        result = chat_data(name, recent=recent, keyword=keyword,
                           from_date=from_date, to_date=to_date,
                           context_lines=context_lines)
        if original_recent <= 0 or original_recent > CHAT_MAX_RECENT:
            if isinstance(result, dict) and "data" in result:
                result["data"]["truncated"] = True
                result["data"]["original_recent"] = original_recent
                result["data"]["applied_recent"] = recent
                result["data"]["truncation_reason"] = f"recent={original_recent} 超出上限 {CHAT_MAX_RECENT}，已自动截断"
        return result
    except Exception as e:
        return {"error": "PERSON_NOT_FOUND", "message": str(e), "suggestion": "请检查联系人姓名是否正确"}


def person_metrics(name: str) -> dict:
    """获取人物关系指标。"""
    try:
        result = metrics(name)
        if isinstance(result, str):
            return {"error": "PERSON_NOT_FOUND", "message": result, "suggestion": "请检查联系人姓名是否正确"}
        return result
    except Exception as e:
        return {"error": "TOOL_ERROR", "message": str(e), "suggestion": "请检查数据库连接"}


def person_rank() -> dict:
    """获取所有人的关系排名。"""
    try:
        result = rank_data()
        return result
    except Exception as e:
        return {"error": "TOOL_ERROR", "message": str(e), "suggestion": "请检查数据库连接"}


def person_status(name: str) -> dict:
    """获取人物状态概览。"""
    try:
        return status_data(name)
    except Exception as e:
        return {"error": "PERSON_NOT_FOUND", "message": str(e), "suggestion": "请检查联系人姓名是否正确"}


def wiki_search(query: str, limit: int = 5) -> dict:
    """搜索 Wiki 知识库。"""
    try:
        return wiki_search_data(query, limit=limit)
    except Exception as e:
        return {"error": "TOOL_ERROR", "message": str(e), "suggestion": "请检查 Wiki 配置"}


def wiki_read(path: str, max_chars: int = 8000) -> dict:
    """读取 Wiki 页面完整正文。

    什么时候用：wiki_search 找到感兴趣的知识点后，需要阅读完整内容时。
    返回什么：dict 含 path/content/total_chars/truncated 字段。
    边界是什么：path 是 wiki_search 返回的 path 字段；max_chars 控制返回长度，超过则截断。
    """
    try:
        content = wiki_show(path, max_chars=max_chars)
        return {"path": path, "content": content, "max_chars": max_chars}
    except Exception as e:
        return {"error": "TOOL_ERROR", "message": str(e), "suggestion": "请检查 path 是否正确，应使用 wiki_search 返回的 path"}


def wiki_context(
    queries: list[str],
    task_type: str = "analyze",
    stage: str = "",
    focus: str = "",
    max_chars: int = 8000,
    max_pages: int = 8,
) -> dict:
    """批量构建 Wiki 知识上下文（推荐作为主入口，替代多次 wiki_search+wiki_read）。

    什么时候用：
    - 分析人物时，拿到 brief 的阶段/信号后，一次性构建知识图景
    - 看到聊天模式后，需要查策略和话术时
    - 写报告前，需要回顾相关 Wiki 条目时

    与 wiki_search 的区别：
    - wiki_context 合并多条查询 + 阶段过滤 + 焦点加权，一次返回格式化 prompt 段落
    - wiki_search 返回候选列表，需要逐条 wiki_read 读全文
    wiki_search/wiki_read 保留用于精确钻取单页内容。

    返回什么：dict 含 prompt_section（可直接嵌入推理的 Markdown 段落）、
    meta（hit_pages/returned_pages/deduped/total_chars/low_confidence）、
    page_list（命中页面摘要，供需要时用 wiki_read 钻取）。

    边界：queries 最多 5 条（超出自动截断）；stage 从 person_brief 的 relationship_stage
    或 person_stage 的 current_stage 获取；focus 取 signals/strategy/risk/date/chat。
    """
    try:
        return wiki_context_data(
            queries=queries,
            task_type=task_type,
            stage=stage,
            focus=focus,
            max_chars=max_chars,
            max_pages=max_pages,
        )
    except Exception as e:
        return {
            "error": "TOOL_ERROR",
            "message": str(e),
            "suggestion": "请检查 queries 格式（应为字符串列表）和参数值",
        }


# ── Phase 2 P1: 只读工具 ──────────────────────────────────────


def person_timeline(name: str, max_events: int = 30) -> dict:
    """获取关系时间线。

    什么时候用：需要查看关系发展的关键事件时间线时。
    返回什么：dict 含 person_id/display_name/events 列表。
    边界是什么：max_events 控制返回事件数量。
    """
    try:
        return timeline(name, max_events=max_events)
    except Exception as e:
        return {"error": "PERSON_NOT_FOUND", "message": str(e), "suggestion": "请检查联系人姓名是否正确"}


def person_signals(name: str) -> dict:
    """获取信号详情（基础信号 + 操控信号 + 朋友圈联动信号）。

    什么时候用：需要深入了解检测到的各类信号时。
    返回什么：dict 含 person_id/display_name/basic_signals/manipulation_signals/moments_signals。
    边界是什么：name 必填。
    """
    try:
        return signals(name)
    except Exception as e:
        return {"error": "PERSON_NOT_FOUND", "message": str(e), "suggestion": "请检查联系人姓名是否正确"}


def person_evidence(name: str, section: str = "all", since_date: Optional[str] = None) -> dict:
    """获取事实档案（timeline/evaluations/notes/dates/all）。

    什么时候用：需要查看已记录的客观事实（笔记、评价、约会记录等）时。
    返回什么：dict 含 name/section/content/has_analysis 字段，content 为 Markdown 格式。
    边界是什么：section 可选 all/timeline/evaluations/notes/dates；since_date 过滤起始日期。
    分析内容不在事实档案中，请使用 person_save_analysis/person_compare 查看分析结论。
    """
    try:
        result = evidence(name, section=section, since_date=since_date)
        from pathlib import Path
        from engine.config import ROOT_DIR
        analysis_dir = ROOT_DIR / "data" / "outputs" / "analysis"
        has_analysis = any(analysis_dir.glob(f"{name}*")) if analysis_dir.is_dir() else False
        hint = ""
        if not has_analysis:
            hint = "\n\n---\n**提示**: 未找到分析记录。分析内容存储在 data/outputs/analysis/，请使用 person_save_analysis 保存分析，或 person_compare 对比历史分析。"
        else:
            hint = "\n\n---\n**提示**: 检测到已有分析记录。请使用 person_compare 查看分析对比，或 person_save_analysis 更新分析。"
        return {
            "name": name,
            "section": section,
            "content": result + hint,
            "has_analysis": has_analysis,
        }
    except Exception as e:
        return {"error": "PERSON_NOT_FOUND", "message": str(e), "suggestion": "请检查联系人姓名是否正确"}


def person_stage(name: str) -> dict:
    """关系阶段自动识别 — 基于指标+事件+失败档案推断当前关系阶段。

    什么时候用：需要快速判断与某人的关系进展阶段、获取推进建议时。
    返回什么：dict 含 current_stage/next_stage/advancement_signals/blockers/
    is_stagnant/entered_at/days_in_current_stage。
    阶段定义（9 个）：未识别 → 初识 → 有基本互动 → 高频聊天 → 已约见 →
    持续接触 → 暧昧推进 → 关系确认 → 退出/失败。
    边界是什么：name 必填；识别基于客观数据（消息量、活跃天、信号等级、事件），
    不读取主观分析结论。
    """
    try:
        return stage_data(name)
    except ValueError as e:
        return {"error": "PERSON_NOT_FOUND", "message": str(e), "suggestion": "请检查联系人姓名是否正确"}
    except Exception as e:
        return {"error": "TOOL_ERROR", "message": str(e), "suggestion": "请检查数据库连接"}


def person_compare(name: str) -> dict:
    """对比 latest.yaml 和 previous.yaml 的变化趋势。

    什么时候用：需要了解一个人与上次分析相比的变化时。
    返回什么：dict 含 name/content 字段，content 为对比分析 Markdown。
    边界是什么：需要至少两次 save_analysis 才有对比数据。
    """
    try:
        result = compare_analysis(name)
        return {"name": name, "content": result}
    except Exception as e:
        return {"error": "PERSON_NOT_FOUND", "message": str(e), "suggestion": "请检查联系人姓名是否正确"}


def weekly_report(deep: bool = False) -> dict:
    """生成周报。

    什么时候用：需要生成本周关系维护总结报告时。
    返回什么：dict 含 content 字段，content 为周报 Markdown。
    边界是什么：deep=True 时生成深度报告（更耗时）。
    """
    try:
        result = weekly(deep=deep)
        return {"content": result, "deep": deep}
    except Exception as e:
        return {"error": "TOOL_ERROR", "message": str(e), "suggestion": "请检查数据库连接"}


def person_moments_stats(name: str) -> dict:
    """获取朋友圈互动统计。

    什么时候用：需要分析朋友圈互动频率和模式时。
    返回什么：dict 含朋友圈互动统计数据。
    边界是什么：name 必填。
    """
    try:
        result = moments_stats(name)
        if isinstance(result, str):
            return {"error": "PERSON_NOT_FOUND", "message": result, "suggestion": "请检查联系人姓名是否正确"}
        return result
    except Exception as e:
        return {"error": "TOOL_ERROR", "message": str(e), "suggestion": "请检查联系人姓名是否正确"}


_REASON_PRIORITY = {
    "热度下降": "高",
    "窗口未推进": "高",
    "高潜力未投入": "中",
    "需关注": "低",
}

_REASON_ACTION = {
    "热度下降": "重新建立联系，分享轻松内容，避免关系冷却",
    "窗口未推进": "推进关系，发起邀约或深入话题，抓住窗口期",
    "高潜力未投入": "主动联系，投入更多关注，测试对方反应",
    "需关注": "保持联系，观察信号变化，避免过度投入",
}


def maintain_list(limit: int = 10) -> dict:
    """获取需要维持关系的候选人列表。

    什么时候用：每周主动维护关系时，筛选需要联系的人。
    返回什么：dict 含 candidates 列表和 formatted Markdown。
    边界是什么：limit 控制返回候选人数。
    """
    try:
        candidates = maintain_candidates(max_people=limit)
        if isinstance(candidates, str):
            return {"error": "TOOL_ERROR", "message": candidates, "suggestion": "请检查数据库连接"}
        formatted = format_candidates(candidates)
        return {
            "candidates": [
                {
                    "name": c.name,
                    "rank": c.rank,
                    "priority": _REASON_PRIORITY.get(c.reason, "低"),
                    "reason": c.reason,
                    "signal_level": c.signal_level,
                    "recent_days": c.recent_days,
                    "composite": c.composite,
                    "trend": c.trend,
                    "interaction_pattern": c.interaction_pattern,
                    "last_msg_summary": c.last_msg_summary,
                    "suggested_action": _REASON_ACTION.get(c.reason, "保持联系，观察信号变化"),
                }
                for c in candidates
            ],
            "formatted": formatted,
        }
    except Exception as e:
        return {"error": "TOOL_ERROR", "message": str(e), "suggestion": "请检查数据库连接"}


# ── Phase 2 P1: events 拆分 ───────────────────────────────────


def events_scan(name: str, disconnect_days: int = 7) -> dict:
    """扫描关系事件（只读，不写入）。

    什么时候用：需要检测断联、恢复、频率变化等关系事件时。
    返回什么：dict 含 name/content 字段，content 为检测结果 Markdown。
    边界是什么：scan=False 只展示不写入；disconnect_days 控制断联判定阈值。
    """
    try:
        result = events(name, scan=False, disconnect_days=disconnect_days)
        return {"name": name, "content": result, "written": False}
    except Exception as e:
        return {"error": "PERSON_NOT_FOUND", "message": str(e), "suggestion": "请检查联系人姓名是否正确"}


# ── Phase 2 P1: system_sync + wcd_status ─────────────────────


def system_sync(mode: str = "incremental", meta_only: bool = False) -> dict:
    """全量/增量数据同步。

    什么时候用：需要同步所有联系人的微信数据时。⚠️ 可能耗时 1-5 分钟。
    返回什么：dict 含 success/message 字段。
    边界是什么：mode 默认 incremental（快），full 全量（慢）；meta_only 只同步联系人元数据。
    需要 WCD 后端运行中。
    """
    from engine.tools import sync as _sync
    try:
        result = _sync(mode=mode, meta_only=meta_only)
        return {"success": True, "message": result, "mode": mode}
    except Exception as e:
        return {"error": "TOOL_ERROR", "message": str(e), "suggestion": "确保 WCD 后端已启动"}


def wcd_status() -> dict:
    """检查 WCD 后端在线状态 + 密钥缓存状态，给出操作建议。

    什么时候用：同步前确认 WCD 后端是否在线、密钥是否可用。
    返回什么：dict 含 online/keys_cached/message/suggestion 字段。
    边界是什么：只读检查，不启动进程、不获取密钥、不修改任何状态。
    密钥安全：绝不自动调用 fetch_keys（封号风险），密钥失效时仅提示用户手动处理。
    """
    try:
        from engine.importers.wcd_client import WCDClient
        from engine.agent.core import _get_conn
        conn, config = _get_conn()
        try:
            if config.weflow.backend != "wcd":
                return {
                    "online": False,
                    "backend": config.weflow.backend,
                    "message": f"当前后端是 {config.weflow.backend}，非 WCD",
                    "suggestion": "无需 WCD 检查",
                }
            client = WCDClient(
                base_url=config.weflow.base_url,
                decrypted_db_dir=config.weflow.decrypted_db_dir or None,
            )
            online = client.health()
            keys = client.check_cached_keys()
            keys_cached = keys.get("cached", False)

            if online and keys_cached:
                return {
                    "online": True,
                    "keys_cached": True,
                    "message": "WCD 后端在线，密钥已缓存，可以正常同步",
                    "suggestion": None,
                }
            if online and not keys_cached:
                return {
                    "online": True,
                    "keys_cached": False,
                    "message": "WCD 后端在线，但密钥未缓存",
                    "suggestion": "请手动获取密钥并保存到 account_keys.json（注意封号风险，勿频繁获取）",
                }
            if not online and keys_cached:
                return {
                    "online": False,
                    "keys_cached": True,
                    "message": "WCD 后端未启动，但密钥已缓存",
                    "suggestion": "请手动启动 WCD 后端（密钥会自动加载），启动后即可同步",
                }
            return {
                "online": False,
                "keys_cached": False,
                "message": "WCD 后端未启动，密钥也未缓存",
                "suggestion": "请先手动获取密钥保存到 account_keys.json（注意封号风险），再启动 WCD 后端",
            }
        finally:
            conn.close()
    except Exception as e:
        return {"error": "TOOL_ERROR", "message": str(e), "suggestion": "请检查 WCD 配置"}


def wcd_start(timeout: int = 90) -> dict:
    """启动 WCD 后端进程并等待健康检查通过。

    什么时候用：wcd_status 显示 offline 时调此工具启动后端。
    返回什么：dict 含 success/message/already_running/pid 字段。
    边界是什么：如果 WCD 已在运行，直接返回成功。启动是异步的，进程会持续运行。
    默认 timeout=90s（WCD 后端冷启动通常需要 40-60s，留足余量）。
    密钥安全：不获取密钥，只启动进程。密钥缓存会自动加载。
    """
    import sys
    import time
    import subprocess
    from pathlib import Path

    try:
        from engine.importers.wcd_client import WCDClient
        from engine.agent.core import _get_conn
        conn, config = _get_conn()
        try:
            if config.weflow.backend != "wcd":
                return {
                    "success": False,
                    "message": f"当前后端是 {config.weflow.backend}，非 WCD，无需启动",
                }

            client = WCDClient(
                base_url=config.weflow.base_url,
                decrypted_db_dir=config.weflow.decrypted_db_dir or None,
            )

            # 1. 已在运行则直接返回
            if client.health():
                return {
                    "success": True,
                    "already_running": True,
                    "message": "WCD 后端已在运行，无需重复启动",
                }

            # 2. 定位 WCD 目录
            project_root = Path(__file__).resolve().parent.parent
            wcd_dir = project_root / "_reference" / "WeChatDataAnalysis"
            if not wcd_dir.exists():
                return {
                    "success": False,
                    "message": f"WCD 目录不存在: {wcd_dir}",
                    "suggestion": "请确认 WCD 后端代码已安装到 _reference/WeChatDataAnalysis/",
                }

            # 3. 启动进程（隐藏窗口）
            startupinfo = None
            creationflags = 0
            if sys.platform == 'win32':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                creationflags = subprocess.CREATE_NO_WINDOW

            proc = subprocess.Popen(
                ["uv", "run", "main.py"],
                cwd=str(wcd_dir),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                startupinfo=startupinfo,
                creationflags=creationflags,
            )

            # 4. 轮询健康检查
            start_time = time.time()
            while time.time() - start_time < timeout:
                time.sleep(2)
                if client.health():
                    elapsed = time.time() - start_time
                    return {
                        "success": True,
                        "already_running": False,
                        "pid": proc.pid,
                        "message": f"WCD 后端启动成功（PID: {proc.pid}，耗时 {elapsed:.1f}s）",
                    }
                if proc.poll() is not None:
                    return {
                        "success": False,
                        "pid": proc.pid,
                        "message": f"WCD 后端进程已退出（返回码: {proc.returncode}）",
                        "suggestion": "请手动在 WCD 目录运行 uv run main.py 查看错误信息",
                    }

            process_alive = proc.poll() is None
            return {
                "success": False,
                "pid": proc.pid,
                "process_alive": process_alive,
                "message": f"WCD 后端启动超时（{timeout}s），进程{'仍在运行' if process_alive else '已退出'}",
                "suggestion": "进程仍在运行则健康检查未就绪，可调 wcd_status 复查；进程已退出则需手动在 WCD 目录运行 uv run main.py 查看错误",
            }
        finally:
            conn.close()
    except FileNotFoundError:
        return {
            "success": False,
            "message": "未找到 uv 命令",
            "suggestion": "请确认 uv 已安装并在 PATH 中（pip install uv 或参考 https://docs.astral.sh/uv/）",
        }
    except Exception as e:
        return {"error": "TOOL_ERROR", "message": str(e), "suggestion": "请检查 WCD 配置和依赖"}


# WeFlow CDP 端口（固定为 9222，用于不重启清缓存）
WEFLOW_CDP_PORT = 9222


def _check_cdp_enabled(port: int = WEFLOW_CDP_PORT) -> tuple[bool, dict]:
    """检查 WeFlow 是否开启了 CDP（Chrome DevTools Protocol）端口。

    用于不重启 WeFlow 清缓存的方案：
    通过 CDP 调用 ipcRenderer.invoke('cache:clearAll') 清头像缓存。

    Args:
        port: CDP 端口号，默认 9222

    Returns:
        tuple (enabled: bool, info: dict)
        - enabled: CDP 是否可用
        - info: 包含 Browser/Protocol-Version 等信息（enabled=True 时）或错误信息
    """
    import json
    import urllib.request
    try:
        url = f"http://127.0.0.1:{port}/json/version"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=2) as resp:
            if resp.status != 200:
                return False, {"error": f"HTTP {resp.status}"}
            body = resp.read().decode("utf-8", errors="ignore")
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                return False, {"error": "invalid JSON"}
            if "Browser" in data or "webSocketDebuggerUrl" in data:
                return True, data
            return False, {"error": "not CDP response", "body": body[:200]}
    except Exception as e:
        return False, {"error": str(e)}


# ── CDP WebSocket 客户端（纯 Python 标准库实现，无新依赖） ──


def _cdp_ws_call(ws_url: str, method: str, params: dict | None = None,
                 timeout: float = 10.0) -> dict:
    """通过 WebSocket 调用 CDP 命令（纯 Python 标准库实现）。

    Args:
        ws_url: ws://127.0.0.1:9222/... 格式的 WebSocket URL
        method: CDP 方法名，如 "Runtime.evaluate"
        params: 方法参数 dict
        timeout: 超时秒数

    Returns:
        dict: CDP 响应的 result 字段

    Raises:
        RuntimeError: 握手失败 / 连接关闭 / CDP 返回 error
    """
    import base64
    import json as _json
    import os
    import socket
    import struct
    import urllib.parse

    parsed = urllib.parse.urlparse(ws_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 80
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query

    sock = socket.create_connection((host, port), timeout=timeout)
    try:
        sock.settimeout(timeout)

        # 1. WebSocket 握手
        ws_key = base64.b64encode(os.urandom(16)).decode("ascii")
        handshake = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {ws_key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n"
            f"\r\n"
        )
        sock.sendall(handshake.encode("ascii"))

        # 读取握手响应
        resp_buf = b""
        while b"\r\n\r\n" not in resp_buf:
            chunk = sock.recv(4096)
            if not chunk:
                raise RuntimeError("CDP handshake closed before completion")
            resp_buf += chunk

        status_line = resp_buf.split(b"\r\n", 1)[0]
        if b" 101 " not in status_line:
            raise RuntimeError(f"CDP handshake failed: {status_line.decode('ascii', errors='replace')}")

        # 多读的字节作为后续帧的 buffer
        leftover = resp_buf.split(b"\r\n\r\n", 1)[1] if b"\r\n\r\n" in resp_buf else b""

        # 2. 发送 CDP 命令
        # 注意：CDP 协议要求 id 为数字（Chrome 实测字符串 id 会无响应）
        # 每次调用都是新连接，固定用 1 不会冲突
        msg_id = 1
        cmd_payload = _json.dumps({
            "id": msg_id,
            "method": method,
            "params": params or {},
        }).encode("utf-8")
        _cdp_ws_send_frame(sock, cmd_payload, opcode=0x1)  # text frame

        # 3. 接收响应（最多等 timeout 秒）
        buffer = bytearray(leftover)
        deadline_check = 0
        import time
        start_time = time.time()
        while True:
            if time.time() - start_time > timeout:
                raise RuntimeError(f"CDP response timeout after {timeout}s")
            payload, buffer = _cdp_ws_recv_frame(sock, buffer)
            if payload is None:
                continue  # ping/pong/fragment header

            try:
                msg = _json.loads(payload.decode("utf-8"))
            except _json.JSONDecodeError:
                continue

            if msg.get("id") != msg_id:
                continue  # 其他 id 的消息（如事件通知），跳过

            if "error" in msg:
                raise RuntimeError(f"CDP error: {msg['error']}")
            return msg.get("result", {})
    finally:
        try:
            sock.close()
        except Exception:
            pass


def _cdp_ws_send_frame(sock, payload: bytes, opcode: int = 0x1):
    """发送 WebSocket frame（masked，客户端必须 mask）。"""
    import os
    import struct
    mask_key = os.urandom(4)

    first_byte = 0x80 | opcode  # FIN=1
    payload_len = len(payload)

    if payload_len < 126:
        header = struct.pack("!BB", first_byte, 0x80 | payload_len)
    elif payload_len < 65536:
        header = struct.pack("!BBH", first_byte, 0x80 | 126, payload_len)
    else:
        header = struct.pack("!BBQ", first_byte, 0x80 | 127, payload_len)

    masked = bytearray(payload_len)
    for i in range(payload_len):
        masked[i] = payload[i] ^ mask_key[i % 4]

    sock.sendall(header + mask_key + bytes(masked))


def _cdp_ws_recv_frame(sock, buffer: bytearray) -> tuple[bytes | None, bytearray]:
    """接收 WebSocket frame。返回 (payload, new_buffer)。

    payload 为 None 表示非数据帧（ping/pong/close）或分片延续帧（暂不支持）。
    """
    import struct

    # 至少 2 字节
    while len(buffer) < 2:
        chunk = sock.recv(4096)
        if not chunk:
            raise RuntimeError("CDP connection closed")
        buffer += chunk

    first_byte = buffer[0]
    second_byte = buffer[1]

    opcode = first_byte & 0x0F
    masked = (second_byte & 0x80) != 0
    payload_len = second_byte & 0x7F

    offset = 2

    if payload_len == 126:
        while len(buffer) < offset + 2:
            buffer += sock.recv(4096)
        payload_len = struct.unpack("!H", buffer[offset:offset + 2])[0]
        offset += 2
    elif payload_len == 127:
        while len(buffer) < offset + 8:
            buffer += sock.recv(4096)
        payload_len = struct.unpack("!Q", buffer[offset:offset + 8])[0]
        offset += 8

    mask_key = b""
    if masked:
        while len(buffer) < offset + 4:
            buffer += sock.recv(4096)
        mask_key = bytes(buffer[offset:offset + 4])
        offset += 4

    # 读取 payload
    while len(buffer) < offset + payload_len:
        chunk = sock.recv(4096)
        if not chunk:
            raise RuntimeError("CDP connection closed")
        buffer += chunk

    payload = bytes(buffer[offset:offset + payload_len])
    new_buffer = bytearray(buffer[offset + payload_len:])

    if masked:
        payload = bytes(payload[i] ^ mask_key[i % 4] for i in range(len(payload)))

    # 控制帧处理
    if opcode == 0x9:  # ping -> 自动回 pong
        _cdp_ws_send_frame(sock, payload, opcode=0xA)
        return None, new_buffer
    elif opcode == 0xA:  # pong
        return None, new_buffer
    elif opcode == 0x8:  # close
        return None, new_buffer
    elif opcode == 0x0:  # continuation（暂不支持分片）
        return None, new_buffer

    return payload, new_buffer


def _cdp_runtime_evaluate(ws_url: str, expression: str,
                          await_promise: bool = True,
                          timeout: float = 15.0) -> dict:
    """通过 CDP Runtime.evaluate 执行 JavaScript 表达式。

    Args:
        ws_url: WebSocket 调试 URL
        expression: JavaScript 表达式（如果是 Promise，需设 await_promise=True）
        await_promise: 是否等待 Promise 完成
        timeout: 超时秒数

    Returns:
        dict: 包含 success/value/error 字段
    """
    try:
        result = _cdp_ws_call(
            ws_url,
            "Runtime.evaluate",
            {
                "expression": expression,
                "awaitPromise": await_promise,
                "returnByValue": True,
            },
            timeout=timeout,
        )
        # result 结构：{"result": {"type": ..., "value": ..., "subtype": ...}}
        inner = result.get("result", {})
        if inner.get("subtype") == "error" or "exceptionDetails" in result:
            exception = result.get("exceptionDetails", {})
            return {
                "success": False,
                "error": "JavaScript exception",
                "details": exception,
            }
        return {
            "success": True,
            "value": inner.get("value"),
            "type": inner.get("type"),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def _refresh_weflow_avatar_cache_via_cdp() -> dict:
    """通过 CDP 调用 WeFlow 的 cache:clearAvatarCache IPC，清头像缓存（不重启 WeFlow）。

    前置条件：
      - WeFlow 以 --remote-debugging-port=9222 启动（CDP 已开启）
      - WeFlow 源码已修改并重新构建（包含 cache:clearAvatarCache IPC handler）

    清理范围：
      L2: chatService.avatarCache（主进程内存）
      L3: contactCacheService -> contacts.json（持久化）
      L4: avatarFileCacheService PNG 文件 LRU
    不清 L1（wcdbCore.avatarUrlCache worker 内存），等 10 分钟 TTL 自动失效。

    什么时候用：wechat_send 获取头像前调用，确保拿到最新头像。
    返回什么：dict 含 success/message/cdp_used/eval_result 字段。
    边界是什么：仅清头像缓存，不关闭 DB，不清消息/emoji。
    """
    import json
    import urllib.request

    # 1. 检查 CDP 是否开启
    cdp_enabled, cdp_info = _check_cdp_enabled()
    if not cdp_enabled:
        return {
            "success": False,
            "message": f"WeFlow CDP 未开启（端口 {WEFLOW_CDP_PORT}），无法通过 CDP 清缓存",
            "cdp_used": False,
            "eval_result": None,
            "cdp_error": cdp_info.get("error", "unknown"),
            "suggestion": (
                f"调 weflow_start 自动开启 CDP（端口 {WEFLOW_CDP_PORT}）后重试，"
                f"或手动用 WeFlow.exe --remote-debugging-port=9222 启动"
            ),
        }

    # 2. 获取 WeFlow renderer 页面列表
    try:
        url = f"http://127.0.0.1:{WEFLOW_CDP_PORT}/json"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            pages = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {
            "success": False,
            "message": f"获取 CDP 页面列表失败: {e}",
            "cdp_used": False,
            "eval_result": None,
        }

    # 3. 找一个 type=page 的页面（WeFlow 主窗口）
    target_page = None
    for page in pages:
        if page.get("type") == "page":
            target_page = page
            break

    if not target_page:
        return {
            "success": False,
            "message": f"CDP 未找到 type=page 的页面（pages={len(pages)}）",
            "cdp_used": False,
            "eval_result": None,
            "pages": [{"type": p.get("type"), "url": p.get("url", "")[:100]} for p in pages],
        }

    ws_url = target_page.get("webSocketDebuggerUrl")
    if not ws_url:
        return {
            "success": False,
            "message": "CDP 页面缺少 webSocketDebuggerUrl",
            "cdp_used": False,
            "eval_result": None,
        }

    # 4. 通过 CDP Runtime.evaluate 调用 window.electronAPI.cache.clearAvatarCache()
    #    先检查 API 是否存在（WeFlow 是否已重新构建包含新 IPC）
    js_expr = (
        "(function() {"
        "  if (!window.electronAPI || !window.electronAPI.cache "
        "      || typeof window.electronAPI.cache.clearAvatarCache !== 'function') {"
        "    return { success: false, error: 'clearAvatarCache API not available', "
        "             hint: 'WeFlow 需重新构建以包含 cache:clearAvatarCache IPC' };"
        "  }"
        "  return window.electronAPI.cache.clearAvatarCache().then(function(r) {"
        "    return { success: true, raw: r };"
        "  }).catch(function(e) {"
        "    return { success: false, error: String(e) };"
        "  });"
        "})()"
    )

    eval_result = _cdp_runtime_evaluate(ws_url, js_expr, await_promise=True, timeout=15.0)

    if not eval_result.get("success"):
        return {
            "success": False,
            "message": f"CDP Runtime.evaluate 失败: {eval_result.get('error', 'unknown')}",
            "cdp_used": True,
            "eval_result": eval_result,
            "ws_url": ws_url,
        }

    inner_value = eval_result.get("value") or {}
    if not inner_value.get("success"):
        return {
            "success": False,
            "message": f"WeFlow clearAvatarCache 调用失败: {inner_value.get('error', 'unknown')}",
            "cdp_used": True,
            "eval_result": eval_result,
            "ws_url": ws_url,
            "hint": inner_value.get("hint", ""),
        }

    return {
        "success": True,
        "message": "已通过 CDP 调用 clearAvatarCache 清头像缓存（L2/L3/L4）",
        "cdp_used": True,
        "eval_result": eval_result,
        "ws_url": ws_url,
        "raw": inner_value.get("raw"),
    }


def weflow_status() -> dict:
    """检查 WeFlow 后端在线状态（含 CDP 检测）。

    什么时候用：同步前确认 WeFlow 是否已启动。
    返回什么：dict 含 online/cdp_enabled/message/suggestion 字段。
    边界是什么：只读检查，不启动进程。

    CDP 用途：开启 CDP 后可不重启 WeFlow 清头像缓存（通过 ipcRenderer.invoke('cache:clearAll')）。
    未开启 CDP 时，刷新头像需要重启 WeFlow（用 weflow_start 自动重启会带上 CDP 参数）。
    """
    try:
        from engine.importers.weflow_client import WeFlowClient
        from engine.agent.core import _get_conn
        conn, config = _get_conn()
        try:
            if config.weflow.backend != "weflow":
                return {
                    "online": False,
                    "cdp_enabled": False,
                    "backend": config.weflow.backend,
                    "message": f"当前后端是 {config.weflow.backend}，非 WeFlow",
                    "suggestion": "无需 WeFlow 检查",
                }
            client = WeFlowClient(
                base_url=config.weflow.base_url,
                token=config.weflow.token,
                timeout=5,
            )
            online = client.health()
            # 同时检查 CDP 端口
            cdp_enabled, cdp_info = _check_cdp_enabled()
            if online:
                suggestion = None
                if not cdp_enabled:
                    suggestion = (
                        f"WeFlow 在线但未开启 CDP（端口 {WEFLOW_CDP_PORT}）。"
                        f"刷新头像需重启 WeFlow，或调 weflow_start 重启（自动加 CDP 参数）"
                    )
                return {
                    "online": True,
                    "cdp_enabled": cdp_enabled,
                    "cdp_port": WEFLOW_CDP_PORT if cdp_enabled else None,
                    "message": "WeFlow 后端在线" + ("，CDP 已开启" if cdp_enabled else "，CDP 未开启"),
                    "suggestion": suggestion,
                }
            return {
                "online": False,
                "cdp_enabled": False,
                "message": "WeFlow 后端未响应",
                "suggestion": "请手动启动 WeFlow（D:\\WeFlow\\WeFlow.exe），或用 weflow_start 工具",
            }
        finally:
            conn.close()
    except Exception as e:
        return {"error": "TOOL_ERROR", "message": str(e), "suggestion": "请检查 WeFlow 配置"}


def weflow_start(timeout: int = 60, force_restart_without_cdp: bool = True) -> dict:
    """启动 WeFlow 后端进程并等待健康检查通过（自动开启 CDP）。

    什么时候用：weflow_status 显示 offline 时调此工具启动 WeFlow。
    返回什么：dict 含 success/message/already_running/cdp_enabled 字段。
    边界是什么：
    - 如果 WeFlow 已在运行且 CDP 已开启，直接返回成功
    - 如果 WeFlow 已在运行但 CDP 未开启，按 force_restart_without_cdp 决定是否杀进程重启
    - 启动时自动加 --remote-debugging-port=9222 参数开启 CDP
    - 启动后进程持续运行，CDP 端口持续可用

    CDP 用途：开启 CDP 后可通过 ipcRenderer.invoke('cache:clearAll') 不重启清头像缓存。

    Args:
        timeout: 健康检查超时秒数
        force_restart_without_cdp: True=已在运行但 CDP 未开启时杀进程重启（默认）；
                                    False=不重启，返回 CDP 未开启警告
    """
    import platform
    import subprocess
    import time
    from pathlib import Path

    try:
        from engine.importers.weflow_client import WeFlowClient
        from engine.agent.core import _get_conn
        conn, config = _get_conn()
        try:
            if config.weflow.backend != "weflow":
                return {
                    "success": False,
                    "message": f"当前后端是 {config.weflow.backend}，非 WeFlow，无需启动",
                }

            client = WeFlowClient(
                base_url=config.weflow.base_url,
                token=config.weflow.token,
                timeout=5,
            )

            # 1. 已在运行 → 检查 CDP 状态
            if client.health():
                cdp_enabled, _ = _check_cdp_enabled()
                if cdp_enabled:
                    return {
                        "success": True,
                        "already_running": True,
                        "cdp_enabled": True,
                        "cdp_port": WEFLOW_CDP_PORT,
                        "message": "WeFlow 后端已在运行，CDP 已开启",
                    }
                # CDP 未开启
                if not force_restart_without_cdp:
                    return {
                        "success": True,
                        "already_running": True,
                        "cdp_enabled": False,
                        "message": "WeFlow 后端已在运行，但 CDP 未开启",
                        "suggestion": (
                            f"调 weflow_start(force_restart_without_cdp=True) 杀进程重启加 CDP，"
                            f"或手动关闭 WeFlow 后重调 weflow_start"
                        ),
                    }
                # 杀进程重启加 CDP
                try:
                    subprocess.run(
                        ['taskkill', '/F', '/IM', 'WeFlow.exe'],
                        capture_output=True, text=True, timeout=15,
                        encoding='utf-8', errors='ignore'
                    )
                    time.sleep(2)  # 等进程完全退出
                except Exception as e:
                    return {
                        "success": False,
                        "message": f"杀 WeFlow 进程失败: {e}",
                        "suggestion": "请手动关闭 WeFlow 后重调 weflow_start",
                    }

            # 2. 定位 WeFlow.exe
            weflow_exe = Path("D:/WeFlow/WeFlow.exe")
            if not weflow_exe.exists():
                return {
                    "success": False,
                    "message": f"WeFlow 不存在: {weflow_exe}",
                    "suggestion": "请确认 WeFlow 已安装到 D:\\WeFlow\\",
                }

            # 3. 启动进程（加 --remote-debugging-port 参数开启 CDP）
            proc = subprocess.Popen(
                [str(weflow_exe), f"--remote-debugging-port={WEFLOW_CDP_PORT}"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            # 4. 轮询健康检查 + CDP 端口
            start_time = time.time()
            while time.time() - start_time < timeout:
                time.sleep(2)
                if client.health():
                    cdp_enabled, cdp_info = _check_cdp_enabled()
                    elapsed = time.time() - start_time
                    if not cdp_enabled:
                        # HTTP 在线但 CDP 还没就绪，多等一会
                        cdp_enabled, cdp_info = _check_cdp_enabled()
                    return {
                        "success": True,
                        "already_running": False,
                        "cdp_enabled": cdp_enabled,
                        "cdp_port": WEFLOW_CDP_PORT if cdp_enabled else None,
                        "message": (
                            f"WeFlow 后端启动成功（耗时 {elapsed:.1f}s），"
                            f"CDP {'已开启' if cdp_enabled else '未开启'}"
                        ),
                        "suggestion": None if cdp_enabled else "CDP 端口未就绪，可调 weflow_status 复查",
                    }
                if proc.poll() is not None:
                    return {
                        "success": False,
                        "message": f"WeFlow 进程已退出（返回码: {proc.returncode}）",
                        "suggestion": "请手动运行 D:\\WeFlow\\WeFlow.exe 查看错误信息",
                    }

            process_alive = proc.poll() is None
            return {
                "success": False,
                "process_alive": process_alive,
                "message": f"WeFlow 启动超时（{timeout}s），进程{'仍在运行' if process_alive else '已退出'}",
                "suggestion": "进程仍在运行则 WeFlow 可能还在加载，可调 weflow_status 复查",
            }
        finally:
            conn.close()
    except Exception as e:
        return {"error": "TOOL_ERROR", "message": str(e), "suggestion": "请检查 WeFlow 配置"}


# ── Phase 2 P2: contact/sticker/exclude/failure 拆分 ─────────


def contact_search(query: str) -> dict:
    """搜索联系人信息。

    什么时候用：需要查找联系人、查看身份目录信息时。
    返回什么：dict 含 query/content 字段，content 为联系人信息 Markdown。
    边界是什么：query 支持姓名、别名、wxid 多种方式。
    """
    try:
        result = contact(query, action="search")
        return {"query": query, "content": result}
    except Exception as e:
        return {"error": "TOOL_ERROR", "message": str(e), "suggestion": "请检查查询参数"}


def sticker_scan(private_only: bool = True) -> dict:
    """扫描聊天中的贴纸表情（⚠️ 可能耗时）。

    什么时候用：需要建立贴纸词典、分析贴纸使用模式前先扫描。
    返回什么：dict 含 content 字段，content 为扫描结果摘要。
    边界是什么：private_only=True 只扫描私聊。
    """
    try:
        result = sticker(action="scan", private_only=private_only)
        return {"content": result, "private_only": private_only}
    except Exception as e:
        return {"error": "TOOL_ERROR", "message": str(e), "suggestion": "请检查数据库连接"}


def sticker_list(limit: int = 30, unlabeled: bool = False, min_freq: int = 1) -> dict:
    """列出贴纸词典。

    什么时候用：需要查看已扫描的贴纸列表和标注时。
    返回什么：dict 含 content 字段，content 为贴纸列表 Markdown。
    边界是什么：unlabeled=True 只看未标注的；min_freq 过滤最低频率。
    """
    try:
        result = sticker(action="list", limit=limit, unlabeled=unlabeled, min_freq=min_freq)
        return {"content": result, "limit": limit, "unlabeled": unlabeled}
    except Exception as e:
        return {"error": "TOOL_ERROR", "message": str(e), "suggestion": "请先运行 sticker_scan"}


def exclude_list() -> dict:
    """查看排除列表（硬排除 + 标签排除 + 手动排除）。

    什么时候用：需要了解哪些联系人被排除出排名及原因时。
    返回什么：dict 含 content 字段，content 为排除列表 Markdown。
    边界是什么：只读，不修改排除状态。
    """
    try:
        result = exclude(action="list")
        return {"content": result}
    except Exception as e:
        return {"error": "TOOL_ERROR", "message": str(e), "suggestion": "请检查数据库连接"}


def failure_list() -> dict:
    """查看所有失败案例。

    什么时候用：需要回顾历史失败教训、避免重蹈覆辙时。
    返回什么：dict 含 content 字段，content 为失败案例列表 Markdown。
    边界是什么：只读。
    """
    try:
        result = failure(action="list")
        return {"content": result}
    except Exception as e:
        return {"error": "TOOL_ERROR", "message": str(e), "suggestion": "请检查数据文件"}


# ── Phase 2 P2: message_context ──────────────────────────────


# ── WeChat 进程管理 ──────────────────────────────────────────

# 模块级 ctypes 初始化（避免每次调用重复定义类型）
import ctypes as _ctypes
from ctypes import wintypes as _wintypes

_user32 = _ctypes.windll.user32

class _RECT(_ctypes.Structure):
    _fields_ = [("left", _ctypes.c_long), ("top", _ctypes.c_long),
                ("right", _ctypes.c_long), ("bottom", _ctypes.c_long)]

_user32.EnumWindows.argtypes = [_wintypes.HANDLE, _wintypes.LPARAM]
_user32.EnumWindows.restype = _wintypes.BOOL
_user32.IsWindowVisible.argtypes = [_wintypes.HWND]
_user32.IsWindowVisible.restype = _wintypes.BOOL
_user32.GetWindowTextW.argtypes = [_wintypes.HWND, _wintypes.LPWSTR, _ctypes.c_int]
_user32.GetWindowTextW.restype = _ctypes.c_int
_user32.GetWindowTextLengthW.argtypes = [_wintypes.HWND]
_user32.GetWindowTextLengthW.restype = _ctypes.c_int
_user32.GetWindowRect.argtypes = [_wintypes.HWND, _ctypes.POINTER(_RECT)]
_user32.GetWindowRect.restype = _wintypes.BOOL
_user32.GetClassNameW.argtypes = [_wintypes.HWND, _wintypes.LPWSTR, _ctypes.c_int]
_user32.GetClassNameW.restype = _ctypes.c_int


def wechat_status() -> dict:
    """检查微信（Weixin.exe）是否在运行。

    什么时候用：启动 WCD 后端前需要确认微信已登录，或需要判断微信进程状态时。
    返回什么：dict 含 online/pid/message 字段。
    边界是什么：只读检查，不启动进程。
    """
    import subprocess
    import sys

    try:
        if sys.platform != 'win32':
            return {
                "online": False,
                "message": "非 Windows 系统，无法检查微信进程",
            }

        # Windows 中文环境下 tasklist 输出 GBK 编码
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq Weixin.exe", "/FO", "CSV"],
            capture_output=True, timeout=10,
        )
        import io
        raw = result.stdout
        # 尝试用 GBK 解码（中文 Windows 默认编码），回退到 utf-8
        try:
            text = raw.decode("gbk")
        except UnicodeDecodeError:
            text = raw.decode("utf-8", errors="replace")

        # tasklist /FO CSV 输出格式: "映像名称","PID","会话名","会话#","内存使用"
        # 没有匹配进程时只输出表头
        import csv
        reader = csv.reader(io.StringIO(text))
        header = next(reader, None)
        pids = []
        for row in reader:
            if row and len(row) >= 2:
                try:
                    pids.append(int(row[1]))
                except (ValueError, IndexError):
                    pass

        if pids:
            return {
                "online": True,
                "pid": pids[0],
                "count": len(pids),
                "message": f"微信正在运行（{len(pids)} 个进程，PID: {pids}）",
                "suggestion": None,
            }
        return {
            "online": False,
            "pid": None,
            "count": 0,
            "message": "微信未运行",
            "suggestion": "请使用 wechat_start 工具启动微信",
        }
    except FileNotFoundError:
        return {
            "online": False,
            "message": "未找到 tasklist 命令",
            "suggestion": "请确认系统环境正常",
        }
    except subprocess.TimeoutExpired:
        return {
            "online": False,
            "message": "检查微信进程超时",
            "suggestion": "请重试",
        }
    except Exception as e:
        return {"error": "TOOL_ERROR", "message": str(e), "suggestion": "请检查系统状态"}


def _find_wechat_window() -> dict | None:
    """查找微信主窗口，返回 HWND 和窗口尺寸。

    委托给 wechat_window_utils.find_wechat_window（统一窗口枚举实现）。
    匹配策略：标题精确"微信" > 标题含"微信" > 类名匹配（WeChat/Qt+WindowIcon）。

    Returns:
        dict with hwnd/left/top/width/height，未找到返回 None
    """
    from engine.wechat_sender.wechat_window_utils import find_wechat_window
    return find_wechat_window()


def _bring_window_to_front(hwnd: int):
    """将窗口置顶并激活。"""
    SWP_NOSIZE = 0x0001
    SWP_NOMOVE = 0x0002
    SWP_SHOWWINDOW = 0x0040
    _user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, SWP_NOSIZE | SWP_NOMOVE | SWP_SHOWWINDOW)
    _user32.SetForegroundWindow(hwnd)
    _user32.BringWindowToTop(hwnd)


def _remove_topmost(hwnd: int):
    """移除窗口置顶状态。"""
    SWP_NOSIZE = 0x0001
    SWP_NOMOVE = 0x0002
    _user32.SetWindowPos(hwnd, -2, 0, 0, 0, 0, SWP_NOSIZE | SWP_NOMOVE)


def _click_login_button(delay_before: float = 3.0, max_retries: int = 3) -> bool:
    """找到微信未登录窗口，置顶，点击登录按钮（窗口水平居中，垂直 77.3%）。

    改进：先验证窗口尺寸符合登录页特征（约 350x475，宽高比 ≈ 0.74），
    避免在已登录窗口（>500 宽）上误点。

    点击后检查窗口大小是否变化（登录成功后窗口会从登录页尺寸变为正常尺寸）。
    如果没变化则重试，最多 max_retries 次。

    Returns:
        True 表示点击成功（窗口大小已变化），False 表示重试耗尽仍未成功
    """
    import time

    time.sleep(delay_before)

    for attempt in range(1, max_retries + 1):
        win = _find_wechat_window()
        if not win:
            # 回退到屏幕居中 57% 点击
            SM_CXSCREEN = 0
            SM_CYSCREEN = 1
            screen_w = _user32.GetSystemMetrics(SM_CXSCREEN)
            screen_h = _user32.GetSystemMetrics(SM_CYSCREEN)
            click_x = screen_w // 2
            click_y = int(screen_h * 0.57)
            _user32.SetCursorPos(click_x, click_y)
            _user32.mouse_event(0x0002, 0, 0, 0, 0)  # MOUSEEVENTF_LEFTDOWN
            time.sleep(0.05)
            _user32.mouse_event(0x0004, 0, 0, 0, 0)  # MOUSEEVENTF_LEFTUP
            return False  # 无法确认窗口，直接返回

        # 记录点击前的窗口尺寸
        prev_w, prev_h = win["width"], win["height"]

        # 验证：已登录窗口（>500 宽）不应执行点击登录按钮
        if prev_w > 500:
            return True  # 已登录，视为成功（不需要点击）

        # 置顶窗口
        _bring_window_to_front(win["hwnd"])
        time.sleep(0.5)

        # 登录页面 350x475，按钮在 (175, 367)（左上角 0,0）
        # 折算为窗口相对位置：水平居中 50%，垂直 77.3%
        btn_x = win["left"] + int(win["width"] * 0.50)
        btn_y = win["top"] + int(win["height"] * 0.773)

        _user32.SetCursorPos(btn_x, btn_y)
        _user32.mouse_event(0x0002, 0, 0, 0, 0)  # MOUSEEVENTF_LEFTDOWN
        time.sleep(0.05)
        _user32.mouse_event(0x0004, 0, 0, 0, 0)  # MOUSEEVENTF_LEFTUP

        # 点击后移除置顶
        try:
            _remove_topmost(win["hwnd"])
        except Exception:
            pass

        # 等待窗口变化（登录后窗口尺寸会改变）
        time.sleep(2.0)
        win_after = _find_wechat_window()
        if win_after and (win_after["width"] != prev_w or win_after["height"] != prev_h):
            return True  # 窗口大小已变化，点击成功

        # 最后一次尝试不再等待
        if attempt < max_retries:
            time.sleep(1.0)

    return False  # 重试耗尽


def wechat_start(timeout: int = 30, click_login: bool = True) -> dict:
    """启动微信（Weixin.exe）并自动点击登录按钮。

    什么时候用：wechat_status 显示微信未运行时启动微信。
    返回什么：dict 含 success/message/already_running/clicked/logged_in 字段。
    边界是什么：
    - 如果微信进程已在运行，直接返回成功。
    - 如果微信已登录（托盘有图标/主窗口>500宽/有隐藏子窗口），拒绝重复登录。
    - click_login=True 时启动后自动点击登录按钮（登录页窗口水平居中，垂直 77.3%）。

    录屏功能：操作前自动开始录屏，成功删除，失败保留 7 天（路径在 recording_path 字段）。
    """
    from mcp_server.tools_wechat import _with_recording
    return _with_recording("wechat_start", _wechat_start_impl, timeout=timeout, click_login=click_login)


def _wechat_start_impl(timeout: int = 30, click_login: bool = True) -> dict:
    """wechat_start 的实现（不含录屏，由 wechat_start 包装）。"""
    import subprocess
    import sys
    import time
    from pathlib import Path

    try:
        # 1. 先检查是否已在运行
        status = wechat_status()
        if status.get("online"):
            # 进一步检测是否已登录（避免重复登录）
            try:
                from engine.wechat_sender.wechat_window_utils import check_login_status
                login_info = check_login_status()
                if login_info["logged_in"]:
                    return {
                        "success": True,
                        "already_running": True,
                        "already_logged_in": True,
                        "pid": status.get("pid"),
                        "message": f"微信已运行且已登录（PID: {status.get('pid')}），拒绝重复登录",
                        "login_details": {
                            "tray_icon_found": login_info["tray_icon_found"],
                            "tray_method": login_info["tray_method"],
                            "tray_confidence": login_info["tray_confidence"],
                            "main_window_size": login_info["main_window_size"],
                            "has_hidden_subwindow": login_info["has_hidden_subwindow"],
                        },
                    }
            except Exception:
                pass

            return {
                "success": True,
                "already_running": True,
                "already_logged_in": False,
                "pid": status.get("pid"),
                "message": "微信已在运行（未确认登录状态），无需重复启动",
            }

        # 2. 定位 Weixin.exe
        weixin_exe = Path("D:/Weixin/Weixin.exe")
        if not weixin_exe.exists():
            return {
                "success": False,
                "message": f"微信不存在: {weixin_exe}",
                "suggestion": "请确认微信已安装到 D:\\Weixin\\",
            }

        # 启动进程（GUI 应用，不隐藏窗口）
        proc = subprocess.Popen(
            [str(weixin_exe)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # 3. 轮询等待进程启动（不需要等登录，只要进程起来即可）
        start_time = time.time()
        launched_pid = None
        while time.time() - start_time < timeout:
            time.sleep(1)
            status = wechat_status()
            if status.get("online"):
                launched_pid = status.get("pid")
                break
            if proc.poll() is not None:
                return {
                    "success": False,
                    "message": f"微信进程已退出（返回码: {proc.returncode}）",
                    "suggestion": "请手动运行 D:\\Weixin\\Weixin.exe 查看错误信息",
                }

        if launched_pid:
            elapsed = time.time() - start_time
            clicked = False
            if click_login:
                try:
                    clicked = _click_login_button(delay_before=3.0, max_retries=3)
                except Exception:
                    pass
            msg = f"微信启动成功（PID: {launched_pid}，耗时 {elapsed:.1f}s）"
            if clicked:
                msg += "，已自动点击登录按钮（窗口已变化）"
            else:
                msg += "，点击登录按钮未确认成功（请手动点击登录）"
            return {
                "success": True,
                "already_running": False,
                "pid": launched_pid,
                "clicked": clicked,
                "message": msg,
                "suggestion": None if clicked else "请手动点击登录按钮，扫码完成登录",
            }

        process_alive = proc.poll() is None
        return {
            "success": False,
            "process_alive": process_alive,
            "message": f"微信启动超时（{timeout}s），进程{'仍在运行' if process_alive else '已退出'}",
            "suggestion": "进程仍在运行则微信可能正在加载，可调 wechat_status 复查",
        }
    except FileNotFoundError:
        return {
            "success": False,
            "message": "未找到微信可执行文件",
            "suggestion": "请确认 D:\\Weixin\\Weixin.exe 存在",
        }
    except Exception as e:
        return {"error": "TOOL_ERROR", "message": str(e), "suggestion": "请检查系统状态"}


def wechat_stop(force: bool = False) -> dict:
    """关闭微信（Weixin.exe）进程。

    什么时候用：需要关闭微信（如重启微信、释放资源、切换账号）时。
    返回什么：dict 含 success/message/killed_pids 字段。
    边界是什么：force=False 时先尝试优雅关闭（发送关闭信号），force=True 时强制终止。
    配合 wechat_start 可实现重启：wechat_stop → wechat_start。

    录屏功能：操作前自动开始录屏，成功删除，失败保留 7 天（路径在 recording_path 字段）。
    """
    from mcp_server.tools_wechat import _with_recording
    return _with_recording("wechat_stop", _wechat_stop_impl, force=force)


def _wechat_stop_impl(force: bool = False) -> dict:
    """wechat_stop 的实现（不含录屏，由 wechat_stop 包装）。"""
    import subprocess
    import sys
    import time

    try:
        if sys.platform != 'win32':
            return {
                "success": False,
                "message": "非 Windows 系统，无法关闭微信进程",
            }

        # 1. 先检查微信是否在运行
        status = wechat_status()
        if not status.get("online"):
            return {
                "success": True,
                "already_stopped": True,
                "message": "微信未运行，无需关闭",
            }

        killed_pids = status.get("pid")
        if isinstance(status.get("count"), int) and status["count"] > 1:
            # 多个进程时，获取所有 PID
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq Weixin.exe", "/FO", "CSV"],
                capture_output=True, timeout=10,
            )
            import io
            import csv
            try:
                text = result.stdout.decode("gbk")
            except UnicodeDecodeError:
                text = result.stdout.decode("utf-8", errors="replace")
            reader = csv.reader(io.StringIO(text))
            next(reader, None)  # 跳过表头
            killed_pids = []
            for row in reader:
                if row and len(row) >= 2:
                    try:
                        killed_pids.append(int(row[1]))
                    except (ValueError, IndexError):
                        pass

        # 2. 关闭进程
        if force:
            # 强制终止
            subprocess.run(
                ["taskkill", "/F", "/IM", "Weixin.exe"],
                capture_output=True, timeout=15,
            )
            method = "强制终止"
        else:
            # 优雅关闭：发送 WM_CLOSE 消息
            try:
                _find_wechat_window()  # 确保能找到窗口
                # 通过 taskkill 不带 /F 发送关闭信号
                subprocess.run(
                    ["taskkill", "/IM", "Weixin.exe"],
                    capture_output=True, timeout=15,
                )
                method = "优雅关闭"
            except Exception:
                # 回退到强制终止
                subprocess.run(
                    ["taskkill", "/F", "/IM", "Weixin.exe"],
                    capture_output=True, timeout=15,
                )
                method = "强制终止（优雅关闭失败，回退）"

        # 3. 等待进程退出（最多 10 秒）
        start_time = time.time()
        while time.time() - start_time < 10:
            time.sleep(1)
            check = wechat_status()
            if not check.get("online"):
                elapsed = time.time() - start_time
                return {
                    "success": True,
                    "killed_pids": killed_pids,
                    "method": method,
                    "message": f"微信已关闭（{method}，耗时 {elapsed:.1f}s）",
                }

        # 超时仍未退出
        return {
            "success": False,
            "killed_pids": killed_pids,
            "method": method,
            "message": f"微信关闭超时（{method}，10s 后仍在运行）",
            "suggestion": "可尝试 wechat_stop(force=True) 强制终止",
        }
    except FileNotFoundError:
        return {
            "success": False,
            "message": "未找到 taskkill 命令",
            "suggestion": "请确认系统环境正常",
        }
    except Exception as e:
        return {"error": "TOOL_ERROR", "message": str(e), "suggestion": "请检查系统状态"}


def message_context(message_ids: list[str], before: int = 20, after: int = 20) -> dict:
    """根据消息 ID 获取前后上下文消息。

    什么时候用：需要查看某条消息的上下文（前后对话）时。
    返回什么：dict 含 messages 列表及元信息。
    边界是什么：message_ids 是消息 ID 列表；before/after 控制上下文条数；不跨会话。
    """
    try:
        return message_context_data(message_ids, before=before, after=after)
    except Exception as e:
        return {"error": "TOOL_ERROR", "message": str(e), "suggestion": "请检查 message_ids 参数"}
