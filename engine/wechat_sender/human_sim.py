"""
人类行为模拟模块：防封号。

提供两类能力：
1. 文字输入：把消息切成若干段，以随机间隔逐段输入，模拟人类打字节奏。
2. 鼠标点击：在识别到的目标区域内随机抖动点击位置，点击间隔随机化。

设计原则：
- 抖动半径小（默认 3px），不会脱离识别区域。
- 间隔随机但合理（0.05~0.8s），不会过度拖慢流程。
- 段长随机（3~15 字符），避免机械化的固定分段。
- 兼容原 physical_click / input_text_via_clipboard 的调用方，可直接替换。

用法：
    from human_sim import human_physical_click, human_input_text
    human_physical_click(x, y, jitter_radius=3)
    human_input_text(hwnd, "你好，今天天气不错")
"""
import os
import sys
import time
import random
import math
import ctypes
import ctypes.wintypes as wintypes

# 设置 DPI 感知（必须在其他导入前）
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from logger import get_logger  # noqa: E402
logger = get_logger(__name__)

user32 = ctypes.windll.user32

# 鼠标事件常量
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004

# 键盘事件常量
KEYEVENTF_KEYUP = 0x0002
VK_CONTROL = 0x11
VK_A = 0x41
VK_V = 0x56
VK_END = 0x23  # End 键，用于把光标移到末尾


# ── 防封号参数（可在 config.py 中覆盖）─────────────────────────
DEFAULT_JITTER_RADIUS = 3          # 默认点击位置抖动半径（像素）
DEFAULT_CLICK_DOWN_MIN = 0.04      # 按下到抬起的最小间隔（秒）
DEFAULT_CLICK_DOWN_MAX = 0.12      # 按下到抬起的最大间隔（秒）
DEFAULT_PRE_CLICK_MIN = 0.05       # 移动到点击前的最小停顿（秒）
DEFAULT_PRE_CLICK_MAX = 0.15       # 移动到点击前的最大停顿（秒）
DEFAULT_POST_CLICK_MIN = 0.05      # 点击后最小停顿（秒）
DEFAULT_POST_CLICK_MAX = 0.15      # 点击后最大停顿（秒）

# 输入分段参数
SHORT_MSG_THRESHOLD = 20           # 短消息阈值（字符）
MID_MSG_THRESHOLD = 100            # 中等消息阈值（字符）
SHORT_SEG_MIN, SHORT_SEG_MAX = 3, 8    # 中等消息的分段长度范围
LONG_SEG_MIN, LONG_SEG_MAX = 8, 15     # 长消息的分段长度范围

# 段间随机间隔（秒）
SEG_GAP_MIN, SEG_GAP_MAX = 0.2, 0.8
# 段内粘贴后等待（秒）
PASTE_WAIT_MIN, PASTE_WAIT_MAX = 0.2, 0.4
# 剪贴板写入后等待（秒）
CLIPBOARD_WAIT_MIN, CLIPBOARD_WAIT_MAX = 0.15, 0.3
# 前台切换后等待（秒）
FOREGROUND_WAIT_MIN, FOREGROUND_WAIT_MAX = 0.2, 0.4


def _human_sleep(min_s, max_s):
    """随机睡眠 [min_s, max_s] 秒。"""
    time.sleep(random.uniform(min_s, max_s))


def _jitter_point(x, y, radius=DEFAULT_JITTER_RADIUS):
    """在以 (x, y) 为中心、半径 radius 的圆内随机选一个整数点。

    radius=0 时返回原点（用于禁用抖动的场景）。
    """
    if radius <= 0:
        return int(x), int(y)
    angle = random.uniform(0, 2 * math.pi)
    r = random.uniform(0, radius)
    return int(round(x + r * math.cos(angle))), int(round(y + r * math.sin(angle)))


def _press_key_combo(hold_vk, press_vk):
    """模拟 Ctrl+X 之类的组合键：按住 hold_vk，按一下 press_vk，再松开 hold_vk。"""
    user32.keybd_event(hold_vk, 0, 0, 0)                  # Ctrl down
    _human_sleep(0.04, 0.08)
    user32.keybd_event(press_vk, 0, 0, 0)                 # X down
    _human_sleep(0.03, 0.07)
    user32.keybd_event(press_vk, 0, KEYEVENTF_KEYUP, 0)   # X up
    _human_sleep(0.03, 0.07)
    user32.keybd_event(hold_vk, 0, KEYEVENTF_KEYUP, 0)    # Ctrl up


def _set_clipboard_text(text):
    """用 ctypes 直接设置剪贴板文本（避免 PowerShell 注入风险）。

    64 位系统必须设置函数原型，否则句柄被截断为 32 位导致失败。
    """
    CF_UNICODETEXT = 13
    GMEM_MOVEABLE = 0x0002

    kernel32 = ctypes.windll.kernel32

    # 关键：64位系统必须设置函数原型，否则句柄被截断为32位导致失败
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.SetClipboardData.restype = wintypes.HANDLE
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]

    data = text + '\0'
    data_bytes = data.encode('utf-16-le')

    if not user32.OpenClipboard(None):
        return False
    try:
        user32.EmptyClipboard()
        h_global = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data_bytes))
        if not h_global:
            return False
        ptr = kernel32.GlobalLock(h_global)
        if not ptr:
            return False
        ctypes.memmove(ptr, data_bytes, len(data_bytes))
        kernel32.GlobalUnlock(h_global)
        result = user32.SetClipboardData(CF_UNICODETEXT, h_global)
        return bool(result)
    finally:
        user32.CloseClipboard()


def human_physical_click(screen_x, screen_y, jitter_radius=DEFAULT_JITTER_RADIUS):
    """带随机抖动和随机间隔的物理点击。

    相比 physical_click：
    1. 点击位置在 (screen_x, screen_y) 附近半径 jitter_radius 内随机抖动。
    2. SetCursorPos → 按下 → 抬起 三个阶段都有随机间隔。
    3. 间隔范围通过模块级常量控制，避免机械化节奏。

    Args:
        screen_x, screen_y: 目标屏幕坐标（识别到的中心点）
        jitter_radius: 抖动半径（像素），0 表示不抖动

    Returns:
        tuple (actual_x, actual_y): 实际点击的屏幕坐标
    """
    actual_x, actual_y = _jitter_point(screen_x, screen_y, jitter_radius)
    user32.SetCursorPos(actual_x, actual_y)
    _human_sleep(DEFAULT_PRE_CLICK_MIN, DEFAULT_PRE_CLICK_MAX)
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    _human_sleep(DEFAULT_CLICK_DOWN_MIN, DEFAULT_CLICK_DOWN_MAX)
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    _human_sleep(DEFAULT_POST_CLICK_MIN, DEFAULT_POST_CLICK_MAX)
    logger.info(f"   [人类模拟] 点击 ({actual_x}, {actual_y})  jitter={jitter_radius}")
    return actual_x, actual_y


def human_physical_double_click(screen_x, screen_y, jitter_radius=DEFAULT_JITTER_RADIUS):
    """带抖动和随机间隔的物理双击。"""
    actual_x, actual_y = _jitter_point(screen_x, screen_y, jitter_radius)
    user32.SetCursorPos(actual_x, actual_y)
    _human_sleep(DEFAULT_PRE_CLICK_MIN, DEFAULT_PRE_CLICK_MAX)
    # 第一次点击
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    _human_sleep(DEFAULT_CLICK_DOWN_MIN, DEFAULT_CLICK_DOWN_MAX)
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    _human_sleep(0.08, 0.16)  # 双击间隔
    # 第二次点击
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    _human_sleep(DEFAULT_CLICK_DOWN_MIN, DEFAULT_CLICK_DOWN_MAX)
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    _human_sleep(DEFAULT_POST_CLICK_MIN, DEFAULT_POST_CLICK_MAX)
    logger.info(f"   [人类模拟] 双击 ({actual_x}, {actual_y})  jitter={jitter_radius}")
    return actual_x, actual_y


def _split_text(text):
    """把文本切成若干段。

    分段策略：
    - 短消息（≤ SHORT_MSG_THRESHOLD）：不分段
    - 中等消息（≤ MID_MSG_THRESHOLD）：3~8 字符一段
    - 长消息（> MID_MSG_THRESHOLD）：8~15 字符一段

    段长在范围内随机，避免机械化分段。
    """
    if len(text) <= SHORT_MSG_THRESHOLD:
        return [text]
    if len(text) <= MID_MSG_THRESHOLD:
        seg_len = random.randint(SHORT_SEG_MIN, SHORT_SEG_MAX)
    else:
        seg_len = random.randint(LONG_SEG_MIN, LONG_SEG_MAX)
    return [text[i:i + seg_len] for i in range(0, len(text), seg_len)]


def human_input_text(hwnd, text):
    """分段随机间隔输入文字，模拟人类打字。

    相比 input_text_via_clipboard：
    1. 把消息切成若干段（段长随机）。
    2. 第一段用 Ctrl+A 全选 + Ctrl+V 粘贴（替换已有内容）。
    3. 后续段直接 Ctrl+V 粘贴（追加到光标位置）。
    4. 段间随机间隔 0.2~0.8 秒，模拟人类打字停顿。
    5. 每段内的按键操作也有随机间隔。

    Args:
        hwnd: 目标窗口句柄（需在前台才能接收 keybd_event）
        text: 要输入的文本

    Returns:
        bool: 是否成功
    """
    segments = _split_text(text)
    logger.info(f"   [人类模拟] 输入 {text!r}（{len(segments)} 段，总 {len(text)} 字符）")

    # 写入第一段到剪贴板
    if not _set_clipboard_text(segments[0]):
        logger.warning(f"   ⚠️ 剪贴板设置失败，文本: {segments[0]}")
        return False
    _human_sleep(CLIPBOARD_WAIT_MIN, CLIPBOARD_WAIT_MAX)

    # 将微信设为前台
    user32.SetForegroundWindow(hwnd)
    _human_sleep(FOREGROUND_WAIT_MIN, FOREGROUND_WAIT_MAX)

    # 第一段：Ctrl+A 全选 + Ctrl+V 替换
    _press_key_combo(VK_CONTROL, VK_A)
    _human_sleep(0.08, 0.18)
    _press_key_combo(VK_CONTROL, VK_V)
    _human_sleep(PASTE_WAIT_MIN, PASTE_WAIT_MAX)

    # 后续段：Ctrl+V 追加（光标应在上次粘贴的末尾）
    for idx, seg in enumerate(segments[1:], start=2):
        _human_sleep(SEG_GAP_MIN, SEG_GAP_MAX)  # 段间停顿，模拟人类打字
        if not _set_clipboard_text(seg):
            logger.warning(f"   ⚠️ 第 {idx} 段剪贴板设置失败")
            return False
        _human_sleep(CLIPBOARD_WAIT_MIN, CLIPBOARD_WAIT_MAX)
        _press_key_combo(VK_CONTROL, VK_V)
        _human_sleep(PASTE_WAIT_MIN, PASTE_WAIT_MAX)

    logger.info(f"   [人类模拟] 输入完成: {text}")
    return True


def random_operation_gap(min_s=0.3, max_s=0.8):
    """在两个独立操作之间加入随机间隔（如搜索→点击头像之间）。

    用于在阶段切换时插入更长的随机停顿，模拟人类思考/反应时间。
    """
    _human_sleep(min_s, max_s)
