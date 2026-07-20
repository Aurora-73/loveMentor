# -*- coding: utf-8 -*-
"""微信窗口管理编排层。

职责：
- 检查微信进程是否运行
- 确保微信主窗口可见（前置检查 + 多方法回退）
- 唤醒微信窗口（纯托盘唤醒，给 open_wechat_window MCP 工具用）

设计原则：
- 本模块只做窗口管理编排，不涉及 MCP 工具层职责
- 底层实现复用 engine/wechat_sender/ 内的现有模块：
  - open_wechat_window.open_wechat_window_robust（托盘唤醒）
  - click_search_and_input.click_taskbar_wechat（点击任务栏）
  - wechat_window_utils.restore_wechat_windows（ShowWindow 恢复）
  - wechat_window_utils.check_login_status（登录检查）
  - wechat_window_utils.ensure_wechat_window_width（宽度调整）
  - wechat_window_utils.find_wechat_window（窗口查找）
  - test_current_wechat.find_wechat_window（窗口查找，兼容）

回退顺序（v2 修正：先轻后重）：
1. 托盘唤醒（open_wechat_window_robust）
2. 点击任务栏微信图标（click_taskbar_wechat）
3. ShowWindow 恢复（restore_wechat_windows）
4. 启动新 Weixin.exe（最后兜底，重量级操作）
"""
import os
import sys
import ctypes
import logging

logger = logging.getLogger(__name__)

# 微信可执行文件路径（用于启动新进程兜底）
WEIXIN_EXE = r"D:\Weixin\Weixin.exe"


def is_wechat_running() -> bool:
    """检查微信进程是否在运行（不检查窗口）。"""
    try:
        import subprocess
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq Weixin.exe", "/NH"],
            capture_output=True, text=True, timeout=5,
        )
        return "Weixin.exe" in result.stdout
    except Exception:
        return False


def ensure_wechat_window(max_wait: float = 15.0) -> dict:
    """确保微信主窗口可见且已登录。

    改进：
    1. 检查微信是否已登录（托盘图标/主窗口尺寸/隐藏子窗口综合判定），未登录则拒绝发送
    2. 如果微信进程在运行但主窗口不可见（最小化到托盘），通过托盘图标唤醒
    3. 回退方法（先轻后重）：点击任务栏 → ShowWindow → 启动新进程

    Args:
        max_wait: 等待窗口出现的最大秒数

    Returns:
        dict: {
            "success": bool,
            "window_visible": bool,
            "logged_in": bool,
            "action": str,  # "already_visible" / "restored" / "process_not_running" / "not_logged_in" / "failed"
            "message": str,
        }
    """
    import time

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass

    from engine.wechat_sender.test_current_wechat import find_wechat_window

    # 1. 检查微信进程是否在运行
    process_running = is_wechat_running()
    if not process_running:
        return {
            "success": False,
            "window_visible": False,
            "logged_in": False,
            "action": "process_not_running",
            "message": "微信进程未运行，请先调用 wechat_start 启动微信",
        }

    # 2. 检查微信是否已登录（综合判定）
    try:
        from engine.wechat_sender.wechat_window_utils import check_login_status
        login_info = check_login_status()
        if not login_info["logged_in"]:
            return {
                "success": False,
                "window_visible": False,
                "logged_in": False,
                "action": "not_logged_in",
                "message": (
                    f"微信未登录（托盘图标={login_info['tray_icon_found']}, "
                    f"主窗口尺寸={login_info['main_window_size']}, "
                    f"隐藏子窗口={login_info['has_hidden_subwindow']}），"
                    f"请先调用 wechat_start 启动并登录微信"
                ),
            }
    except Exception:
        # 登录检测失败，继续尝试发送（保守策略，避免误拒）
        pass

    # 3. 检查主窗口是否已可见（必须 >= 500x400 才算主窗口）
    window = find_wechat_window()
    # 如果窗口存在但宽度不够，先调整窗口宽度（避免三栏布局问题 + 满足 500x400 阈值）
    if window and window["width"] < 1000:
        try:
            from engine.wechat_sender.wechat_window_utils import ensure_wechat_window_width
            width_result = ensure_wechat_window_width(min_width=1000, hwnd=window["hwnd"])
            if width_result["success"]:
                logger.info(
                    f"[窗口宽度调整] {width_result['old_width']}px → {width_result['new_width']}px "
                    f"({width_result['reason']})"
                )
                # 重新查找窗口（尺寸已变）
                window = find_wechat_window()
            else:
                logger.warning(f"[窗口宽度调整] 失败: {width_result['reason']}")
        except Exception as e:
            logger.warning(f"[窗口宽度调整] 异常: {e}")

    if window and window["width"] >= 500 and window["height"] >= 400:
        return {
            "success": True,
            "window_visible": True,
            "logged_in": True,
            "action": "already_visible",
            "message": f"微信主窗口已可见 ({window['width']}x{window['height']})",
        }

    # 4. 进程在运行已登录但窗口不可见，通过托盘图标唤醒（优先）
    try:
        from engine.wechat_sender.open_wechat_window import open_wechat_window_robust
        if open_wechat_window_robust(timeout=max_wait):
            window = find_wechat_window()
            # 唤醒后再次调整窗口宽度（可能唤醒后窗口尺寸变小）
            if window and window["width"] < 1000:
                try:
                    from engine.wechat_sender.wechat_window_utils import ensure_wechat_window_width
                    width_result = ensure_wechat_window_width(min_width=1000, hwnd=window["hwnd"])
                    if width_result["success"]:
                        logger.info(
                            f"[唤醒后窗口宽度调整] {width_result['old_width']}px → {width_result['new_width']}px"
                        )
                        window = find_wechat_window()
                except Exception as e:
                    logger.warning(f"[唤醒后窗口宽度调整] 异常: {e}")
            if window and window["width"] >= 500 and window["height"] >= 400:
                return {
                    "success": True,
                    "window_visible": True,
                    "logged_in": True,
                    "action": "restored",
                    "message": f"微信主窗口已通过托盘图标唤醒 ({window['width']}x{window['height']})",
                }
    except Exception:
        pass

    # 5. 回退方法 A: 点击任务栏微信图标（轻量级，优先尝试）
    try:
        from engine.wechat_sender.click_search_and_input import click_taskbar_wechat
        click_taskbar_wechat(max_wait=3.0)
    except Exception as e:
        pass

    # 回退方法 B: 用 ShowWindow 恢复最小化的窗口（Win32 API，轻量级）
    try:
        from engine.wechat_sender.wechat_window_utils import restore_wechat_windows
        restore_wechat_windows()
    except Exception:
        pass

    # 短暂等待方法 A/B 生效
    time.sleep(1.0)
    window = find_wechat_window()
    if window and window["width"] >= 500 and window["height"] >= 400:
        return {
            "success": True,
            "window_visible": True,
            "logged_in": True,
            "action": "restored",
            "message": f"微信主窗口已恢复可见 ({window['width']}x{window['height']}，方法A/B:点击任务栏+ShowWindow)",
        }

    # 回退方法 C: 启动新 Weixin.exe 触发已运行实例显示窗口（最后兜底，重量级操作）
    import subprocess
    try:
        subprocess.Popen(
            [WEIXIN_EXE],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        return {
            "success": False,
            "window_visible": False,
            "logged_in": True,
            "action": "launch_failed",
            "message": f"启动 Weixin.exe 失败: {e}",
        }

    # 6. 轮询等待窗口出现（必须 >= 500x400 才算主窗口恢复）
    start_time = time.time()
    while time.time() - start_time < max_wait:
        time.sleep(1.0)
        window = find_wechat_window()
        if window and window["width"] >= 500 and window["height"] >= 400:
            elapsed = time.time() - start_time
            return {
                "success": True,
                "window_visible": True,
                "logged_in": True,
                "action": "restored",
                "message": f"微信主窗口已恢复可见 ({window['width']}x{window['height']}，耗时 {elapsed:.1f}s)",
            }

    return {
        "success": False,
        "window_visible": False,
        "logged_in": True,
        "action": "timeout",
        "message": f"等待 {max_wait}s 后窗口仍未出现，可能微信被最小化到托盘且无法自动恢复",
    }


def wake_wechat_window(timeout: float = 10.0) -> dict:
    """唤醒微信窗口（纯托盘唤醒，给 open_wechat_window MCP 工具用）。

    与 ensure_wechat_window 的区别：
    - ensure_wechat_window: 前置检查（进程+登录）+ 多方法回退（给 wechat_send/wechat_ocr 用）
    - wake_wechat_window: 只做窗口检查 + 托盘唤醒（给用户主动调用）

    Args:
        timeout: 等待窗口出现的最大秒数

    Returns:
        dict: {
            "success": bool,
            "message": str,
            "action": str,  # "already_visible" / "tray_click" / "failed"
            "window": dict|None,
            "elapsed": float|None,
            "error": str|None,
        }
    """
    import time
    from engine.wechat_sender.open_wechat_window import open_wechat_window_robust
    from engine.wechat_sender.wechat_window_utils import find_wechat_window

    # 先检查窗口是否已可见
    existing = find_wechat_window()
    if existing and existing["width"] >= 500 and existing["height"] >= 400:
        return {
            "success": True,
            "message": f"微信窗口已可见 ({existing['width']}x{existing['height']})，无需唤醒",
            "action": "already_visible",
            "window": {
                "hwnd": existing["hwnd"],
                "width": existing["width"],
                "height": existing["height"],
            },
            "elapsed": 0.0,
            "error": None,
        }

    # 托盘点击唤醒
    start_time = time.time()
    success = open_wechat_window_robust(timeout=timeout)
    elapsed = time.time() - start_time

    if success:
        window = find_wechat_window()
        return {
            "success": True,
            "message": f"已通过托盘图标唤醒微信窗口（耗时 {elapsed:.1f}s）",
            "action": "tray_click",
            "window": {
                "hwnd": window["hwnd"] if window else 0,
                "width": window["width"] if window else 0,
                "height": window["height"] if window else 0,
            },
            "elapsed": round(elapsed, 2),
            "error": None,
        }
    else:
        return {
            "success": False,
            "message": (
                f"托盘点击唤醒失败（耗时 {elapsed:.1f}s）。"
                f"可能原因：1) 微信进程未启动  2) 托盘图标被隐藏到溢出区  "
                f"3) HSV 颜色匹配未命中（图标可能处于闪烁暗态）"
            ),
            "action": "failed",
            "window": None,
            "elapsed": round(elapsed, 2),
            "error": "TRAY_CLICK_FAILED",
        }
