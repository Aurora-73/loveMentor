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
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_SCANCODE = 0x0008
INPUT_KEYBOARD = 1
VK_CONTROL = 0x11
VK_MENU = 0x12  # Alt 键
VK_A = 0x41
VK_V = 0x56
VK_F = 0x46
VK_END = 0x23  # End 键，用于把光标移到末尾
VK_ESCAPE = 0x1B

# WM_IME_CHAR 消息（用于绕过剪贴板模拟 IME 输入中文）
WM_IME_CHAR = 0x0286


# ── SendInput 结构体定义（64 位兼容）─────────────────────────────
class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),  # ULONG_PTR，用 c_void_p 避免 64 位指针截断
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [("ki", _KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("ii",)
    _fields_ = [
        ("type", wintypes.DWORD),
        ("ii", _INPUT_UNION),
    ]


# SendInput 函数原型（64 位兼容）
user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT
user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
user32.MapVirtualKeyW.restype = wintypes.UINT
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostMessageW.restype = wintypes.BOOL
# keybd_event 函数原型（64 位兼容，作为 SendInput 的 fallback）
user32.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_void_p]
user32.keybd_event.restype = None


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

# 逐字输入参数（短消息用 SendInput 逐字输入）
CHAR_GAP_MIN, CHAR_GAP_MAX = 0.05, 0.15   # 每个字符的输入间隔（秒）
# 中文 IME 输入参数（用 WM_IME_CHAR 绕过剪贴板）
IME_CHAR_GAP_MIN, IME_CHAR_GAP_MAX = 0.08, 0.25  # 中文字符间隔（更长，模拟 IME 候选词选择）

# 是否启用 WM_IME_CHAR 输入中文（默认 False，需测试有效后再开启）
# 测试方法：运行 scripts/test_ime_char.py 验证微信编辑框是否响应 WM_IME_CHAR
USE_IME_CHAR_FOR_CHINESE = False


def _human_sleep(min_s, max_s):
    """随机睡眠 [min_s, max_s] 秒。"""
    time.sleep(random.uniform(min_s, max_s))


# 偶发长停顿参数（模拟人类走神/思考）
OCCASIONAL_PAUSE_PROBABILITY = 0.05  # 5% 概率触发长停顿
OCCASIONAL_PAUSE_MIN = 1.0           # 长停顿最小 1 秒
OCCASIONAL_PAUSE_MAX = 3.0           # 长停顿最大 3 秒


def _human_sleep_with_pause(min_s, max_s, allow_pause=True):
    """随机睡眠，偶发引入长停顿模拟人类走神。

    在常规随机间隔基础上，有 OCCASIONAL_PAUSE_PROBABILITY 概率
    触发长停顿（1-3 秒），模拟人类操作中的走神/思考。

    用于阶段切换、段间停顿等关键位置，避免机械化节奏。

    Args:
        min_s, max_s: 常规随机间隔范围（秒）
        allow_pause: 是否允许触发长停顿（False=纯随机间隔）
    """
    if allow_pause and random.random() < OCCASIONAL_PAUSE_PROBABILITY:
        # 偶发长停顿
        pause = random.uniform(OCCASIONAL_PAUSE_MIN, OCCASIONAL_PAUSE_MAX)
        logger.info(f"   [人类模拟] 偶发停顿 {pause:.2f}s（模拟走神）")
        time.sleep(pause)
    else:
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


def _send_input_keyboard(wVk, wScan, dwFlags):
    """用 SendInput 发送一个键盘事件，失败时回退到 keybd_event。

    优先使用 SendInput（更底层，带扫描码），如果失败则回退到 keybd_event。
    SendInput 在某些环境下可能因结构体对齐或权限问题失败，
    keybd_event 内部也是调用 SendInput，但封装更稳定。

    Args:
        wVk: 虚拟键码（用 KEYEVENTF_UNICODE 时传 0）
        wScan: 扫描码或 Unicode 字符码
        dwFlags: 标志位（KEYEVENTF_SCANCODE / KEYEVENTF_UNICODE / KEYEVENTF_KEYUP）

    Returns:
        bool: 是否成功发送
    """
    # 尝试 SendInput
    try:
        inp = INPUT()
        inp.type = INPUT_KEYBOARD
        inp.ii.ki.wVk = wVk
        inp.ii.ki.wScan = wScan
        inp.ii.ki.dwFlags = dwFlags
        inp.ii.ki.time = 0
        inp.ii.ki.dwExtraInfo = None  # NULL 指针（c_void_p）
        result = user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
        if result > 0:
            return True
        # SendInput 失败，回退到 keybd_event
        logger.debug(f"   SendInput 返回 {result}，回退到 keybd_event (wVk={wVk}, wScan={wScan})")
    except Exception as e:
        logger.debug(f"   SendInput 异常: {e}，回退到 keybd_event")

    # 回退：keybd_event（带扫描码）
    # keybd_event 签名：keybd_event(bVk, bScan, dwFlags, dwExtraInfo)
    # bScan 是 BYTE 类型，但对于大多数键扫描码 < 128，足够
    # 对于 Unicode 字符（KEYEVENTF_UNICODE），wScan 是字符码，可能 > 127
    # keybd_event 的 bScan 是 BYTE，会截断，但 Unicode 输入主要靠 wScan
    user32.keybd_event(wVk, wScan & 0xFF, dwFlags, 0)
    return True


def _send_key_press(vk, with_scan=True):
    """用 SendInput 按下并抬起一个键（带扫描码）。

    Args:
        vk: 虚拟键码
        with_scan: 是否带扫描码（True=扫描码，False=纯虚拟键码）
    """
    flags_down = KEYEVENTF_SCANCODE if with_scan else 0
    flags_up = flags_down | KEYEVENTF_KEYUP
    scan = user32.MapVirtualKeyW(vk, 0) if with_scan else 0  # MAPVK_VK_TO_VSC
    _send_input_keyboard(0, scan, flags_down)
    _human_sleep(0.03, 0.07)
    _send_input_keyboard(0, scan, flags_up)


def _send_key_combo_si(hold_vk, press_vk):
    """用 SendInput 模拟 Ctrl+X 组合键（带扫描码，更接近真实硬件事件）。

    替代 _press_key_combo，使用 SendInput 而非 keybd_event。
    """
    scan_hold = user32.MapVirtualKeyW(hold_vk, 0)  # MAPVK_VK_TO_VSC
    scan_press = user32.MapVirtualKeyW(press_vk, 0)

    # Ctrl down
    _send_input_keyboard(0, scan_hold, KEYEVENTF_SCANCODE)
    _human_sleep(0.04, 0.08)
    # X down
    _send_input_keyboard(0, scan_press, KEYEVENTF_SCANCODE)
    _human_sleep(0.03, 0.07)
    # X up
    _send_input_keyboard(0, scan_press, KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP)
    _human_sleep(0.03, 0.07)
    # Ctrl up
    _send_input_keyboard(0, scan_hold, KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP)


def _type_char_unicode(char):
    """用 SendInput + KEYEVENTF_UNICODE 逐字输入一个字符。

    适用于英文/数字/符号（ASCII 字符），绕过键盘布局和 IME。
    发送的是 WM_CHAR 消息，微信编辑框响应良好。

    Args:
        char: 单个字符（ASCII）
    """
    code = ord(char)
    # 按下（KEYEVENTF_UNICODE）
    _send_input_keyboard(0, code, KEYEVENTF_UNICODE)
    _human_sleep(0.02, 0.05)
    # 抬起
    _send_input_keyboard(0, code, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)


def _type_ime_char(hwnd, char):
    """用 WM_IME_CHAR 消息输入一个中文字符（绕过剪贴板）。

    通过 PostMessageW 直接向目标窗口发送 WM_IME_CHAR 消息，
    模拟 IME 输入法输入中文字符，不经过剪贴板。

    ⚠️ 注意：此方法依赖于微信编辑框响应 WM_IME_CHAR 消息。
    测试方法：运行 scripts/test_ime_char.py 验证。
    如果不响应，请保持 USE_IME_CHAR_FOR_CHINESE = False，使用剪贴板粘贴。

    Args:
        hwnd: 目标窗口句柄
        char: 单个中文字符

    Returns:
        bool: PostMessageW 是否成功发送（不代表窗口已处理）
    """
    code = ord(char)
    # PostMessageW 是异步的，不阻塞
    # lParam 高字=扫描码（0），低字=重复次数（1）
    lparam = 1
    result = user32.PostMessageW(hwnd, WM_IME_CHAR, code, lparam)
    return bool(result)


def _press_key_combo(hold_vk, press_vk):
    """模拟 Ctrl+X 之类的组合键：按住 hold_vk，按一下 press_vk，再松开 hold_vk。

    已升级为使用 SendInput（带扫描码），替代旧的 keybd_event。
    保留原函数名以兼容调用方。
    """
    _send_key_combo_si(hold_vk, press_vk)


def _press_single_key(vk):
    """按下并抬起单个键（如 Esc），用 SendInput 带扫描码。

    替代 keybd_event 单键操作，统一输入方式。
    """
    _send_key_press(vk, with_scan=True)


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


def _is_ascii_char(ch):
    """判断字符是否为 ASCII（英文/数字/常见符号）。

    ASCII 字符用 SendInput + KEYEVENTF_UNICODE 逐字输入，
    非 ASCII（如中文）用 WM_IME_CHAR 或剪贴板粘贴。
    """
    return ord(ch) < 128


def _has_chinese(text):
    """判断文本是否包含非 ASCII 字符（如中文）。"""
    return any(not _is_ascii_char(ch) for ch in text)


def _type_short_message(hwnd, text):
    """短消息（≤ SHORT_MSG_THRESHOLD）逐字输入，绕过剪贴板。

    输入策略：
    1. 纯 ASCII：逐字 SendInput + KEYEVENTF_UNICODE（绕过剪贴板和 IME）
    2. 含中文 + USE_IME_CHAR_FOR_CHINESE=True：
       - ASCII 部分用 SendInput Unicode
       - 中文部分用 WM_IME_CHAR（绕过剪贴板）
    3. 含中文 + USE_IME_CHAR_FOR_CHINESE=False：
       - fallback 到剪贴板粘贴（Ctrl+A + Ctrl+V）

    Args:
        hwnd: 目标窗口句柄
        text: 短消息文本（≤ SHORT_MSG_THRESHOLD 字符）

    Returns:
        bool: 是否成功
    """
    has_chinese = _has_chinese(text)

    # 策略3：含中文且未启用 IME_CHAR，fallback 到剪贴板粘贴
    if has_chinese and not USE_IME_CHAR_FOR_CHINESE:
        logger.info(f"   [人类模拟] 短消息含中文(IME_CHAR 未启用)，走剪贴板路径: {text!r}")
        return _type_via_clipboard(hwnd, text)

    # 策略1/2：纯 ASCII 或启用了 IME_CHAR
    # 先 Ctrl+A 清空已有内容
    user32.SetForegroundWindow(hwnd)
    _human_sleep(FOREGROUND_WAIT_MIN, FOREGROUND_WAIT_MAX)
    _press_key_combo(VK_CONTROL, VK_A)
    _human_sleep(0.08, 0.18)

    if has_chinese:
        logger.info(f"   [人类模拟] 短消息逐字输入(IME_CHAR): {text!r}")
    else:
        logger.info(f"   [人类模拟] 短消息逐字输入(Unicode): {text!r}")

    # 逐字输入
    for ch in text:
        if _is_ascii_char(ch):
            _type_char_unicode(ch)
            _human_sleep(CHAR_GAP_MIN, CHAR_GAP_MAX)
        else:
            # 中文用 WM_IME_CHAR
            _type_ime_char(hwnd, ch)
            _human_sleep(IME_CHAR_GAP_MIN, IME_CHAR_GAP_MAX)

    logger.info(f"   [人类模拟] 逐字输入完成: {text}")
    return True


def _type_via_clipboard(hwnd, text):
    """用剪贴板粘贴输入文本（分段或整段）。

    用于长消息或 IME_CHAR 未启用时的中文消息。

    Args:
        hwnd: 目标窗口句柄
        text: 要输入的文本

    Returns:
        bool: 是否成功
    """
    segments = _split_text(text)

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
        _human_sleep_with_pause(SEG_GAP_MIN, SEG_GAP_MAX)  # 段间停顿，偶发长停顿
        if not _set_clipboard_text(seg):
            logger.warning(f"   ⚠️ 第 {idx} 段剪贴板设置失败")
            return False
        _human_sleep(CLIPBOARD_WAIT_MIN, CLIPBOARD_WAIT_MAX)
        _press_key_combo(VK_CONTROL, VK_V)
        _human_sleep(PASTE_WAIT_MIN, PASTE_WAIT_MAX)

    return True


def human_input_text(hwnd, text):
    """人类模拟输入文字，自动选择最佳输入策略。

    输入策略（自动选择）：
    1. 短消息（≤ SHORT_MSG_THRESHOLD 字符）：
       - 纯 ASCII：逐字 SendInput + KEYEVENTF_UNICODE（绕过剪贴板和 IME）
       - 含中文 + USE_IME_CHAR_FOR_CHINESE=True：ASCII 用 Unicode，中文用 WM_IME_CHAR
       - 含中文 + USE_IME_CHAR_FOR_CHINESE=False：剪贴板粘贴（fallback）
    2. 长消息（> SHORT_MSG_THRESHOLD 字符）：分段剪贴板粘贴

    所有按键操作使用 SendInput（带扫描码），替代 keybd_event。

    Args:
        hwnd: 目标窗口句柄（需在前台才能接收输入）
        text: 要输入的文本

    Returns:
        bool: 是否成功
    """
    if not text:
        return True

    logger.info(f"   [人类模拟] 输入 {text!r}（{len(text)} 字符）")

    # 短消息：逐字输入（更隐蔽）
    if len(text) <= SHORT_MSG_THRESHOLD:
        return _type_short_message(hwnd, text)

    # 长消息：分段剪贴板粘贴
    logger.info(f"   [人类模拟] 长消息走分段粘贴路径（{len(text)} > {SHORT_MSG_THRESHOLD}）")
    success = _type_via_clipboard(hwnd, text)
    if success:
        logger.info(f"   [人类模拟] 输入完成: {text}")
    return success


def random_operation_gap(min_s=0.3, max_s=0.8):
    """在两个独立操作之间加入随机间隔（如搜索→点击头像之间）。

    用于在阶段切换时插入更长的随机停顿，模拟人类思考/反应时间。
    偶发引入长停顿（5% 概率 1-3 秒），模拟人类走神。
    """
    _human_sleep_with_pause(min_s, max_s, allow_pause=True)
