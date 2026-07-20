"""微信窗口枚举公共模块。

统一所有 EnumWindows 实现，提供窗口查找、统计、恢复、登录状态检测功能。
消除 6 个文件中 7 处重复的 EnumWindows 代码。

使用方式:
    from wechat_window_utils import (
        find_wechat_window,
        find_search_candidate_window,
        find_history_chat_window,
        count_chat_windows,
        count_wechat_windows,
        restore_wechat_windows,
        check_login_status,
        is_wechat_logged_in,
    )

    window = find_wechat_window()
    candidate = find_search_candidate_window()
    login_info = check_login_status()
"""

import ctypes
import ctypes.wintypes as wintypes
import os

# 设置 DPI 感知，让 GetWindowRect 等返回物理像素而非逻辑像素
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_AWARE
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# 类型声明（确保 64 位兼容性，参考 tools_read.py 的严谨做法）
user32.EnumWindows.argtypes = [wintypes.HANDLE, wintypes.LPARAM]
user32.EnumWindows.restype = wintypes.BOOL
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
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
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype = wintypes.BOOL
user32.SetWindowPos.argtypes = [
    wintypes.HWND, wintypes.HWND,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.UINT,
]
user32.SetWindowPos.restype = wintypes.BOOL
user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsIconic.restype = wintypes.BOOL

# 窗口最小尺寸阈值（过滤托盘图标等小窗口）
WECHAT_MIN_WIDTH = 500
WECHAT_MIN_HEIGHT = 400

# 微信窗口匹配关键词
_WECHAT_TITLE_KEYWORDS = ("微信", "WeChat", "Weixin")
_WECHAT_CLASS_KEYWORDS = ("WeChat", "Weixin", "WeChatMainWnd")

# 微信相关进程名（新版 Weixin.exe，旧版 WeChat.exe，小程序 WeChatAppEx.exe）
_WECHAT_PROCESS_NAMES = ("Weixin.exe", "WeChat.exe", "WeChatAppEx.exe")


def get_process_name_by_pid(pid: int) -> str | None:
    """通过 PID 查询进程名（用于排除 Snipaste 等 Qt 框架窗口的误判）。

    用 QueryFullProcessImageNameW（只需 PROCESS_QUERY_LIMITED_INFORMATION 权限，
    不需要 PROCESS_VM_READ，普通用户权限即可）。

    Args:
        pid: 进程 ID

    Returns:
        进程名（如 "Weixin.exe"）或 None（查询失败）
    """
    try:
        # PROCESS_QUERY_LIMITED_INFORMATION = 0x1000（普通用户权限即可）
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        hProcess = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not hProcess:
            return None
        try:
            buf = ctypes.create_unicode_buffer(260)
            size = wintypes.DWORD(260)
            if kernel32.QueryFullProcessImageNameW(hProcess, 0, buf, ctypes.byref(size)):
                return os.path.basename(buf.value)
            return None
        finally:
            kernel32.CloseHandle(hProcess)
    except Exception:
        return None


def _is_wechat_window(title: str, class_name: str, pid: int | None = None) -> bool:
    """判断窗口是否为微信相关窗口。

    改进：加上进程名验证，排除 Snipaste 等 Qt 框架窗口的误判。
    Snipaste 也用 Qt，class='Qt624QWindowIcon'，会被 "Qt + WindowIcon" 规则误判。

    保守策略：如果 PID 查询进程名失败，不回退到 Qt+WindowIcon 匹配（可能误判）。
    只有标题/类名明确含微信关键词，或进程名确认是微信，才算微信窗口。

    Args:
        title: 窗口标题
        class_name: 窗口类名
        pid: 进程 ID（可选，用于进程名验证）

    Returns:
        bool: 是否为微信窗口
    """
    # 标题或类名明确匹配微信关键词
    title_match = any(kw in title for kw in _WECHAT_TITLE_KEYWORDS)
    class_match = any(kw in class_name for kw in _WECHAT_CLASS_KEYWORDS)
    qt_match = "Qt" in class_name and "WindowIcon" in class_name

    if not (title_match or class_match or qt_match):
        return False

    # 如果有 PID，验证进程名（排除 Snipaste 等误判）
    if pid is not None:
        proc_name = get_process_name_by_pid(pid)
        if proc_name:
            # 只接受微信相关进程
            if any(proc_name == name for name in _WECHAT_PROCESS_NAMES):
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


def enumerate_visible_windows():
    """遍历所有可见窗口，返回窗口信息列表。

    Returns:
        list[dict]: 每个窗口包含 hwnd/title/class/left/top/right/bottom/width/height/pid
    """
    windows = []

    def enum_proc(hwnd, lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
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


def find_wechat_window(min_width=WECHAT_MIN_WIDTH, min_height=WECHAT_MIN_HEIGHT):
    """找到微信主窗口。

    匹配策略（按优先级）：
    1. 标题精确等于 "微信" + Qt/WeChatMainWndForPC 类（真正的主窗口）
    2. 标题精确等于 "微信"（其他类，如 Chrome_WidgetWin_0 是内嵌浏览器窗口）
    3. 标题包含 "微信"
    4. 类名匹配（WeChat/Weixin/WeChatMainWnd/Qt+WindowIcon）

    过滤掉小于 min_width x min_height 的小窗口（除非全部都是小窗口）。

    注意：新版微信（Weixin.exe）的主窗口类是 Qt51514QWindowIcon，
    但微信内嵌的浏览器窗口（如"搜一搜"等）类是 Chrome_WidgetWin_0，
    两者标题都是"微信"。优先选 Qt 类的，避免误操作浏览器窗口。

    Returns:
        dict 或 None: 包含 hwnd/title/class/left/top/width/height，未找到返回 None
    """
    all_windows = enumerate_visible_windows()

    # 筛选微信窗口候选（带进程名验证，排除 Snipaste 等误判）
    wechat_candidates = [w for w in all_windows
                         if _is_wechat_window(w["title"], w["class"], w.get("pid"))]

    if not wechat_candidates:
        return None

    # 过滤小窗口
    big_candidates = [
        w for w in wechat_candidates
        if w["width"] >= min_width and w["height"] >= min_height
    ]

    if not big_candidates:
        # 回退：选面积最大的
        big_candidates = sorted(
            wechat_candidates,
            key=lambda c: c["width"] * c["height"],
            reverse=True
        )

    # 优先级 1：标题精确为"微信" + Qt/WeChatMainWndForPC 类（真正的主窗口）
    # 新版 Weixin.exe 用 Qt51514QWindowIcon，旧版 WeChat.exe 用 WeChatMainWndForPC
    # Chrome_WidgetWin_0 是微信内嵌浏览器窗口（如"搜一搜"），不算主窗口
    main_window_classes = ("Qt", "WeChatMainWndForPC", "WeixinMainWndForPC")
    for c in big_candidates:
        if c["title"] == "微信" and any(cls in c["class"] for cls in main_window_classes):
            return c

    # 优先级 2：标题精确为"微信"（其他类，回退）
    for c in big_candidates:
        if c["title"] == "微信":
            return c

    # 优先级 3：标题含"微信"
    for c in big_candidates:
        if "微信" in c["title"]:
            return c

    # 优先级 4：面积最大
    return max(big_candidates, key=lambda c: c["width"] * c["height"])


def find_largest_wechat_window(min_width=WECHAT_MIN_WIDTH, min_height=WECHAT_MIN_HEIGHT):
    """找到最大的微信窗口（按面积排序）。

    兼容旧版 find_largest_wechat_window 接口，行为与 find_wechat_window 一致。

    Returns:
        dict 或 None
    """
    return find_wechat_window(min_width, min_height)


def find_search_candidate_window():
    """找到搜索候选框窗口（标题 'Weixin'，类名含 'ToolSaveBits'）。

    Returns:
        dict 或 None
    """
    all_windows = enumerate_visible_windows()
    for w in all_windows:
        if w["title"] == "Weixin" and "ToolSaveBits" in w["class"]:
            return w
    return None


def find_search_candidate_windows():
    """找到所有搜索候选框窗口。

    Returns:
        list[dict]
    """
    all_windows = enumerate_visible_windows()
    return [
        w for w in all_windows
        if w["title"] == "Weixin" and "ToolSaveBits" in w["class"]
    ]


def find_history_chat_window():
    """找到"搜索聊天记录"窗口（历史聊天界面）。

    Returns:
        dict 或 None
    """
    all_windows = enumerate_visible_windows()
    for w in all_windows:
        if w["title"] == "搜索聊天记录":
            return w
    return None


# 预期窗口白名单（其他微信相关窗口视为意外窗口，会被关闭）
# - title="微信"：微信主窗口
# - title="Weixin" + class 含 "ToolSaveBits"：搜索候选框
# - title="搜索聊天记录"：历史聊天界面（阶段二）
# - title=""  + class="MS_MASKED_WINDOW" 等：微信内部辅助小窗口（不算意外）
_EXPECTED_WECHAT_TITLES = ("微信", "Weixin", "搜索聊天记录")


def _is_expected_wechat_window(w: dict) -> bool:
    """判断窗口是否为预期的微信窗口（主窗口/搜索候选框/历史聊天窗口）。

    预期窗口白名单：
    - 主窗口：title="微信" + 类是 Qt/WeChatMainWndForPC（真正的主窗口）
    - 搜索候选框：title="Weixin" 或 class 含 ToolSaveBits
    - 历史聊天窗口：title="搜索聊天记录"

    非预期窗口（会被 close_unexpected_wechat_windows 关闭）：
    - title="微信" + class="Chrome_WidgetWin_0"（微信内嵌浏览器窗口，如"搜一搜"）
    - 其他标题的微信进程窗口

    Args:
        w: enumerate_visible_windows 返回的窗口 dict

    Returns:
        bool: 是否为预期窗口
    """
    title = w.get("title", "")
    cls = w.get("class", "")

    # 搜索候选框（title="Weixin"，class 含 ToolSaveBits）
    if "ToolSaveBits" in cls:
        return True

    # 历史聊天窗口（title="搜索聊天记录"）
    if title == "搜索聊天记录":
        return True

    # 主窗口：title="微信" + Qt/WeChatMainWndForPC 类
    # 排除 Chrome_WidgetWin_0（微信内嵌浏览器窗口，标题也是"微信"但不是主窗口）
    if title == "微信":
        main_window_classes = ("Qt", "WeChatMainWndForPC", "WeixinMainWndForPC")
        if any(c in cls for c in main_window_classes):
            return True
        # title="微信" 但类是 Chrome_WidgetWin_0 等 → 意外窗口
        return False

    # 其他 title 含 "Weixin" 的小窗口（如托盘图标等）算预期（不会被关闭）
    if title == "Weixin":
        return True

    return False


def close_unexpected_wechat_windows(min_width=WECHAT_MIN_WIDTH, min_height=WECHAT_MIN_HEIGHT):
    """关闭意外出现的微信相关窗口（如"搜索网络结果"窗口）。

    健壮性增强：用户反馈代码误点击"搜索网络结果"按钮会弹出新的窗口，
    后续操作都在错误窗口里进行。此函数在每次操作前清理这些意外窗口。

    关闭逻辑：
    - 遍历所有可见窗口
    - 过滤出微信相关窗口（_is_wechat_window）
    - 排除预期窗口（主窗口/搜索候选框/历史聊天窗口）
    - 排除小窗口（< min_width x min_height，避免误关托盘图标等）
    - 对剩余的意外窗口发送 WM_CLOSE

    Returns:
        tuple (closed_count: int, closed_windows: list[dict])
    """
    all_windows = enumerate_visible_windows()
    closed = []
    WM_CLOSE = 0x0010

    for w in all_windows:
        title = w.get("title", "")
        cls = w.get("class", "")
        pid = w.get("pid")

        # 必须是微信相关窗口
        if not _is_wechat_window(title, cls, pid):
            continue

        # 排除预期窗口
        if _is_expected_wechat_window(w):
            continue

        # 排除小窗口（托盘图标、辅助小窗口等）
        if w["width"] < min_width or w["height"] < min_height:
            continue

        # 意外窗口：关闭它
        hwnd = w["hwnd"]
        try:
            user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
            closed.append(w)
        except Exception:
            pass

    return len(closed), closed


def count_chat_windows(min_width=WECHAT_MIN_WIDTH, min_height=WECHAT_MIN_HEIGHT):
    """精确统计聊天相关窗口数（排除搜索候选框）。

    统计范围：
    - 主窗口（title='微信'）
    - 历史聊天界面（title='搜索聊天记录'）

    不包含：
    - 搜索候选框（title='Weixin'，class 含 'ToolSaveBits'）
    - 小窗口（< min_width x min_height）

    Returns:
        (count, windows)
    """
    all_windows = enumerate_visible_windows()
    chat_windows = []
    for w in all_windows:
        # 排除搜索候选框
        if "ToolSaveBits" in w["class"]:
            continue
        # 只统计标题为"微信"或"搜索聊天记录"的窗口
        if w["title"] not in ("微信", "搜索聊天记录"):
            continue
        # 排除小窗口
        if w["width"] < min_width or w["height"] < min_height:
            continue
        chat_windows.append(w)
    return len(chat_windows), chat_windows


def count_wechat_windows(min_width=WECHAT_MIN_WIDTH, min_height=WECHAT_MIN_HEIGHT):
    """统计微信相关窗口数量（排除托盘图标等小窗口）。

    匹配规则：标题或类名匹配微信关键词（带进程名验证）

    Returns:
        (count, windows)
    """
    all_windows = enumerate_visible_windows()
    wechat_windows = []
    for w in all_windows:
        if not _is_wechat_window(w["title"], w["class"], w.get("pid")):
            continue
        if w["width"] < min_width or w["height"] < min_height:
            continue
        wechat_windows.append(w)
    return len(wechat_windows), wechat_windows


# ========== 登录状态检测 ==========

# numpy/cv2/PIL 用于 icon 模板匹配（可选依赖）
try:
    import numpy as np
    import cv2
    from PIL import Image
    _HAS_CV = True
except ImportError:
    _HAS_CV = False


def _load_wx_icons():
    """加载微信图标模板（用于模板匹配）。

    从 engine/wechat_sender/wx_icon/1.ico ~ 6.ico 加载图标。

    Returns:
        list[np.ndarray]: 图标模板列表（BGR 格式），加载失败返回空列表
    """
    if not _HAS_CV:
        return []
    icon_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "wx_icon"
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
        except Exception:
            pass
    return icons


def find_wechat_icon_by_template(tray_img, icons, tray_left, tray_top, threshold=0.6):
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


def check_login_status():
    """检测微信是否已登录。

    综合判定（任意一个满足即视为已登录）：
    1. 托盘有微信图标（最可靠，用 icon 模板匹配）
    2. 主窗口尺寸 > 500 宽（未登录窗口约 350x475）
    3. 同 PID 下存在隐藏子窗口 'Weixin'（已登录才有）

    Returns:
        dict: {
            "logged_in": bool,           # 是否已登录
            "tray_icon_found": bool,     # 托盘是否有微信图标
            "tray_method": str|None,     # icon_template / hsv_fallback
            "tray_confidence": float|None,
            "main_window_size": tuple|None,  # (width, height)
            "has_hidden_subwindow": bool,    # 是否有隐藏子窗口 'Weixin'
            "process_running": bool,
            "main_pid": int|None,
        }
    """
    result = {
        "logged_in": False,
        "tray_icon_found": False,
        "tray_method": None,
        "tray_confidence": None,
        "main_window_size": None,
        "has_hidden_subwindow": False,
        "process_running": False,
        "main_pid": None,
    }

    # 1. 检查进程
    try:
        import subprocess
        proc = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True, timeout=5, encoding="gbk", errors="ignore"
        )
        lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
        wechat_pids = []
        for line in lines:
            for name in _WECHAT_PROCESS_NAMES:
                if name in line:
                    parts = line.split(",")
                    if len(parts) >= 2:
                        try:
                            wechat_pids.append(int(parts[1].strip('"')))
                        except ValueError:
                            pass
                    break
        result["process_running"] = bool(wechat_pids)
        # 主进程优先 Weixin.exe / WeChat.exe
        main_pids = [pid for pid in wechat_pids
                     if get_process_name_by_pid(pid) in ("Weixin.exe", "WeChat.exe")]
        result["main_pid"] = main_pids[0] if main_pids else (wechat_pids[0] if wechat_pids else None)
    except Exception:
        pass

    # 2. 检查主窗口尺寸
    all_windows = enumerate_visible_windows()
    main_windows = [w for w in all_windows
                    if w["title"] == "微信"
                    and _is_wechat_window(w["title"], w["class"], w.get("pid"))]
    if main_windows:
        main_win = max(main_windows, key=lambda w: w["width"] * w["height"])
        result["main_window_size"] = (main_win["width"], main_win["height"])

    # 3. 检查隐藏子窗口 'Weixin'（已登录才有，需枚举所有窗口包括不可见的）
    if result["main_pid"]:
        try:
            # 枚举所有窗口（包括不可见的）
            all_windows_incl_hidden = []

            def _enum_all(hwnd, lparam):
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
                pid = wintypes.DWORD(0)
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                all_windows_incl_hidden.append({
                    "hwnd": hwnd,
                    "title": title,
                    "class": cls_name,
                    "pid": pid.value,
                    "is_visible": bool(user32.IsWindowVisible(hwnd)),
                })
                return True

            callback = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)(_enum_all)
            user32.EnumWindows(callback, 0)

            hidden_sub = [w for w in all_windows_incl_hidden
                          if w["title"] == "Weixin"
                          and not w["is_visible"]
                          and w["pid"] == result["main_pid"]]
            result["has_hidden_subwindow"] = bool(hidden_sub)
        except Exception:
            pass

    # 4. 检查托盘图标（用 icon 模板匹配）
    try:
        from open_wechat_window import (
            _find_tray_window, _capture_region, _find_wechat_icon_in_tray, TRAY_RIGHT_RATIO
        )
        tray = _find_tray_window()
        if tray:
            tray_left = int(tray["right"] - tray["width"] * TRAY_RIGHT_RATIO)
            tray_top = tray["top"]
            tray_width = int(tray["width"] * TRAY_RIGHT_RATIO)
            tray_height = tray["height"]
            tray_img = _capture_region(tray_left, tray_top, tray_width, tray_height)
            if tray_img is not None:
                # 优先 icon 模板匹配
                if _HAS_CV:
                    icons = _load_wx_icons()
                    if icons:
                        match = find_wechat_icon_by_template(
                            tray_img, icons, tray_left, tray_top
                        )
                        if match:
                            result["tray_icon_found"] = True
                            result["tray_method"] = "icon_template"
                            result["tray_confidence"] = float(match[2])
                # fallback HSV
                if not result["tray_icon_found"]:
                    hsv_pos = _find_wechat_icon_in_tray(tray_img, tray_left, tray_top)
                    if hsv_pos:
                        result["tray_icon_found"] = True
                        result["tray_method"] = "hsv_fallback"
    except Exception:
        pass

    # 5. 综合判定
    is_logged_in = (
        result["tray_icon_found"]
        or (result["main_window_size"] is not None and result["main_window_size"][0] > 500)
        or result["has_hidden_subwindow"]
    )
    result["logged_in"] = bool(is_logged_in)
    return result


def is_wechat_logged_in() -> bool:
    """简化接口：微信是否已登录。"""
    return check_login_status()["logged_in"]


def restore_wechat_windows():
    """恢复所有微信窗口（ShowWindow RESTORE + SHOW）。

    用于微信最小化到托盘时尝试恢复窗口可见性。

    Returns:
        int: 尝试恢复的窗口数
    """
    SW_RESTORE = 9
    SW_SHOW = 5
    all_windows = enumerate_visible_windows()
    count = 0
    for w in all_windows:
        if "微信" in w["title"]:
            user32.ShowWindow(w["hwnd"], SW_RESTORE)
            user32.ShowWindow(w["hwnd"], SW_SHOW)
            count += 1
    return count


# 确保微信窗口宽度的最小阈值（用户反馈：窗口化 658px→两栏，1186px→三栏）
# 1000 介于两者之间，是恢复三栏的安全阈值
WECHAT_THREE_COLUMN_MIN_WIDTH = 1000


def ensure_wechat_window_width(min_width=WECHAT_THREE_COLUMN_MIN_WIDTH, hwnd=None):
    """确保微信窗口宽度足够大，避免窗口化时只有两栏。

    用户反馈：微信窗口横向宽度太小时只显示两栏（导航+聊天，无会话列表），
    导致 dynamic_detector 误判三栏、阶段一搜索栏定位失败。
    通过 SetWindowPos 增大窗口宽度恢复三栏布局（等同于用户拖动右边界向右放大）。

    经验数据：
    - 窗口化 658x869 → 两栏（导航+聊天，无会话列表）
    - 窗口化 1186x946 → 三栏（nav_right=42, session_right=509）
    - 阈值 min_width=1000 介于两者之间

    Args:
        min_width: 最小宽度阈值（默认 1000）
        hwnd: 微信窗口句柄，None 则自动查找

    Returns:
        dict: {
            "success": bool,       # 最终窗口宽度是否 >= min_width
            "hwnd": int,           # 窗口句柄
            "old_width": int,      # 调整前宽度
            "new_width": int,      # 调整后宽度
            "was_resized": bool,   # 是否触发了 SetWindowPos 调整
            "reason": str,         # 说明文字
        }
    """
    import time

    result = {
        "success": False, "hwnd": 0,
        "old_width": 0, "new_width": 0,
        "was_resized": False, "reason": "",
    }

    if hwnd is None:
        win = find_wechat_window()
        if not win:
            result["reason"] = "未找到微信窗口"
            return result
        hwnd = win["hwnd"]

    result["hwnd"] = hwnd

    # 获取当前窗口位置和尺寸
    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        result["reason"] = "GetWindowRect 失败"
        return result

    cur_left = rect.left
    cur_top = rect.top
    cur_width = rect.right - rect.left
    cur_height = rect.bottom - rect.top
    result["old_width"] = cur_width
    result["new_width"] = cur_width

    # 最小化先恢复（IsIconic 判断是否最小化）
    if user32.IsIconic(hwnd):
        SW_RESTORE = 9
        user32.ShowWindow(hwnd, SW_RESTORE)
        time.sleep(0.3)
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            result["reason"] = "恢复最小化后 GetWindowRect 失败"
            return result
        cur_left = rect.left
        cur_top = rect.top
        cur_width = rect.right - rect.left
        cur_height = rect.bottom - rect.top
        result["old_width"] = cur_width
        result["new_width"] = cur_width

    if cur_width >= min_width:
        result["success"] = True
        result["reason"] = f"宽度 {cur_width}px 已 >= {min_width}px，无需调整"
        return result

    # 宽度不够，用 SetWindowPos 增大（保持 left/top/height 不变，只增大宽度）
    # SWP_NOZORDER (0x0004): 保持 Z 顺序不变
    # SWP_NOACTIVATE (0x0010): 不激活窗口（避免抢占前台）
    SWP_NOZORDER = 0x0004
    SWP_NOACTIVATE = 0x0010
    ok = user32.SetWindowPos(
        hwnd, None,
        cur_left, cur_top, min_width, cur_height,
        SWP_NOZORDER | SWP_NOACTIVATE,
    )
    if not ok:
        result["reason"] = f"SetWindowPos 失败 (cur={cur_width}, target={min_width})"
        return result

    result["was_resized"] = True
    time.sleep(0.3)  # 等待窗口重绘

    # 验证最终尺寸
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        result["reason"] = "SetWindowPos 后 GetWindowRect 失败"
        return result

    new_width = rect.right - rect.left
    result["new_width"] = new_width

    if new_width >= min_width:
        result["success"] = True
        result["reason"] = f"已从 {cur_width}px 调整到 {new_width}px"
    else:
        result["reason"] = f"调整后宽度 {new_width}px 仍 < {min_width}px（微信可能限制最小宽度）"

    return result
