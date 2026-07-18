"""微信窗口枚举公共模块。

统一所有 EnumWindows 实现，提供窗口查找、统计、恢复功能。
消除 6 个文件中 7 处重复的 EnumWindows 代码。

使用方式:
    from wechat_window_utils import (
        find_wechat_window,
        find_search_candidate_window,
        find_history_chat_window,
        count_chat_windows,
        count_wechat_windows,
        restore_wechat_windows,
    )

    window = find_wechat_window()
    candidate = find_search_candidate_window()
"""

import ctypes
import ctypes.wintypes as wintypes

# 设置 DPI 感知，让 GetWindowRect 等返回物理像素而非逻辑像素
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_AWARE
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

user32 = ctypes.windll.user32

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
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype = wintypes.BOOL

# 窗口最小尺寸阈值（过滤托盘图标等小窗口）
WECHAT_MIN_WIDTH = 500
WECHAT_MIN_HEIGHT = 400

# 微信窗口匹配关键词
_WECHAT_TITLE_KEYWORDS = ("微信", "WeChat", "Weixin")
_WECHAT_CLASS_KEYWORDS = ("WeChat", "Weixin", "WeChatMainWnd")


def _is_wechat_window(title: str, class_name: str) -> bool:
    """判断窗口是否为微信相关窗口。"""
    if any(kw in title for kw in _WECHAT_TITLE_KEYWORDS):
        return True
    if any(kw in class_name for kw in _WECHAT_CLASS_KEYWORDS):
        return True
    # Qt 框架特征（微信使用 Qt）
    if "Qt" in class_name and "WindowIcon" in class_name:
        return True
    return False


def enumerate_visible_windows():
    """遍历所有可见窗口，返回窗口信息列表。

    Returns:
        list[dict]: 每个窗口包含 hwnd/title/class/left/top/right/bottom/width/height
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
        })
        return True

    callback = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)(enum_proc)
    user32.EnumWindows(callback, 0)
    return windows


def find_wechat_window(min_width=WECHAT_MIN_WIDTH, min_height=WECHAT_MIN_HEIGHT):
    """找到微信主窗口。

    匹配策略（按优先级）：
    1. 标题精确等于 "微信"
    2. 标题包含 "微信"
    3. 类名匹配（WeChat/Weixin/WeChatMainWnd/Qt+WindowIcon）

    过滤掉小于 min_width x min_height 的小窗口（除非全部都是小窗口）。

    Returns:
        dict 或 None: 包含 hwnd/title/class/left/top/width/height，未找到返回 None
    """
    all_windows = enumerate_visible_windows()

    # 筛选微信窗口候选
    wechat_candidates = [w for w in all_windows if _is_wechat_window(w["title"], w["class"])]

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

    # 优先级：标题精确为"微信" > 标题含"微信" > 其他（按面积最大）
    for c in big_candidates:
        if c["title"] == "微信":
            return c
    for c in big_candidates:
        if "微信" in c["title"]:
            return c
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

    匹配规则：标题或类名匹配微信关键词

    Returns:
        (count, windows)
    """
    all_windows = enumerate_visible_windows()
    wechat_windows = []
    for w in all_windows:
        if not _is_wechat_window(w["title"], w["class"]):
            continue
        if w["width"] < min_width or w["height"] < min_height:
            continue
        wechat_windows.append(w)
    return len(wechat_windows), wechat_windows


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
