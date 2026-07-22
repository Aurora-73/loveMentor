"""stage3 公共函数（v4 重构：提取公共发送逻辑）。

从 run_send_message / run_send_emoji / run_send_image 三个函数中提取公共步骤，
减少 60-70% 的重复代码。

公共步骤（text/image 共享，emoji 部分共享）：
1. check_wechat_login() — 登录检查
2. find_wechat_main_window() — 找微信窗口 + 检查大小
3. capture_and_detect_layout(hwnd, screenshot_name) — 截图 + 检测布局
4. click_input_box(hwnd, img, session_right) — 计算输入框位置 + 点击
5. find_send_button(img, session_right) — 定位发送按钮（OCR 优先 + 绿色按钮回退）
6. click_send_button(hwnd, send_cx, send_cy, offset_x, offset_y) — 点击发送按钮
7. capture_screenshot(hwnd, filename) — 通用截图保存

使用方式：
    from send_common import (
        check_wechat_login,
        find_wechat_main_window,
        capture_and_detect_layout,
        click_input_box,
        find_send_button,
        click_send_button,
        capture_screenshot,
    )
"""
import os
import sys
import time

import ctypes
import ctypes.wintypes as wintypes

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

import cv2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from dynamic_detector import WeChatLayoutDetector  # noqa: E402
from window_capture import screencap_window  # noqa: E402
from wechat_window_utils import find_largest_wechat_window  # noqa: E402
from click_search_and_input import (  # noqa: E402
    get_client_offset,
    client_to_screen,
    physical_click,
    safe_set_foreground_window,
)

from logger import get_logger  # noqa: E402
logger = get_logger(__name__)

from config import INPUT_BOX_OFFSET_FROM_BOTTOM  # noqa: E402

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")


def check_wechat_login():
    """检查微信是否已登录（步骤 0）。

    三个 stage3 函数的登录检查逻辑完全相同，提取为公共函数。

    Returns:
        tuple (logged_in: bool, login_info: dict)
        - logged_in: True=已登录，False=未登录
        - login_info: 登录状态详情（tray_icon_found, main_window_size, tray_method 等）
    """
    try:
        from wechat_window_utils import check_login_status
        login_info = check_login_status()
        if not login_info["logged_in"]:
            logger.error("❌ 微信未登录，拒绝发送消息")
            logger.info(f"   登录状态: tray_icon={login_info['tray_icon_found']} "
                        f"main_window_size={login_info['main_window_size']} "
                        f"hidden_subwindow={login_info.get('has_hidden_subwindow', 'N/A')}")
            logger.info("   请先调用 wechat_start 启动并登录微信")
            return False, login_info
        logger.info(f"[0] 登录状态: 已登录 (tray={login_info['tray_method']}, "
                    f"main_size={login_info['main_window_size']})")
        return True, login_info
    except Exception as e:
        logger.warning(f"⚠️ 登录状态检测异常: {e}，继续尝试发送")
        return True, {"logged_in": True, "error": str(e)}


def find_wechat_main_window():
    """找微信主窗口 + 检查窗口大小（步骤 1）。

    三个 stage3 函数的窗口查找逻辑完全相同。

    Returns:
        dict | None: 窗口信息 dict（hwnd, width, height 等），None=未找到或太小
    """
    window = find_largest_wechat_window()
    if not window:
        logger.error("❌ 未找到微信窗口")
        return None

    hwnd = window["hwnd"]
    logger.info(f"\n[1] 微信窗口: hwnd={hwnd} size={window['width']}x{window['height']}")

    # 检查窗口大小（避免找到托盘图标等小窗口）
    if window["width"] < 500 or window["height"] < 400:
        logger.error(f"❌ 微信窗口太小 ({window['width']}x{window['height']})，可能不是主窗口")
        logger.info("   请确认微信主窗口已打开并显示在屏幕上")
        return None

    return window


def capture_and_detect_layout(hwnd, screenshot_name="stage_3_before_send.png"):
    """截图 + 检测聊天区域分界线（步骤 2-3）。

    三个 stage3 函数的截图和布局检测逻辑相同，只是截图文件名不同。

    Args:
        hwnd: 微信窗口句柄
        screenshot_name: 截图保存文件名（相对 OUTPUT_DIR）

    Returns:
        tuple (img, nav_right, session_right) | (None, 0, 0)
        - img: 截图图像（BGR）
        - nav_right: 导航栏右边界 x 坐标
        - session_right: 会话列表右边界 x 坐标（聊天区域起始 x）
    """
    # 步骤 2：截图（发送前）
    logger.info("\n[2] 截图（发送前）")
    img = screencap_window(hwnd)
    if img is None:
        logger.error("❌ 截图失败")
        return None, 0, 0

    img_path = os.path.join(OUTPUT_DIR, screenshot_name)
    cv2.imwrite(img_path, img)
    logger.info(f"    截图: {img_path} ({img.shape[1]}x{img.shape[0]})")

    h, w = img.shape[:2]

    # 步骤 3：检测聊天区域分界线
    logger.info("\n[3] 检测聊天区域分界线")
    detector = WeChatLayoutDetector()
    nav_right, session_right = detector.detect(img)
    logger.info(f"    nav_right={nav_right} session_right={session_right}")

    chat_x = session_right
    chat_w = w - session_right
    logger.info(f"    聊天区域: x={chat_x} w={chat_w}")

    return img, nav_right, session_right


def click_input_box(hwnd, img, session_right, draw_annotation=True):
    """计算输入框位置 + 物理点击输入框（步骤 4-5）。

    run_send_message 和 run_send_image 的输入框点击逻辑相同。
    run_send_emoji 不使用此函数（它点击表情按钮而非输入框）。

    Args:
        hwnd: 微信窗口句柄
        img: 截图图像（用于计算位置和标注）
        session_right: 会话列表右边界（聊天区域起始 x）
        draw_annotation: 是否绘制输入框标注图（默认 True）

    Returns:
        tuple (offset_x, offset_y) | (None, None)
        - offset_x, offset_y: 客户区偏移量（后续点击发送按钮时需要）
        - None, None: 点击失败
    """
    h, w = img.shape[:2]

    # 步骤 4：计算输入框位置（聊天区域底部中心，距底部 80px）
    chat_x = session_right
    chat_w = w - session_right
    input_cx = chat_x + chat_w // 2
    input_cy = h - INPUT_BOX_OFFSET_FROM_BOTTOM
    logger.info(f"\n[4] 输入框位置(截图坐标): ({input_cx}, {input_cy})")

    # 标注输入框位置（可选）
    if draw_annotation:
        try:
            from send_message_run import draw_input_box
            input_vis = draw_input_box(img, input_cx, input_cy, session_right)
            input_vis_path = os.path.join(OUTPUT_DIR, "stage_3_input_box.png")
            cv2.imwrite(input_vis_path, input_vis)
            logger.info(f"    输入框标注图: {input_vis_path}")
        except Exception as e:
            logger.warning(f"    输入框标注图绘制失败: {e}")

    # 步骤 5：物理点击输入框
    logger.info(f"\n[5] 物理点击输入框")
    offset_x, offset_y = get_client_offset(hwnd)
    client_x = input_cx - offset_x
    client_y = input_cy - offset_y
    screen_x, screen_y = client_to_screen(hwnd, client_x, client_y)
    logger.info(f"    输入框屏幕坐标: ({screen_x}, {screen_y})")
    safe_set_foreground_window(hwnd)
    time.sleep(0.5)
    physical_click(screen_x, screen_y)
    time.sleep(0.8)

    return offset_x, offset_y


def find_send_button(img, session_right, screenshot_name="stage_3_send_button.png"):
    """定位发送按钮（步骤 8）。

    OCR 优先识别"发送"文字，回退到绿色按钮检测。
    run_send_message 和 run_send_image 的发送按钮定位逻辑相同。
    run_send_emoji 不使用此函数（它在表情面板选表情）。

    Args:
        img: 截图图像（输入内容后的截图）
        session_right: 会话列表右边界（绿色按钮回退检测需要）
        screenshot_name: 发送按钮检测图保存文件名

    Returns:
        tuple (send_cx, send_cy, debug_img) | (None, None, None)
        - send_cx, send_cy: 发送按钮中心坐标（截图坐标）
        - debug_img: 标注了发送按钮位置的调试图
    """
    from send_message_run import find_send_button_by_ocr, find_send_button_from_bottom_right

    logger.info("\n[8] 定位发送按钮（OCR 优先）")
    send_cx, send_cy, send_debug = find_send_button_by_ocr(img)

    if send_cx is None:
        logger.info("    OCR 未找到，回退到绿色按钮检测...")
        send_cx, send_cy, send_debug = find_send_button_from_bottom_right(
            img, session_right
        )

    send_debug_path = os.path.join(OUTPUT_DIR, screenshot_name)
    cv2.imwrite(send_debug_path, send_debug)
    logger.info(f"    发送按钮检测图: {send_debug_path}")

    if send_cx is None:
        logger.error("    ❌ 未找到发送按钮")
        logger.info("    可能原因：内容未输入成功，或发送按钮位置不在右下角 1/3 区域")
        return None, None, None

    logger.info(f"    ✅ 找到发送按钮: ({send_cx}, {send_cy})")
    return send_cx, send_cy, send_debug


def click_send_button(hwnd, send_cx, send_cy, offset_x, offset_y, wait_seconds=1.5):
    """物理点击发送按钮（步骤 9）。

    Args:
        hwnd: 微信窗口句柄
        send_cx, send_cy: 发送按钮中心坐标（截图坐标）
        offset_x, offset_y: 客户区偏移量（来自 click_input_box 的返回值）
        wait_seconds: 点击后等待时间（文字 1.5s，图片 3.0s）

    Returns:
        bool: 是否成功点击
    """
    logger.info(f"\n[9] 物理点击发送按钮 ({send_cx}, {send_cy})")
    client_x = send_cx - offset_x
    client_y = send_cy - offset_y
    screen_x, screen_y = client_to_screen(hwnd, client_x, client_y)
    logger.info(f"    发送按钮屏幕坐标: ({screen_x}, {screen_y})")
    physical_click(screen_x, screen_y)
    time.sleep(wait_seconds)
    return True


def capture_screenshot(hwnd, filename):
    """通用截图保存（步骤 7/10）。

    Args:
        hwnd: 窗口句柄
        filename: 保存文件名（相对 OUTPUT_DIR）

    Returns:
        numpy.ndarray | None: 截图图像，None=失败
    """
    img = screencap_window(hwnd)
    if img is None:
        logger.error("❌ 截图失败")
        return None

    img_path = os.path.join(OUTPUT_DIR, filename)
    cv2.imwrite(img_path, img)
    logger.info(f"    截图: {img_path} ({img.shape[1]}x{img.shape[0]})")
    return img
