"""
点击微信搜索栏并输入联系人昵称 [REDACTED]。

流程：
1. 查找微信窗口
2. 截图
3. 检测分界线（复用 dynamic_detector）
4. 检测搜索栏位置（中间栏最白行）
5. 用 PostMessage 后台点击搜索栏（不干扰用户操作）
6. 用剪贴板 + Ctrl+V 输入 "[REDACTED]"
"""
import os
import sys
import time

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

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dynamic_detector import WeChatLayoutDetector
from test_current_wechat import find_wechat_window, screencap_window

from logger import get_logger  # noqa: E402
logger = get_logger(__name__)

user32 = ctypes.windll.user32

# Windows 消息常量
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
MK_LBUTTON = 0x0001
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_CHAR = 0x0102
VK_CONTROL = 0x11
VK_V = 0x56


def get_client_offset(hwnd):
    """计算客户区左上角相对窗口左上角的偏移（物理像素）"""
    class POINT(ctypes.Structure):
        _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

    window_rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(window_rect))

    client_point = POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(client_point))

    offset_x = client_point.x - window_rect.left
    offset_y = client_point.y - window_rect.top
    return offset_x, offset_y


def client_to_screen(hwnd, client_x, client_y):
    """客户区坐标转屏幕坐标"""
    class POINT(ctypes.Structure):
        _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]
    pt = POINT(client_x, client_y)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return pt.x, pt.y


def click_taskbar_wechat(max_wait=5.0):
    """在任务栏上找到微信图标并点击，激活微信窗口。

    通过 BitBlt 从屏幕 DC 截取任务栏区域，用 HSV 颜色匹配找到微信绿色图标，
    物理点击该位置。此方法模拟用户点击行为，可绕过 SetForegroundWindow 权限限制。

    Args:
        max_wait: 点击后等待微信窗口出现在前台的最大秒数

    Returns:
        bool: 是否成功激活微信窗口
    """
    import ctypes.wintypes as wintypes

    gdi32 = ctypes.windll.gdi32

    # 1. 找到任务栏窗口
    Shell_TrayWnd = user32.FindWindowW("Shell_TrayWnd", None)
    if not Shell_TrayWnd:
        logger.warning("   ⚠️ 未找到任务栏窗口")
        return False

    # 获取任务栏矩形
    rect = wintypes.RECT()
    user32.GetWindowRect(Shell_TrayWnd, ctypes.byref(rect))
    width = rect.right - rect.left
    height = rect.bottom - rect.top

    if width <= 0 or height <= 0:
        logger.warning(f"   ⚠️ 任务栏尺寸异常: {width}x{height}")
        return False

    # 2. 用 BitBlt 从屏幕 DC 截取任务栏区域
    hdc_screen = user32.GetDC(None)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
    hbmp = gdi32.CreateCompatibleBitmap(hdc_screen, width, height)
    old_bmp = gdi32.SelectObject(hdc_mem, hbmp)

    SRCCOPY = 0x00CC0020
    gdi32.BitBlt(hdc_mem, 0, 0, width, height, hdc_screen, rect.left, rect.top, SRCCOPY)

    # 3. 转换为 OpenCV 格式
    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.UINT),
            ("biWidth", wintypes.LONG),
            ("biHeight", wintypes.LONG),
            ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD),
            ("biCompression", wintypes.UINT),
            ("biSizeImage", wintypes.UINT),
            ("biXPelsPerMeter", wintypes.LONG),
            ("biYPelsPerMeter", wintypes.LONG),
            ("biClrUsed", wintypes.UINT),
            ("biClrImportant", wintypes.UINT),
        ]

    bih = BITMAPINFOHEADER()
    bih.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bih.biWidth = width
    bih.biHeight = -height  # 负值表示从上到下
    bih.biPlanes = 1
    bih.biBitCount = 32
    bih.biCompression = 0

    buffer_size = width * height * 4
    buffer = ctypes.create_string_buffer(buffer_size)
    gdi32.GetDIBits(hdc_mem, hbmp, 0, height, buffer, ctypes.byref(bih), 0)

    # 清理 GDI 资源
    gdi32.SelectObject(hdc_mem, old_bmp)
    gdi32.DeleteObject(hbmp)
    gdi32.DeleteDC(hdc_mem)
    user32.ReleaseDC(None, hdc_screen)

    # 转换为 numpy 数组
    import numpy as np
    arr = np.frombuffer(buffer.raw, dtype=np.uint8).reshape((height, width, 4))
    img = arr[:, :, :3].copy()

    # 4. 用 HSV 颜色匹配找到微信绿色图标
    import cv2
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

    # 微信绿色 HSV 范围
    lower_green = np.array([60, 80, 80])
    upper_green = np.array([90, 255, 255])
    mask = cv2.inRange(hsv, lower_green, upper_green)

    # 找到绿色区域的轮廓
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    # 过滤候选区域（任务栏图标通常 16x16 到 48x48）
    min_area = 100
    max_area = height * height
    candidates = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < min_area or area > max_area:
            continue
        x, y, w, h = cv2.boundingRect(cnt)
        aspect_ratio = float(w) / h if h > 0 else 0
        if 0.5 < aspect_ratio < 2.0:
            candidates.append({
                'area': area,
                'center': (x + w // 2, y + h // 2),
            })

    if not candidates:
        logger.warning("   ⚠️ 任务栏上未找到微信图标（无绿色候选区域）")
        return False

    # 选面积最大的候选
    best = max(candidates, key=lambda c: c['area'])
    cx, cy = best['center']
    screen_x = rect.left + cx
    screen_y = rect.top + cy

    logger.info(f"   📍 任务栏微信图标位置: ({screen_x}, {screen_y})，候选数: {len(candidates)}")

    # 5. 物理点击任务栏上的微信图标
    physical_click(screen_x, screen_y)

    # 6. 等待微信窗口出现在前台
    start_time = time.time()
    while time.time() - start_time < max_wait:
        time.sleep(0.5)
        foreground_hwnd = user32.GetForegroundWindow()
        if foreground_hwnd:
            # 检查前台窗口是否是微信
            from test_current_wechat import find_wechat_window
            wechat_window = find_wechat_window()
            if wechat_window and wechat_window["hwnd"] == foreground_hwnd:
                elapsed = time.time() - start_time
                logger.info(f"   ✅ 点击任务栏图标成功，微信已在前台（耗时 {elapsed:.1f}s）")
                return True

    logger.warning(f"   ⚠️ 点击任务栏图标后 {max_wait}s 内微信未出现在前台")
    return False


def safe_set_foreground_window(hwnd, max_retries=3):
    """安全地将窗口设为前台（带重试和多种 trick）。

    SetForegroundWindow 有权限限制，直接调用可能失败。
    使用 AttachThreadInput + Alt 键 trick + 任务栏点击组合方法绕过限制。

    Args:
        hwnd: 目标窗口句柄
        max_retries: 最大重试次数

    Returns:
        bool: 是否成功
    """
    KEYEVENTF_KEYUP = 0x0002
    VK_MENU = 0x12  # Alt 键

    # 获取当前前台窗口和线程
    foreground_hwnd = user32.GetForegroundWindow()
    if foreground_hwnd == hwnd:
        return True

    kernel32 = ctypes.windll.kernel32
    foreground_thread_id = user32.GetWindowThreadProcessId(foreground_hwnd, None)
    current_thread_id = kernel32.GetCurrentThreadId()

    for i in range(max_retries):
        # 方法1: AttachThreadInput（最可靠）
        attached = False
        if foreground_thread_id != current_thread_id:
            if user32.AttachThreadInput(current_thread_id, foreground_thread_id, True):
                attached = True

        # 方法2: Alt 键 trick（模拟用户活动）
        if i > 0 or not attached:
            user32.keybd_event(VK_MENU, 0, 0, 0)
            time.sleep(0.05)
            user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
            time.sleep(0.1)

        # 尝试多种方式激活窗口
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        result = user32.SetForegroundWindow(hwnd)
        user32.BringWindowToTop(hwnd)

        # 解除 AttachThreadInput
        if attached:
            user32.AttachThreadInput(current_thread_id, foreground_thread_id, False)

        if result:
            time.sleep(0.2)
            if user32.GetForegroundWindow() == hwnd:
                return True

        logger.warning(f"   ⚠️ SetForegroundWindow 第 {i+1} 次失败 (hwnd={hwnd})")
        time.sleep(0.3)

    # 所有重试失败，尝试用 PowerShell COM 对象激活（最后手段）
    try:
        import subprocess
        # WScript.Shell.AppActivate 通过 COM 激活窗口，可能绕过 SetForegroundWindow 限制
        subprocess.run(
            ["powershell", "-Command",
             "$wshell = New-Object -ComObject WScript.Shell; $wshell.AppActivate('微信')"],
            capture_output=True, timeout=3,
        )
        time.sleep(0.5)
        if user32.GetForegroundWindow() == hwnd:
            logger.info(f"   ✅ PowerShell AppActivate 成功激活微信窗口")
            return True
    except Exception:
        pass

    # 最终回退：点击任务栏上的微信图标（模拟用户行为，最可靠）
    logger.info(f"   🔄 尝试点击任务栏微信图标...")
    if click_taskbar_wechat(max_wait=5.0):
        return True

    # 所有方法都失败，仍然继续（PrintWindow 可能仍能工作）
    logger.warning(f"   ⚠️ SetForegroundWindow {max_retries} 次重试均失败 (hwnd={hwnd})，继续尝试")
    return False


def physical_click(screen_x, screen_y):
    """用 SetCursorPos + mouse_event 物理点击屏幕坐标。

    已委托给 human_sim.human_physical_click，默认带 3px 随机抖动和随机点击间隔，
    模拟人类点击行为，降低被封号风险。
    """
    # 延迟导入避免循环依赖
    from human_sim import human_physical_click
    human_physical_click(screen_x, screen_y, jitter_radius=3)


def post_click(hwnd, client_x, client_y):
    """用 PostMessage 后台点击（坐标为客户区坐标）"""
    lparam = (client_y << 16) | (client_x & 0xFFFF)
    user32.PostMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lparam)
    time.sleep(0.05)
    user32.PostMessageW(hwnd, WM_LBUTTONUP, 0, lparam)
    logger.info(f"   PostMessage 点击客户区坐标: ({client_x}, {client_y})")


def post_key(hwnd, vk, down=True):
    """发送按键"""
    msg = WM_KEYDOWN if down else WM_KEYUP
    lparam = 1  # repeat count
    user32.PostMessageW(hwnd, msg, vk, lparam)


def set_clipboard_text(text):
    """用 ctypes 直接设置剪贴板文本（避免 PowerShell 注入风险）。

    Args:
        text: 要写入剪贴板的文本

    Returns:
        bool: 是否成功
    """
    import ctypes.wintypes as wintypes

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

    # 转为 UTF-16LE 字节（Windows 剪贴板 Unicode 格式）
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


def input_text_via_clipboard(hwnd, text):
    """用剪贴板 + keybd_event Ctrl+V 输入文本（需要窗口在前台）。

    已委托给 human_sim.human_input_text，默认会把消息切成若干段，
    以随机间隔逐段输入，模拟人类打字节奏，降低被封号风险。
    """
    # 延迟导入避免循环依赖
    from human_sim import human_input_text
    return human_input_text(hwnd, text)


def find_search_bar(image, nav_right, session_right):
    """在中间栏内寻找搜索栏位置（复用 search_bar_finder 逻辑）"""
    h, w = image.shape[:2]
    search_x = (nav_right + session_right) // 2

    session_region = image[:, nav_right:session_right]
    gray = cv2.cvtColor(session_region, cv2.COLOR_BGR2GRAY)
    row_brightness = np.mean(gray, axis=1)

    search_top = 0
    search_bottom = int(h * 0.3)
    search_row_range = row_brightness[search_top:search_bottom]
    search_y = search_top + int(np.argmax(search_row_range))

    return search_x, search_y


def main():
    logger.info("=" * 60)
    logger.info("        点击搜索栏并输入联系人昵称")
    logger.info("=" * 60)

    # 1. 查找窗口
    window = find_wechat_window()
    if not window:
        logger.error("❌ 未找到微信窗口")
        return
    hwnd = window["hwnd"]
    logger.info(f"找到微信窗口: {window['width']}x{window['height']}")

    # 2. 截图
    logger.info("正在截取微信窗口...")
    image = screencap_window(hwnd)
    if image is None:
        logger.error("❌ 截图失败")
        return

    # 3. 检测分界线
    logger.info("\n检测界面分界线...")
    detector = WeChatLayoutDetector()
    nav_right, session_right = detector.detect(image)

    # 4. 检测搜索栏
    search_x, search_y = find_search_bar(image, nav_right, session_right)
    logger.info(f"\n搜索栏位置（截图坐标）: ({search_x}, {search_y})")

    # 5. 计算客户区坐标
    offset_x, offset_y = get_client_offset(hwnd)
    logger.info(f"客户区偏移: x={offset_x}, y={offset_y}")
    client_x = search_x - offset_x
    client_y = search_y - offset_y
    logger.info(f"搜索栏客户区坐标: ({client_x}, {client_y})")

    # 6. 将微信设为前台
    logger.info("\n将微信设为前台...")
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.5)

    # 7. 物理点击搜索栏（屏幕坐标）
    screen_x, screen_y = client_to_screen(hwnd, client_x, client_y)
    logger.info(f"搜索栏屏幕坐标: ({screen_x}, {screen_y})")
    logger.info("物理点击搜索栏...")
    physical_click(screen_x, screen_y)
    time.sleep(0.8)  # 等待搜索框激活

    # 8. 输入文本
    logger.info("输入文本 [REDACTED]...")
    input_text_via_clipboard(hwnd, "[REDACTED]")
    time.sleep(0.5)

    logger.info("\n✅ 完成，请检查微信窗口搜索栏是否已输入 [REDACTED]")


if __name__ == "__main__":
    main()
