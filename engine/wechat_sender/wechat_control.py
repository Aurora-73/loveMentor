"""微信（Weixin.exe）进程控制：启动 / 停止 / 状态检查 / 登录按钮点击。

迁移自 mcp_server/tools_read.py L619-L1062，让 tools_read.py 成为薄包装。

功能：
  - wechat_status: 检查微信进程是否在运行
  - wechat_start: 启动微信并自动点击登录按钮（含录屏）
  - wechat_stop: 关闭微信进程（优雅/强制，含录屏）
  - _find_wechat_window: 查找微信主窗口
  - _bring_window_to_front / _remove_topmost: 窗口置顶控制
  - _click_login_button: 点击登录按钮

依赖：
  - engine.wechat_sender.wechat_window_utils（窗口枚举）
  - engine.wechat_sender.wechat_recorder（录屏包装）
"""
import ctypes
import csv
import io
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

# 模块级 ctypes 初始化（避免每次调用重复定义类型）
_user32 = ctypes.windll.user32

# 统一使用 wintypes.RECT（与 click_search_and_input.py / wechat_window_utils.py 一致）
# 避免不同模块用不同的 RECT 类型定义导致 argtypes 覆盖后类型不匹配


_user32.EnumWindows.argtypes = [wintypes.HANDLE, wintypes.LPARAM]
_user32.EnumWindows.restype = wintypes.BOOL
_user32.IsWindowVisible.argtypes = [wintypes.HWND]
_user32.IsWindowVisible.restype = wintypes.BOOL
_user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
_user32.GetWindowTextW.restype = ctypes.c_int
_user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
_user32.GetWindowTextLengthW.restype = ctypes.c_int
_user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
_user32.GetWindowRect.restype = wintypes.BOOL
_user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
_user32.GetClassNameW.restype = ctypes.c_int


def wechat_status() -> dict:
    """检查微信（Weixin.exe）是否在运行。

    什么时候用：启动 WCD 后端前需要确认微信已登录，或需要判断微信进程状态时。
    返回什么：dict 含 online/pid/message 字段。
    边界是什么：只读检查，不启动进程。
    """
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
        raw = result.stdout
        # 尝试用 GBK 解码（中文 Windows 默认编码），回退到 utf-8
        try:
            text = raw.decode("gbk")
        except UnicodeDecodeError:
            text = raw.decode("utf-8", errors="replace")

        # tasklist /FO CSV 输出格式: "映像名称","PID","会话名","会话#","内存使用"
        # 没有匹配进程时只输出表头
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
    from engine.wechat_sender.wechat_recorder import with_recording
    return with_recording("wechat_start", _wechat_start_impl, timeout=timeout, click_login=click_login)


def _wechat_start_impl(timeout: int = 30, click_login: bool = True) -> dict:
    """wechat_start 的实现（不含录屏，由 wechat_start 包装）。"""
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
    from engine.wechat_sender.wechat_recorder import with_recording
    return with_recording("wechat_stop", _wechat_stop_impl, force=force)


def _wechat_stop_impl(force: bool = False) -> dict:
    """wechat_stop 的实现（不含录屏，由 wechat_stop 包装）。"""
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
