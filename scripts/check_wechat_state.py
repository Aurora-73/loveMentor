"""微信窗口状态检测脚本。

用于校对窗口检测逻辑：用户把微信调到不同状态，运行此脚本记录各种检测值。

支持检测的5种状态：
1. 微信进程未运行
2. 微信进程运行，窗口关闭到托盘（不可见）
3. 微信进程运行，窗口最小化到任务栏
4. 微信进程运行，窗口正常显示但在后台（非前台）
5. 微信进程运行，窗口正常显示并前台

用法：
    python -X utf8 scripts/check_wechat_state.py
    python -X utf8 scripts/check_wechat_state.py --watch  # 持续监听模式，每秒打印一次状态
"""
import os
import sys
import time
import argparse
import ctypes
import ctypes.wintypes as wintypes

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# numpy 和 PIL 用于 icon 模板匹配
try:
    import numpy as np
    import cv2
    from PIL import Image
    _HAS_CV = True
except ImportError:
    _HAS_CV = False

# 设置函数原型
user32.EnumWindows.argtypes = [wintypes.HANDLE, wintypes.LPARAM]
user32.EnumWindows.restype = wintypes.BOOL
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindow.restype = wintypes.BOOL
user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsIconic.restype = wintypes.BOOL
user32.IsZoomed.argtypes = [wintypes.HWND]
user32.IsZoomed.restype = wintypes.BOOL
user32.GetForegroundWindow.argtypes = []
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowRect.restype = wintypes.BOOL
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowW.restype = wintypes.HWND

# 微信窗口匹配关键词
WECHAT_TITLE_KEYWORDS = ("微信", "WeChat", "Weixin")
WECHAT_CLASS_KEYWORDS = ("WeChat", "Weixin", "WeChatMainWnd")


def get_process_name_by_pid(pid):
    """通过 PID 查询进程名（用于排除 Snipaste 等 Qt 框架窗口的误判）。

    用 QueryFullProcessImageNameW（只需 PROCESS_QUERY_LIMITED_INFORMATION 权限，
    不需要 PROCESS_VM_READ，普通用户权限即可）。
    """
    try:
        kernel32 = ctypes.windll.kernel32
        # PROCESS_QUERY_LIMITED_INFORMATION = 0x1000（普通用户权限即可）
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        hProcess = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not hProcess:
            return None
        try:
            buf = ctypes.create_unicode_buffer(260)
            size = wintypes.DWORD(260)
            # QueryFullProcessImageNameW 不需要 PROCESS_VM_READ
            if kernel32.QueryFullProcessImageNameW(hProcess, 0, buf, ctypes.byref(size)):
                return os.path.basename(buf.value)
            return None
        finally:
            kernel32.CloseHandle(hProcess)
    except Exception:
        return None


def is_wechat_window(title, class_name, pid=None):
    """判断窗口是否为微信相关窗口。

    改进：加上进程名验证，排除 Snipaste 等 Qt 框架窗口的误判。
    Snipaste 也用 Qt，class='Qt624QWindowIcon'，会被 "Qt + WindowIcon" 规则误判。

    保守策略：如果 PID 查询进程名失败，不回退到 Qt+WindowIcon 匹配（可能误判）。
    只有标题/类名明确含微信关键词，或进程名确认是微信，才算微信窗口。
    """
    # 标题或类名明确匹配微信关键词
    title_match = any(kw in title for kw in WECHAT_TITLE_KEYWORDS)
    class_match = any(kw in class_name for kw in WECHAT_CLASS_KEYWORDS)
    qt_match = "Qt" in class_name and "WindowIcon" in class_name

    if not (title_match or class_match or qt_match):
        return False

    # 如果有 PID，验证进程名（排除 Snipaste 等误判）
    if pid is not None:
        proc_name = get_process_name_by_pid(pid)
        if proc_name:
            # 只接受微信相关进程
            wechat_procs = ("Weixin.exe", "WeChat.exe", "WeChatAppEx.exe")
            if any(proc_name == name for name in wechat_procs):
                return True
            # 进程名不匹配，排除
            return False
        else:
            # 进程名查询失败：保守策略
            # 只有标题/类名明确匹配微信关键词才算（不靠 Qt+WindowIcon）
            if title_match or class_match:
                return True
            return False

    # 没有 PID 信息时，回退到原逻辑（标题/类名匹配）
    return title_match or class_match or qt_match


def check_wechat_process():
    """检查微信进程是否在运行。

    新版微信改名为 Weixin.exe（旧版是 WeChat.exe），还可能有 WeChatAppEx.exe（小程序）。
    """
    try:
        import subprocess
        # 查询所有进程，过滤微信相关
        result = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=5, encoding="gbk", errors="ignore"
        )
        lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]

        # 微信相关进程名（新版 Weixin.exe，旧版 WeChat.exe，小程序 WeChatAppEx.exe）
        wechat_process_names = ("Weixin.exe", "WeChat.exe", "WeChatAppEx.exe")
        wechat_lines = []
        for line in lines:
            for name in wechat_process_names:
                if name in line:
                    wechat_lines.append(line)
                    break

        if not wechat_lines:
            return {"running": False, "pid": None, "count": 0, "all_pids": []}

        # 解析 PID（CSV 格式："Weixin.exe","1234","Console","1","xxx K"）
        pids = []
        process_names = {}
        for line in wechat_lines:
            parts = line.split(",")
            if len(parts) >= 2:
                name = parts[0].strip('"')
                pid_str = parts[1].strip('"')
                try:
                    pid = int(pid_str)
                    pids.append(pid)
                    process_names[pid] = name
                except ValueError:
                    pass

        # 主进程优先 Weixin.exe / WeChat.exe（非 WeChatAppEx.exe）
        main_pids = [pid for pid, name in process_names.items()
                     if name in ("Weixin.exe", "WeChat.exe")]
        main_pid = main_pids[0] if main_pids else (pids[0] if pids else None)

        return {
            "running": True,
            "pid": main_pid,
            "count": len(pids),
            "all_pids": pids,
            "process_names": process_names,
        }
    except Exception as e:
        return {"running": None, "error": str(e)}


def enumerate_all_windows():
    """枚举所有窗口（包括不可见的），返回窗口信息列表。"""
    windows = []

    def enum_proc(hwnd, lparam):
        # 不限制 IsWindowVisible，枚举所有窗口
        length = user32.GetWindowTextLengthW(hwnd) + 1
        if length <= 1:
            title = ""
        else:
            buf = ctypes.create_unicode_buffer(length)
            user32.GetWindowTextW(hwnd, buf, length)
            title = buf.value
        cls_buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls_buf, 256)
        cls_name = cls_buf.value
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        pid = wintypes.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        windows.append({
            "hwnd": hwnd,
            "title": title,
            "class": cls_name,
            "is_window": bool(user32.IsWindow(hwnd)),
            "is_visible": bool(user32.IsWindowVisible(hwnd)),
            "is_iconic": bool(user32.IsIconic(hwnd)),
            "is_zoomed": bool(user32.IsZoomed(hwnd)),
            "left": rect.left,
            "top": rect.top,
            "right": rect.right,
            "bottom": rect.bottom,
            "width": rect.right - rect.left,
            "height": rect.bottom - rect.top,
            "pid": pid.value,
        })
        return True

    callback = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)(enum_proc)
    user32.EnumWindows(callback, 0)
    return windows


def find_wechat_windows_all_states():
    """找所有微信相关窗口（包括不可见/最小化的）。

    Returns:
        list[dict]: 微信窗口列表
    """
    all_windows = enumerate_all_windows()
    return [w for w in all_windows
            if is_wechat_window(w["title"], w["class"], w["pid"])]


def check_tray_icon():
    """检查托盘是否有微信图标（优先用 icon 模板匹配，fallback 到 HSV）。

    改进：优先用 wx_icon/1.ico ~ 6.ico 模板匹配（更准确，避免误判其他绿色软件）。
    如果 icon 匹配失败或依赖不可用，回退到 HSV 颜色匹配。

    Returns:
        dict: {"found": bool, "position": (x, y) or None, "method": str, "confidence": float}
    """
    try:
        # 复用 open_wechat_window 的托盘检测逻辑
        sys.path.insert(0, os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "engine", "wechat_sender"
        ))
        from open_wechat_window import _find_tray_window, _capture_region, _find_wechat_icon_in_tray, TRAY_RIGHT_RATIO

        tray = _find_tray_window()
        if not tray:
            return {"found": False, "error": "未找到任务栏"}

        # 扫描任务栏右侧
        tray_left = int(tray["right"] - tray["width"] * TRAY_RIGHT_RATIO)
        tray_top = tray["top"]
        tray_width = int(tray["width"] * TRAY_RIGHT_RATIO)
        tray_height = tray["height"]
        tray_img = _capture_region(tray_left, tray_top, tray_width, tray_height)
        if tray_img is None:
            return {"found": False, "error": "托盘截图失败"}

        tray_rect = {
            "left": tray_left, "top": tray_top,
            "width": tray_width, "height": tray_height
        }

        # 优先用 icon 模板匹配
        if _HAS_CV:
            icons = _load_wx_icons()
            if icons:
                result = _find_wechat_icon_by_template(tray_img, icons, tray_left, tray_top)
                if result:
                    return {"found": True, "position": (result[0], result[1]),
                            "method": "icon_template", "confidence": result[2],
                            "tray_rect": tray_rect}
                # icon 匹配失败，回退到 HSV
            else:
                print("  ⚠️ 未加载到 wx_icon 图标模板，回退到 HSV")
        else:
            print("  ⚠️ cv2/PIL/numpy 不可用，回退到 HSV")

        # fallback: HSV 颜色匹配
        result = _find_wechat_icon_in_tray(tray_img, tray_left, tray_top)
        if result:
            return {"found": True, "position": result, "method": "hsv_fallback",
                    "confidence": None, "tray_rect": tray_rect}
        return {"found": False, "method": "icon+hsv", "confidence": None,
                "tray_rect": tray_rect}
    except Exception as e:
        return {"found": None, "error": str(e)}


def _load_wx_icons():
    """加载微信图标模板（用于模板匹配）。

    从 engine/wechat_sender/wx_icon/1.ico ~ 6.ico 加载图标。

    Returns:
        list[np.ndarray]: 图标模板列表（BGR 格式），加载失败返回空列表
    """
    if not _HAS_CV:
        return []
    icon_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "engine", "wechat_sender", "wx_icon"
    )
    if not os.path.isdir(icon_dir):
        return []
    icons = []
    for i in range(1, 7):
        icon_path = os.path.join(icon_dir, f"{i}.ico")
        if not os.path.isfile(icon_path):
            continue
        try:
            img = Image.open(icon_path).convert("RGB")
            arr = np.array(img)[:, :, ::-1].copy()  # RGB → BGR
            icons.append(arr)
        except Exception as e:
            print(f"  ⚠️ 加载图标 {icon_path} 失败: {e}")
    return icons


def _find_wechat_icon_by_template(tray_img, icons, tray_left, tray_top, threshold=0.6):
    """用模板匹配找微信图标。

    Args:
        tray_img: 托盘区域截图 (BGR)
        icons: 图标模板列表（BGR）
        tray_left, tray_top: 托盘区域在屏幕上的左上角坐标
        threshold: 匹配阈值 (0-1)，低于此值视为未匹配

    Returns:
        (screen_x, screen_y, confidence) 或 None
    """
    if tray_img is None or not icons:
        return None

    best_match = None
    best_conf = 0.0
    # 托盘图标通常 20-32px，尝试多种尺寸
    for icon in icons:
        for size in [20, 24, 28, 32]:
            resized = cv2.resize(icon, (size, size), interpolation=cv2.INTER_AREA)
            result = cv2.matchTemplate(tray_img, resized, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)
            if max_val > best_conf and max_val >= threshold:
                best_conf = max_val
                cx = max_loc[0] + size // 2
                cy = max_loc[1] + size // 2
                best_match = (tray_left + cx, tray_top + cy, max_val)

    return best_match


def detect_state():
    """检测微信窗口当前状态。

    状态判定优先级：
    1. 进程未运行 → A1
    2. 进程运行 + 无可见窗口 + 托盘有图标 → C3（关闭到托盘）
    3. 进程运行 + 可见窗口 + 前台=微信 → C1/B1（前台）
    4. 进程运行 + 可见窗口 + 前台≠微信 → C2/B2（后台）
    5. 多个不同 PID 的主窗口 → E（多开，附加状态）
    6. 子窗口识别（搜索窗口/历史聊天界面/私聊独立窗口）

    区分 B/C（未登录/已登录）：
    - 托盘图标（True=已登录）
    - 主窗口尺寸（>500 宽=已登录）
    - 同 PID 下有隐藏子窗口 'Weixin'（已登录才有）

    Returns:
        dict: 包含状态判定和各种检测值
    """
    # 1. 所有微信窗口（包括不可见/最小化）
    wechat_windows = find_wechat_windows_all_states()

    # 2. 进程状态
    process_info = check_wechat_process()
    wechat_pids = set(process_info.get("all_pids", []))

    # 3. 当前前台窗口
    foreground_hwnd = user32.GetForegroundWindow()
    fg_title = ""
    fg_class = ""
    fg_pid = 0
    if foreground_hwnd:
        buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(foreground_hwnd, buf, 256)
        fg_title = buf.value
        cls_buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(foreground_hwnd, cls_buf, 256)
        fg_class = cls_buf.value
        pid = wintypes.DWORD(0)
        user32.GetWindowThreadProcessId(foreground_hwnd, ctypes.byref(pid))
        fg_pid = pid.value

    # 4. 托盘图标
    tray_info = check_tray_icon()

    # 5. 分类窗口
    # 主窗口：title='微信'
    main_windows = [w for w in wechat_windows if w["title"] == "微信"]
    # 隐藏子窗口：title='Weixin' + 不可见
    hidden_sub_windows = [w for w in wechat_windows
                          if w["title"] == "Weixin" and not w["is_visible"]]
    # 搜索窗口：class 含 'ToolSaveBits'
    search_windows = [w for w in wechat_windows if "ToolSaveBits" in w["class"]]
    # 历史聊天界面：title='搜索聊天记录'
    history_windows = [w for w in wechat_windows if w["title"] == "搜索聊天记录"]
    # 私聊独立窗口：title 不在已知列表 + class='Qt51514QWindowIcon' + PID=微信进程
    known_titles = {"微信", "Weixin", "搜索聊天记录"}
    private_chat_windows = [w for w in wechat_windows
                            if w["title"] not in known_titles
                            and w["pid"] in wechat_pids
                            and "WindowIcon" in w["class"]]

    # 6. 多开识别：统计不同 PID 的主窗口数
    main_window_pids = set(w["pid"] for w in main_windows)
    is_multi_open = len(main_window_pids) >= 2

    # 7. 状态判定
    login_state = "未知"
    if not process_info["running"] and not wechat_windows:
        state = "进程未运行（程序退出）"
    elif wechat_windows:
        # 选主窗口：优先 title='微信' 中面积最大的
        if main_windows:
            main_win = max(main_windows, key=lambda w: w["width"] * w["height"])
        else:
            main_win = max(wechat_windows, key=lambda w: w["width"] * w["height"])

        # 登录状态判定（多维度综合）
        # 已登录特征：托盘有图标 / 主窗口宽 > 500 / 同 PID 有隐藏子窗口
        has_tray_icon = tray_info.get("found") is True
        is_large_window = main_win["width"] > 500
        has_hidden_sub = any(w["pid"] == main_win["pid"] for w in hidden_sub_windows)
        is_logged_in = has_tray_icon or is_large_window or has_hidden_sub
        login_state = "已登录" if is_logged_in else "未登录"

        # 窗口可见性 + 前台判定
        if not main_win["is_visible"]:
            state = "窗口不可见（关闭到托盘）"
        elif main_win["is_iconic"]:
            state = "窗口最小化到任务栏"
        elif main_win["hwnd"] == foreground_hwnd:
            state = "窗口正常显示并前台"
        elif fg_pid == main_win["pid"] or fg_pid in main_window_pids:
            # 前台是微信相关窗口（但不是主窗口，是子窗口）
            state = f"主窗口在后台（前台是微信子窗口: {fg_title!r}）"
        else:
            state = "窗口正常显示但在后台"

        # 多开标注
        if is_multi_open:
            state = f"[多开 {len(main_window_pids)} 个] " + state
    else:
        state = "进程运行但无窗口（仅托盘）"

    # 8. 子窗口信息列表
    sub_windows_info = []
    for w in search_windows:
        sub_windows_info.append({"type": "搜索窗口", **{k: w[k] for k in ("hwnd", "title", "pid", "is_visible")}})
    for w in history_windows:
        sub_windows_info.append({"type": "历史聊天界面", **{k: w[k] for k in ("hwnd", "title", "pid", "is_visible")}})
    for w in private_chat_windows:
        sub_windows_info.append({"type": "私聊独立窗口", **{k: w[k] for k in ("hwnd", "title", "pid", "is_visible")}})
    for w in hidden_sub_windows:
        sub_windows_info.append({"type": "隐藏子窗口", **{k: w[k] for k in ("hwnd", "title", "pid", "is_visible")}})

    return {
        "state": state,
        "login_state": login_state,
        "is_multi_open": is_multi_open,
        "main_window_count": len(main_windows),
        "main_window_pids": list(main_window_pids),
        "process": process_info,
        "wechat_windows": wechat_windows,
        "main_windows": main_windows,
        "sub_windows": sub_windows_info,
        "foreground": {
            "hwnd": foreground_hwnd,
            "title": fg_title,
            "class": fg_class,
            "pid": fg_pid,
            "is_wechat": fg_pid in wechat_pids,
        },
        "tray": tray_info,
        "timestamp": time.strftime("%H:%M:%S"),
    }


def print_state(info):
    """打印状态信息。"""
    print(f"\n{'='*60}")
    print(f"  微信窗口状态检测  {info['timestamp']}")
    print(f"{'='*60}")
    print(f"\n[状态判定] {info['state']}")
    print(f"[登录状态] {info.get('login_state', '未知')}")
    if info.get("is_multi_open"):
        print(f"[多开识别] 检测到 {info['main_window_count']} 个主窗口，{len(info['main_window_pids'])} 个不同 PID: {info['main_window_pids']}")

    # 进程信息
    p = info["process"]
    print(f"\n[1] 进程状态:")
    print(f"    运行中: {p['running']}")
    if p["running"]:
        print(f"    主 PID: {p['pid']}")
        print(f"    进程数: {p['count']}")
        print(f"    所有 PID: {p.get('all_pids', [])}")
    elif "error" in p:
        print(f"    错误: {p['error']}")

    # 微信窗口
    wins = info["wechat_windows"]
    print(f"\n[2] 微信窗口（枚举所有，含不可见）: {len(wins)} 个")
    for i, w in enumerate(wins):
        print(f"    #{i+1}: hwnd={w['hwnd']} title={w['title']!r} class={w['class']!r}")
        print(f"        is_window={w['is_window']} is_visible={w['is_visible']} "
              f"is_iconic={w['is_iconic']} is_zoomed={w['is_zoomed']}")
        print(f"        rect=({w['left']},{w['top']},{w['right']},{w['bottom']}) "
              f"size={w['width']}x{w['height']} pid={w['pid']}")

    # 子窗口分类
    subs = info.get("sub_windows", [])
    if subs:
        print(f"\n[2.1] 子窗口分类: {len(subs)} 个")
        for s in subs:
            print(f"    [{s['type']}] hwnd={s['hwnd']} title={s['title']!r} pid={s['pid']} visible={s['is_visible']}")

    # 前台窗口
    fg = info["foreground"]
    print(f"\n[3] 当前前台窗口:")
    print(f"    hwnd={fg['hwnd']} title={fg['title']!r} class={fg['class']!r} pid={fg.get('pid', 0)}")
    print(f"    是微信相关窗口: {fg.get('is_wechat', False)}")

    # 托盘图标
    t = info["tray"]
    print(f"\n[4] 托盘微信图标:")
    print(f"    找到: {t['found']}")
    if t["found"]:
        print(f"    位置: {t['position']}")
        print(f"    匹配方法: {t.get('method', 'unknown')}")
        if t.get("confidence") is not None:
            print(f"    匹配置信度: {t['confidence']:.3f}")
    if "error" in t:
        print(f"    错误: {t['error']}")
    if "tray_rect" in t:
        tr = t["tray_rect"]
        print(f"    扫描区域: ({tr['left']},{tr['top']}) {tr['width']}x{tr['height']}")

    print(f"\n{'='*60}")


def main():
    parser = argparse.ArgumentParser(description="微信窗口状态检测")
    parser.add_argument("--watch", action="store_true",
                        help="持续监听模式，每秒打印一次状态（按 Ctrl+C 退出）")
    parser.add_argument("--interval", type=float, default=1.0,
                        help="监听模式间隔秒数（默认 1.0）")
    args = parser.parse_args()

    if args.watch:
        print("持续监听模式（按 Ctrl+C 退出）")
        try:
            while True:
                info = detect_state()
                # 简洁输出：时间 + 登录状态 + 状态 + 窗口数
                login = info.get("login_state", "未知")
                multi = f" [多开{info['main_window_count']}个]" if info.get("is_multi_open") else ""
                wins = info["wechat_windows"]
                win_info = f" | 窗口数={len(wins)}" if wins else ""
                print(f"[{info['timestamp']}] [{login}]{multi} {info['state']}{win_info}")
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\n退出监听")
    else:
        info = detect_state()
        print_state(info)


if __name__ == "__main__":
    main()
