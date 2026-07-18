"""打开微信窗口 — 在微信已启动但无窗口的情况下，点击托盘图标唤醒。

场景：
- 微信进程已启动，但窗口被关闭/最小化到托盘
- 需要通过点击任务栏右下角托盘的微信图标来唤醒窗口

设计要点（基于录屏分析）：
- 托盘图标在系统右下角，不需要全屏匹配
- 微信收到消息时图标会闪烁（绿色↔灰色），周期约 1.867 秒
- 常态下图标是稳定绿色，颜色匹配即可定位
- 截屏间隔建议 0.2~0.3 秒（闪烁场景），但唤醒操作不需要等闪烁

实现方式：
1. 先检查微信窗口是否已存在（避免不必要的托盘点击）
2. 定位任务栏托盘区域（Shell_TrayWnd 右侧）
3. 截图托盘区域，用 HSV 颜色匹配找微信绿色图标
4. 物理点击图标
5. 轮询等待微信窗口出现

用法：
    from engine.wechat_sender.open_wechat_window import open_wechat_window
    success = open_wechat_window()  # 返回 bool
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
from logger import get_logger  # noqa: E402
from wechat_window_utils import find_wechat_window  # noqa: E402

logger = get_logger(__name__)

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32


# ========== 常量 ==========
# 微信绿色 HSV 范围（H: 60-90 绿色系，S/V 较高确保饱和度）
WX_GREEN_LOWER = np.array([60, 80, 80])
WX_GREEN_UPPER = np.array([90, 255, 255])

# 托盘区域：任务栏右侧的比例（避免扫描整个任务栏）
TRAY_RIGHT_RATIO = 0.30  # 只扫描任务栏右侧 30%
TRAY_LEFT_RATIO = 0.50   # 闪烁场景可扩展到右侧 50%

# 托盘图标面积阈值（任务栏图标通常 20x20 到 40x40）
MIN_ICON_AREA = 100
MAX_ICON_AREA_RATIO = 0.5  # 最大不超过任务栏高度的平方的 50%

# 鼠标事件常量
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004


def _capture_region(left, top, width, height):
    """用 BitBlt 从屏幕 DC 截取指定区域。

    Args:
        left, top: 屏幕坐标左上角
        width, height: 区域尺寸

    Returns:
        numpy.ndarray (BGR) 或 None
    """
    if width <= 0 or height <= 0:
        return None

    hdc_screen = user32.GetDC(None)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
    hbmp = gdi32.CreateCompatibleBitmap(hdc_screen, width, height)
    old_bmp = gdi32.SelectObject(hdc_mem, hbmp)

    SRCCOPY = 0x00CC0020
    gdi32.BitBlt(hdc_mem, 0, 0, width, height, hdc_screen, left, top, SRCCOPY)

    # BITMAPINFOHEADER
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

    gdi32.SelectObject(hdc_mem, old_bmp)
    gdi32.DeleteObject(hbmp)
    gdi32.DeleteDC(hdc_mem)
    user32.ReleaseDC(None, hdc_screen)

    arr = np.frombuffer(buffer.raw, dtype=np.uint8).reshape((height, width, 4))
    img = arr[:, :, :3].copy()
    return img


def _find_tray_window():
    """找到系统托盘窗口（通知区域）。

    Windows 10/11 的托盘窗口层次：
    Shell_TrayWnd
      └─ TrayNotifyWnd
           └─ Shell_TrayWnd (右侧)
                └─ ToolbarWindow32 (通知区域)

    但直接找 ToolbarWindow32 不可靠（类名可能不同）。
    更可靠的方式：找 Shell_TrayWnd，然后用其右侧区域。
    """
    Shell_TrayWnd = user32.FindWindowW("Shell_TrayWnd", None)
    if not Shell_TrayWnd:
        logger.warning("⚠️ 未找到任务栏窗口 Shell_TrayWnd")
        return None

    rect = wintypes.RECT()
    user32.GetWindowRect(Shell_TrayWnd, ctypes.byref(rect))
    return {
        "hwnd": Shell_TrayWnd,
        "left": rect.left,
        "top": rect.top,
        "right": rect.right,
        "bottom": rect.bottom,
        "width": rect.right - rect.left,
        "height": rect.bottom - rect.top,
    }


def _find_wechat_icon_in_tray(tray_img, tray_left, tray_top):
    """在托盘截图中用 HSV 颜色匹配找微信绿色图标。

    Args:
        tray_img: 托盘区域截图 (BGR)
        tray_left, tray_top: 托盘区域在屏幕上的左上角坐标

    Returns:
        (screen_x, screen_y) 或 None
    """
    if tray_img is None or tray_img.size == 0:
        return None

    h, w = tray_img.shape[:2]
    logger.info(f"   托盘截图尺寸: {w}x{h}")

    # 转 HSV 并匹配微信绿色
    hsv = cv2.cvtColor(tray_img, cv2.COLOR_BGR2HSV)
    green_mask = cv2.inRange(hsv, WX_GREEN_LOWER, WX_GREEN_UPPER)

    # 形态学操作去噪
    kernel = np.ones((3, 3), np.uint8)
    green_mask = cv2.morphologyEx(green_mask, cv2.MORPH_OPEN, kernel)
    green_mask = cv2.morphologyEx(green_mask, cv2.MORPH_CLOSE, kernel)

    # 找轮廓
    contours, _ = cv2.findContours(green_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    max_area = int(h * h * MAX_ICON_AREA_RATIO)
    candidates = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < MIN_ICON_AREA or area > max_area:
            continue
        x, y, cw, ch = cv2.boundingRect(cnt)
        aspect_ratio = float(cw) / ch if ch > 0 else 0
        # 任务栏图标通常接近正方形
        if 0.5 < aspect_ratio < 2.0:
            cx = x + cw // 2
            cy = y + ch // 2
            candidates.append({
                "area": area,
                "center": (cx, cy),
                "size": (cw, ch),
            })
            logger.info(f"   候选绿色区域: center=({cx},{cy}) size={cw}x{ch} area={area}")

    if not candidates:
        logger.warning("   ⚠️ 托盘区域未找到微信绿色图标候选")
        return None

    # 选面积最大的候选（微信图标通常是托盘中最大的绿色图标）
    best = max(candidates, key=lambda c: c["area"])
    cx, cy = best["center"]
    screen_x = tray_left + cx
    screen_y = tray_top + cy
    logger.info(f"   📍 微信托盘图标位置: ({screen_x}, {screen_y}) area={best['area']}")
    return (screen_x, screen_y)


def _physical_click(screen_x, screen_y):
    """物理点击屏幕坐标。

    已委托给 human_sim.human_physical_click，托盘图标较小，用 2px 抖动半径。
    """
    from human_sim import human_physical_click
    human_physical_click(screen_x, screen_y, jitter_radius=2)
    logger.info(f"   ✅ 已点击托盘图标: ({screen_x}, {screen_y})")


def _double_click(screen_x, screen_y):
    """双击（某些情况下单击只是显示托盘气泡，双击才能打开窗口）。"""
    _physical_click(screen_x, screen_y)
    time.sleep(0.1)
    _physical_click(screen_x, screen_y)


def _find_wechat_icon_in_tray_with_icon_match(tray_img, tray_left, tray_top):
    """优先用 icon 模板匹配找微信图标，失败则回退到 HSV 颜色匹配。

    改进：避免 HSV 误判其他绿色软件（如 Snipaste、企业微信等）。

    Args:
        tray_img: 托盘区域截图 (BGR)
        tray_left, tray_top: 托盘区域在屏幕上的左上角坐标

    Returns:
        (screen_x, screen_y, method, confidence) 或 None
        method: "icon_template" 或 "hsv_fallback"
    """
    # 1. 优先 icon 模板匹配
    try:
        from wechat_window_utils import _load_wx_icons, find_wechat_icon_by_template
        icons = _load_wx_icons()
        if icons:
            match = find_wechat_icon_by_template(tray_img, icons, tray_left, tray_top)
            if match:
                return (match[0], match[1], "icon_template", match[2])
    except Exception as e:
        logger.warning(f"   ⚠️ icon 模板匹配异常: {e}，回退到 HSV")

    # 2. fallback: HSV 颜色匹配
    hsv_pos = _find_wechat_icon_in_tray(tray_img, tray_left, tray_top)
    if hsv_pos:
        return (hsv_pos[0], hsv_pos[1], "hsv_fallback", None)
    return None


def open_wechat_window(timeout=10.0, try_double_click=False):
    """在微信已启动但无窗口的情况下，点击托盘图标唤醒微信窗口。

    改进：优先用 icon 模板匹配定位微信图标（更准确，避免 HSV 误判其他绿色软件），
    失败则回退到 HSV 颜色匹配。

    Args:
        timeout: 等待微信窗口出现的最大秒数
        try_double_click: 是否尝试双击（某些 Windows 版本需要双击托盘图标）

    Returns:
        bool: 是否成功唤醒微信窗口
    """
    logger.info("=" * 60)
    logger.info("  打开微信窗口（托盘图标唤醒）")
    logger.info("=" * 60)

    # 1. 先检查微信窗口是否已存在
    existing = find_wechat_window()
    if existing:
        logger.info(f"✅ 微信窗口已存在: hwnd={existing['hwnd']} size={existing['width']}x{existing['height']}")
        return True

    logger.info("ℹ️ 微信窗口不存在，尝试通过托盘图标唤醒...")

    # 2. 找到任务栏
    tray = _find_tray_window()
    if not tray:
        logger.error("❌ 未找到任务栏，无法定位托盘")
        return False

    logger.info(f"   任务栏: left={tray['left']} top={tray['top']} "
                f"size={tray['width']}x{tray['height']}")

    # 3. 截图托盘右侧区域（通知区域在右下角）
    # 只扫描右侧 TRAY_RIGHT_RATIO 区域，避免匹配到任务栏左侧的应用图标
    tray_region_width = int(tray["width"] * TRAY_RIGHT_RATIO)
    tray_left = tray["right"] - tray_region_width
    tray_top = tray["top"]
    tray_region_height = tray["height"]

    logger.info(f"   托盘扫描区域: ({tray_left}, {tray_top}) "
                f"size={tray_region_width}x{tray_region_height}")

    tray_img = _capture_region(tray_left, tray_top, tray_region_width, tray_region_height)
    if tray_img is None:
        logger.error("❌ 托盘区域截图失败")
        return False

    # 保存截图用于调试
    try:
        debug_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")
        os.makedirs(debug_dir, exist_ok=True)
        debug_path = os.path.join(debug_dir, "tray_capture_debug.png")
        cv2.imwrite(debug_path, tray_img)
        logger.info(f"   托盘截图已保存: {debug_path}")
    except Exception:
        pass

    # 4. 在托盘区域找微信图标（优先 icon 模板匹配，fallback HSV）
    icon_result = _find_wechat_icon_in_tray_with_icon_match(tray_img, tray_left, tray_top)
    if icon_result is None:
        logger.error("❌ 未在托盘找到微信图标（微信可能未启动，或图标被隐藏）")
        logger.info("   建议：1) 确认微信进程已启动  2) 检查托盘图标是否被隐藏到溢出区")
        return False

    screen_x, screen_y, method, confidence = icon_result
    logger.info(f"   📍 微信托盘图标位置: ({screen_x}, {screen_y}) method={method}"
                + (f" confidence={confidence:.3f}" if confidence is not None else ""))

    # 5. 点击托盘图标
    if try_double_click:
        logger.info("   尝试双击托盘图标...")
        _double_click(screen_x, screen_y)
    else:
        _physical_click(screen_x, screen_y)

    # 6. 等待微信窗口出现
    logger.info(f"   等待微信窗口出现（最多 {timeout} 秒）...")
    start_time = time.time()
    while time.time() - start_time < timeout:
        time.sleep(0.5)
        window = find_wechat_window()
        if window:
            elapsed = time.time() - start_time
            logger.info(f"✅ 微信窗口已出现: hwnd={window['hwnd']} "
                        f"size={window['width']}x{window['height']} (耗时 {elapsed:.1f}s)")
            return True

    logger.error(f"❌ 等待 {timeout} 秒后微信窗口仍未出现")
    logger.info("   可能原因：1) 单击只显示了气泡提示，需双击  2) 微信进程异常  3) 窗口被最小化到托盘需多次点击")
    return False


def open_wechat_window_robust(timeout=10.0):
    """稳健版打开微信窗口：先单击，失败则双击。

    Args:
        timeout: 每次尝试的等待秒数

    Returns:
        bool
    """
    # 第一次尝试：单击
    if open_wechat_window(timeout=timeout, try_double_click=False):
        return True

    logger.info("   单击未生效，尝试双击...")

    # 第二次尝试：双击
    # 先关闭可能出现的气泡（按 Esc，已升级为 SendInput 带扫描码）
    # ⚠️ 注意：这里调用时微信主窗口本来就没有（否则 open_wechat_window 第一次就成功了），
    #    所以按 Esc 不会触发"关闭主面板"快捷键（主面板本来就没打开）。
    from human_sim import _press_single_key, VK_ESCAPE
    _press_single_key(VK_ESCAPE)
    time.sleep(0.3)

    if open_wechat_window(timeout=timeout, try_double_click=True):
        return True

    return False


if __name__ == "__main__":
    # 命令行测试
    success = open_wechat_window_robust(timeout=10.0)
    if success:
        logger.info("\n🎉 微信窗口已成功打开")
    else:
        logger.error("\n💥 打开微信窗口失败")
        sys.exit(1)
