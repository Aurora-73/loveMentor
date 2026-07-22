"""
阶段三：输入和发送图片（v4 第十六章多媒体发送能力）。

技术方案（v4 16.2 节）：
- 复用文本发送的剪贴板机制，只需把剪贴板内容从文字换成图片
- input_image_via_clipboard(hwnd, image_path) → 剪贴板放图片 → Ctrl+V → 微信显示预览 → 点击发送

流程（与 run_send_message 一致，仅第 6 步不同）：
1. 找微信窗口 + 截图
2. 检测聊天区域分界线（session_right）
3. 计算输入框位置（聊天区域底部中心，距底部约 80px）
4. 物理点击输入框
5. 把图片放到剪贴板 + Ctrl+V 粘贴（微信显示图片预览，发送按钮变绿）
6. 重新截图（此时发送按钮是绿色）
7. 从右下角开始向左上角找绿色发送按钮
8. 物理点击发送按钮
9. 截图验证

用法：
    # 只检测布局（不发送）：点击输入框 + 粘贴图片 + 找发送按钮 + 不点击发送
    python send_image_run.py

    # 检测 + 发送图片
    python send_image_run.py "C:\\path\\to\\image.jpg"
"""
import os
import sys
import io
import time

import ctypes
import ctypes.wintypes as wintypes

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

import cv2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# 添加项目根目录到 sys.path（用于 from engine.wechat_sender.xxx import 的绝对导入）
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

# 统一配置（从 config.py 导入，避免散落）
from config import (  # noqa: E402
    SEND_BTN_BGR,
    SEND_BTN_TOLERANCE,
    INPUT_BOX_OFFSET_FROM_BOTTOM,
)

user32 = ctypes.windll.user32

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")

# 支持的图片格式
_SUPPORTED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp", ".tiff"}


def _set_clipboard_image(image_path: str) -> bool:
    """用 ctypes 直接设置剪贴板图片（CF_DIB 格式）。

    避免依赖 pywin32（项目未安装），复用 human_sim._set_clipboard_text 的 ctypes 模式。

    Args:
        image_path: 图片文件路径

    Returns:
        bool: True=成功，False=失败
    """
    CF_DIB = 8  # Device-Independent Bitmap
    GMEM_MOVEABLE = 0x0002

    kernel32 = ctypes.windll.kernel32

    # 64位系统必须设置函数原型，否则句柄被截断为32位导致失败
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.SetClipboardData.restype = wintypes.HANDLE
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]

    try:
        from PIL import Image
    except ImportError:
        logger.error("❌ 未安装 PIL/Pillow，无法设置剪贴板图片")
        return False

    try:
        # 读取图片并转成 RGB（去掉 alpha 通道，BMP DIB 不支持 alpha）
        img = Image.open(image_path)
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGB")
        elif img.mode != "RGB":
            img = img.convert("RGB")

        # 保存为 BMP 到内存缓冲区
        buf = io.BytesIO()
        img.save(buf, format="BMP")
        bmp_data = buf.getvalue()

        # BMP 文件头是 14 字节（BITMAPFILEHEADER），DIB 格式去掉文件头
        # BITMAPFILEHEADER: signature(2) + filesize(4) + reserved(4) + data_offset(4) = 14 bytes
        dib_data = bmp_data[14:]

    except Exception as e:
        logger.error(f"❌ 读取图片失败: {e}")
        return False

    if not user32.OpenClipboard(None):
        logger.error("❌ OpenClipboard 失败")
        return False
    try:
        user32.EmptyClipboard()
        h_global = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(dib_data))
        if not h_global:
            logger.error("❌ GlobalAlloc 失败")
            return False
        ptr = kernel32.GlobalLock(h_global)
        if not ptr:
            logger.error("❌ GlobalLock 失败")
            return False
        ctypes.memmove(ptr, dib_data, len(dib_data))
        kernel32.GlobalUnlock(h_global)
        result = user32.SetClipboardData(CF_DIB, h_global)
        if not result:
            logger.error("❌ SetClipboardData(CF_DIB) 失败")
            return False
        logger.info(f"   ✅ 剪贴板已设置图片 DIB ({len(dib_data)} bytes)")
        return True
    finally:
        user32.CloseClipboard()


def _press_ctrl_v(hwnd):
    """在目标窗口上按 Ctrl+V 粘贴。

    使用 SendInput 发送 Ctrl+V，与 human_sim 中的按键方式一致。
    """
    # 复用 human_sim 的 _send_key_press（带扫描码，更稳定）
    from human_sim import _press_single_key

    VK_CONTROL = 0x11
    VK_V = 0x56

    # 确保 hwnd 是前台窗口
    safe_set_foreground_window(hwnd)
    time.sleep(0.2)

    # 按下 Ctrl
    user32.keybd_event(VK_CONTROL, 0, 0, 0)  # 0 = keydown
    time.sleep(0.05)
    # 按下 V
    user32.keybd_event(VK_V, 0, 0, 0)
    time.sleep(0.05)
    # 抬起 V
    user32.keybd_event(VK_V, 0, 0x0002, 0)  # KEYEVENTF_KEYUP = 0x0002
    time.sleep(0.05)
    # 抬起 Ctrl
    user32.keybd_event(VK_CONTROL, 0, 0x0002, 0)
    time.sleep(0.3)


def input_image_via_clipboard(hwnd, image_path):
    """用剪贴板 + Ctrl+V 输入图片（需要窗口在前台）。

    流程：
    1. 验证图片文件存在且格式支持
    2. 把图片 DIB 放到剪贴板
    3. 在目标窗口按 Ctrl+V 粘贴

    Args:
        hwnd: 目标窗口句柄
        image_path: 图片文件路径

    Returns:
        bool: True=成功，False=失败
    """
    # 验证图片文件
    if not os.path.exists(image_path):
        logger.error(f"❌ 图片文件不存在: {image_path}")
        return False

    ext = os.path.splitext(image_path)[1].lower()
    if ext not in _SUPPORTED_IMAGE_EXTS:
        logger.error(f"❌ 不支持的图片格式: {ext}（支持: {_SUPPORTED_IMAGE_EXTS}）")
        return False

    logger.info(f"   [剪贴板] 准备粘贴图片: {image_path}")

    # 设置剪贴板
    if not _set_clipboard_image(image_path):
        return False

    # Ctrl+V 粘贴
    _press_ctrl_v(hwnd)

    logger.info(f"   ✅ 图片已粘贴到输入框")
    return True


def run_send_image(image_path, do_send=True):
    """执行阶段三（图片版）：粘贴图片并发送。

    与 run_send_message 的区别：
    - 第 6 步用 input_image_via_clipboard 替代 input_text_via_clipboard
    - 不分段（图片只有一张）
    - 第 11 步不做 OCR 文字验证（图片无法用文字 OCR 验证）

    Args:
        image_path: 图片文件路径
        do_send: True=发送，False=只检测不发送

    Returns:
        bool: 是否成功
    """
    logger.info("=" * 60)
    if do_send:
        logger.info(f"  阶段三（图片版）：粘贴并发送图片  path={image_path!r}")
    else:
        logger.info("  阶段三（图片版）：只检测布局（粘贴图片但不发送）")
    logger.info("=" * 60)

    # 前置检查：图片文件
    if not os.path.exists(image_path):
        logger.error(f"❌ 图片文件不存在: {image_path}")
        return False

    ext = os.path.splitext(image_path)[1].lower()
    if ext not in _SUPPORTED_IMAGE_EXTS:
        logger.error(f"❌ 不支持的图片格式: {ext}")
        return False

    # 0. 前置检查：微信是否已登录
    try:
        from wechat_window_utils import check_login_status
        login_info = check_login_status()
        if not login_info["logged_in"]:
            logger.error("❌ 微信未登录，拒绝发送图片")
            logger.info(f"   登录状态: tray_icon={login_info['tray_icon_found']} "
                        f"main_window_size={login_info['main_window_size']}")
            return False
        logger.info(f"[0] 登录状态: 已登录 (tray={login_info['tray_method']}, "
                    f"main_size={login_info['main_window_size']})")
    except Exception as e:
        logger.warning(f"⚠️ 登录状态检测异常: {e}，继续尝试发送")

    # 1. 找微信窗口
    window = find_largest_wechat_window()
    if not window:
        logger.error("❌ 未找到微信窗口")
        return False
    hwnd = window["hwnd"]
    logger.info(f"\n[1] 微信窗口: hwnd={hwnd} size={window['width']}x{window['height']}")

    if window["width"] < 500 or window["height"] < 400:
        logger.error(f"❌ 微信窗口太小 ({window['width']}x{window['height']})")
        return False

    # 2. 截图（发送前）
    logger.info("\n[2] 截图（发送前）")
    img = screencap_window(hwnd)
    if img is None:
        logger.error("❌ 截图失败")
        return False
    img_path = os.path.join(OUTPUT_DIR, "stage_3_img_before_send.png")
    cv2.imwrite(img_path, img)
    logger.info(f"    截图: {img_path} ({img.shape[1]}x{img.shape[0]})")

    h, w = img.shape[:2]

    # 3. 检测聊天区域分界线
    logger.info("\n[3] 检测聊天区域分界线")
    detector = WeChatLayoutDetector()
    nav_right, session_right = detector.detect(img)
    logger.info(f"    nav_right={nav_right} session_right={session_right}")

    chat_x = session_right
    chat_w = w - session_right
    logger.info(f"    聊天区域: x={chat_x} w={chat_w}")

    # 4. 计算输入框位置（聊天区域底部中心，距底部 80px）
    input_cx = chat_x + chat_w // 2
    input_cy = h - INPUT_BOX_OFFSET_FROM_BOTTOM
    logger.info(f"\n[4] 输入框位置(截图坐标): ({input_cx}, {input_cy})")

    # 5. 物理点击输入框
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

    # 6. 粘贴图片（此时微信显示图片预览，发送按钮变绿）
    logger.info(f"\n[6] 粘贴图片: {image_path}")
    if not input_image_via_clipboard(hwnd, image_path):
        logger.error("❌ 粘贴图片失败")
        return False
    # 等待微信显示图片预览（图片预览加载比文字慢）
    time.sleep(1.5)

    # 7. 重新截图（此时发送按钮是绿色）
    logger.info("\n[7] 重新截图（发送按钮应变绿）")
    img_after_input = screencap_window(hwnd)
    if img_after_input is None:
        logger.error("❌ 重新截图失败")
        return False
    img_after_input_path = os.path.join(OUTPUT_DIR, "stage_3_img_after_input.png")
    cv2.imwrite(img_after_input_path, img_after_input)
    logger.info(f"    截图: {img_after_input_path}")

    # 8. 定位发送按钮（OCR 优先，回退到绿色按钮检测）
    logger.info("\n[8] 定位发送按钮")
    from send_message_run import find_send_button_by_ocr, find_send_button_from_bottom_right

    send_cx, send_cy, send_debug = find_send_button_by_ocr(img_after_input)

    if send_cx is None:
        logger.info("    OCR 未找到，回退到绿色按钮检测...")
        send_cx, send_cy, send_debug = find_send_button_from_bottom_right(
            img_after_input, session_right
        )

    send_debug_path = os.path.join(OUTPUT_DIR, "stage_3_img_send_button.png")
    cv2.imwrite(send_debug_path, send_debug)
    logger.info(f"    发送按钮检测图: {send_debug_path}")

    if send_cx is None:
        logger.error("    ❌ 未找到发送按钮")
        logger.info("    可能原因：图片未粘贴成功，或发送按钮位置不在右下角 1/3 区域")
        return False

    logger.info(f"    ✅ 找到发送按钮: ({send_cx}, {send_cy})")

    if not do_send:
        logger.info("\n[只检测模式] 已找到发送按钮，未点击发送")
        return True

    # 9. 物理点击发送按钮
    logger.info(f"\n[9] 物理点击发送按钮 ({send_cx}, {send_cy})")
    client_x = send_cx - offset_x
    client_y = send_cy - offset_y
    screen_x, screen_y = client_to_screen(hwnd, client_x, client_y)
    logger.info(f"    发送按钮屏幕坐标: ({screen_x}, {screen_y})")
    physical_click(screen_x, screen_y)
    # 等待图片上传完成（图片比文字上传慢，需要更长等待）
    time.sleep(3.0)

    # 10. 截图验证（发送后）
    logger.info("\n[10] 截图验证（发送后）")
    after_img = screencap_window(hwnd)
    if after_img is None:
        logger.error("❌ 发送后截图失败")
        return False
    after_path = os.path.join(OUTPUT_DIR, "stage_3_img_after_send.png")
    cv2.imwrite(after_path, after_img)
    logger.info(f"    发送后截图: {after_path}")

    # 11. 图片发送验证：对比输入框区域，检查图片预览是否消失
    # 不用发送按钮颜色判断（模板匹配无论绿色/灰色都能匹配到，无法区分）
    # 改为对比发送前后的输入框区域，如果差异大说明图片预览消失 = 发送成功
    logger.info("\n[11] 图片发送验证（输入框清空检测）")
    h_img = img_after_input.shape[0]
    # 输入框区域：聊天区域底部 120px
    input_box_before = img_after_input[h_img - 120:h_img, session_right:]
    input_box_after = after_img[h_img - 120:h_img, session_right:]
    diff = cv2.absdiff(input_box_after, input_box_before)
    mean_diff = float(diff.mean())

    if mean_diff > 5.0:
        # 输入框区域变化大 = 图片预览消失 = 发送成功
        logger.info(f"    ✅ 输入框已清空（差异值 {mean_diff:.2f}），图片发送成功")
    else:
        # 输入框区域变化小 = 图片预览仍在 = 可能未发送
        logger.warning(f"    ⚠️ 输入框未清空（差异值 {mean_diff:.2f}），可能未发送成功")
        return False

    logger.info("\n" + "=" * 60)
    logger.info("  阶段三（图片版）完成")
    logger.info("=" * 60)
    return True


def main():
    """命令行入口：python send_image_run.py <image_path>"""
    if len(sys.argv) < 2:
        logger.info("用法: python send_image_run.py <图片路径>")
        logger.info("示例: python send_image_run.py C:\\\\Users\\\\test\\\\image.jpg")
        sys.exit(1)

    image_path = sys.argv[1]
    if not os.path.exists(image_path):
        logger.error(f"❌ 图片文件不存在: {image_path}")
        sys.exit(1)

    success = run_send_image(image_path, do_send=True)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
