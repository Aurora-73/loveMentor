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


def weflow_status() -> dict:
    """检查 WeFlow 后端在线状态。

    什么时候用：同步前确认 WeFlow 是否已启动。
    返回什么：dict 含 online/message/suggestion 字段。
    边界是什么：只读检查，不启动进程。
    """
    try:
        from engine.importers.weflow_client import WeFlowClient
        from engine.agent.core import _get_conn
        conn, config = _get_conn()
        try:
            if config.weflow.backend != "weflow":
                return {
                    "online": False,
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
            if online:
                return {
                    "online": True,
                    "message": "WeFlow 后端在线，可以正常同步",
                    "suggestion": None,
                }
            return {
                "online": False,
                "message": "WeFlow 后端未响应",
                "suggestion": "请手动启动 WeFlow（D:\\WeFlow\\WeFlow.exe），或用 weflow_start 工具",
            }
        finally:
            conn.close()
    except Exception as e:
        return {"error": "TOOL_ERROR", "message": str(e), "suggestion": "请检查 WeFlow 配置"}


def weflow_start(timeout: int = 60) -> dict:
    """启动 WeFlow 后端进程并等待健康检查通过。

    什么时候用：weflow_status 显示 offline 时调此工具启动 WeFlow。
    返回什么：dict 含 success/message/already_running 字段。
    边界是什么：如果 WeFlow 已在运行，直接返回成功。启动后进程持续运行。
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

            # 1. 已在运行则直接返回
            if client.health():
                return {
                    "success": True,
                    "already_running": True,
                    "message": "WeFlow 后端已在运行，无需重复启动",
                }

            # 2. 定位 WeFlow.exe
            weflow_exe = Path("D:/WeFlow/WeFlow.exe")
            if not weflow_exe.exists():
                return {
                    "success": False,
                    "message": f"WeFlow 不存在: {weflow_exe}",
                    "suggestion": "请确认 WeFlow 已安装到 D:\\WeFlow\\",
                }

            # 3. 启动进程
            proc = subprocess.Popen(
                [str(weflow_exe)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
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
                        "message": f"WeFlow 后端启动成功（耗时 {elapsed:.1f}s）",
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

    匹配策略（按优先级）：
    1. 标题精确等于 "微信"
    2. 标题包含 "微信"
    3. 类名包含 "Qt" 且包含 "WindowIcon"（微信使用 Qt 框架）

    Returns:
        dict with hwnd/left/top/width/height，未找到返回 None
    """
    exact_match = None
    fuzzy_match = None
    class_match = None

    def enum_proc(hwnd, lparam):
        nonlocal exact_match, fuzzy_match, class_match
        if not _user32.IsWindowVisible(hwnd):
            return True

        # 获取窗口标题
        length = _user32.GetWindowTextLengthW(hwnd) + 1
        if length <= 1:
            title = ""
        else:
            buf = _ctypes.create_unicode_buffer(length)
            _user32.GetWindowTextW(hwnd, buf, length)
            title = buf.value

        # 获取窗口类名
        cls_buf = _ctypes.create_unicode_buffer(256)
        _user32.GetClassNameW(hwnd, cls_buf, 256)
        cls_name = cls_buf.value

        # 策略1: 精确匹配
        if title == "微信":
            exact_match = hwnd
            return False  # 最高优先级，直接停止
        # 策略2: 标题包含"微信"
        if "微信" in title and fuzzy_match is None:
            fuzzy_match = hwnd
        # 策略3: 类名含 Qt 且含 WindowIcon
        if "Qt" in cls_name and "WindowIcon" in cls_name and class_match is None:
            class_match = hwnd
        return True

    callback = _ctypes.WINFUNCTYPE(_wintypes.BOOL, _wintypes.HWND, _wintypes.LPARAM)(enum_proc)
    _user32.EnumWindows(callback, 0)

    found_hwnd = exact_match or fuzzy_match or class_match
    if not found_hwnd:
        return None

    rect = _RECT()
    _user32.GetWindowRect(found_hwnd, _ctypes.byref(rect))
    return {
        "hwnd": found_hwnd,
        "left": rect.left,
        "top": rect.top,
        "width": rect.right - rect.left,
        "height": rect.bottom - rect.top,
    }


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
    """找到微信窗口，置顶，点击登录按钮（窗口水平居中，垂直 77.3%）。

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
    返回什么：dict 含 success/message/already_running/clicked 字段。
    边界是什么：如果微信已在运行，直接返回成功。click_login=True 时启动后自动点击登录按钮（屏幕正中偏下 57% 位置）。
    """
    import subprocess
    import sys
    import time
    from pathlib import Path

    try:
        # 1. 先检查是否已在运行
        status = wechat_status()
        if status.get("online"):
            return {
                "success": True,
                "already_running": True,
                "pid": status.get("pid"),
                "message": "微信已在运行，无需重复启动",
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

        # 4. 轮询等待进程启动（不需要等登录，只要进程起来即可）
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
    """
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
