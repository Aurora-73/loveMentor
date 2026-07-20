"""WeFlow 后端进程控制（启动 / 状态检查）。

迁移自 mcp_server/tools_read.py L539-L728，让 tools_read.py 成为薄包装。

功能：
  - weflow_status: 检查 WeFlow 后端在线状态（含 CDP 检测）
  - weflow_start: 启动 WeFlow 后端进程并等待健康检查通过（自动开启 CDP）

依赖：
  - engine.importers.weflow_client.WeFlowClient（HTTP 客户端）
  - engine.importers.weflow_cdp（CDP 基础设施）
  - engine.agent.core._get_conn（数据库连接 + 配置）
"""
import platform
import subprocess
import time
from pathlib import Path

from engine.importers.weflow_cdp import (
    WEFLOW_CDP_PORT,
    _check_cdp_enabled,
)


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
