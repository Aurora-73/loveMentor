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

# 支持的视频格式（CF_HDROP 发送，微信自动识别为视频）
_SUPPORTED_VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".flv", ".wmv", ".m4v", ".3gp"}

# 所有支持的格式（图片 + 视频 + 其他文件）
_SUPPORTED_MEDIA_EXTS = _SUPPORTED_IMAGE_EXTS | _SUPPORTED_VIDEO_EXTS


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
    from send_common import (
        check_wechat_login, find_wechat_main_window,
        capture_and_detect_layout, click_input_box,
        capture_screenshot, find_send_button, click_send_button,
    )

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
    logged_in, _ = check_wechat_login()
    if not logged_in:
        return False

    # 1. 找微信窗口
    window = find_wechat_main_window()
    if not window:
        return False
    hwnd = window["hwnd"]

    # 2-3. 截图 + 检测聊天区域分界线
    img, nav_right, session_right = capture_and_detect_layout(
        hwnd, screenshot_name="stage_3_img_before_send.png"
    )
    if img is None:
        return False

    h, w = img.shape[:2]

    # 4-5. 计算输入框位置 + 物理点击输入框
    offset_x, offset_y = click_input_box(hwnd, img, session_right, draw_annotation=False)
    if offset_x is None:
        return False

    # 6. 粘贴图片（此时微信显示图片预览，发送按钮变绿）
    logger.info(f"\n[6] 粘贴图片: {image_path}")
    if not input_image_via_clipboard(hwnd, image_path):
        logger.error("❌ 粘贴图片失败")
        return False
    # 等待微信显示图片预览（图片预览加载比文字慢）
    time.sleep(1.5)

    # 7. 重新截图（此时发送按钮应变绿）
    logger.info("\n[7] 重新截图（发送按钮应变绿）")
    img_after_input = capture_screenshot(hwnd, "stage_3_img_after_input.png")
    if img_after_input is None:
        return False

    # 8. 定位发送按钮（OCR 优先，回退到绿色按钮检测）
    send_cx, send_cy, _ = find_send_button(
        img_after_input, session_right, screenshot_name="stage_3_img_send_button.png"
    )
    if send_cx is None:
        return False

    if not do_send:
        logger.info("\n[只检测模式] 已找到发送按钮，未点击发送")
        return True

    # 9. 物理点击发送按钮（图片上传慢，等待 3.0s）
    click_send_button(hwnd, send_cx, send_cy, offset_x, offset_y, wait_seconds=3.0)

    # 10. 截图验证（发送后）
    logger.info("\n[10] 截图验证（发送后）")
    after_img = capture_screenshot(hwnd, "stage_3_img_after_send.png")
    if after_img is None:
        return False

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


# ── 视频/文件发送（CF_HDROP 剪贴板格式，模拟 Explorer 复制）──────────────────


def _set_clipboard_file(file_path: str) -> bool:
    """用 ctypes 设置剪贴板文件（CF_HDROP 格式，模拟 Explorer 复制）。

    当你在 Explorer 中右键复制文件时，Windows 将文件路径以 CF_HDROP 格式放入剪贴板。
    微信接受此格式，根据文件类型自动处理：
    - 视频文件 → 显示视频预览/发送为视频
    - 其他文件 → 发送为文件

    Args:
        file_path: 文件路径（视频/文档/任意文件）

    Returns:
        bool: True=成功，False=失败
    """
    import struct

    CF_HDROP = 15  # File drop format
    GMEM_MOVEABLE = 0x0002

    kernel32 = ctypes.windll.kernel32

    # 64位系统必须设置函数原型
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.SetClipboardData.restype = wintypes.HANDLE
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]

    # DROPFILES structure (20 bytes)
    # typedef struct {
    #     DWORD pFiles;     // offset to file list (= sizeof(DROPFILES) = 20)
    #     POINT pt;         // drop point (0, 0) — 2x DWORD = 8 bytes
    #     BOOL  fNC;        // non-client area flag (FALSE = 0)
    #     BOOL  fWide;      // Unicode flag (TRUE = 1)
    # } DROPFILES;
    # Layout: pFiles(4) + pt.x(4) + pt.y(4) + fNC(4) + fWide(4) = 20 bytes

    abs_path = os.path.abspath(file_path)
    # 文件列表：UTF-16-LE 编码，以双 \0 结尾
    file_list = (abs_path + "\0\0").encode("utf-16-le")

    dropfiles = struct.pack("IiiII", 20, 0, 0, 0, 1)  # pFiles=20, pt=(0,0), fNC=0, fWide=1
    data = dropfiles + file_list

    if not user32.OpenClipboard(None):
        logger.error("❌ OpenClipboard 失败")
        return False
    try:
        user32.EmptyClipboard()
        h_global = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not h_global:
            logger.error("❌ GlobalAlloc 失败")
            return False
        ptr = kernel32.GlobalLock(h_global)
        if not ptr:
            logger.error("❌ GlobalLock 失败")
            return False
        ctypes.memmove(ptr, data, len(data))
        kernel32.GlobalUnlock(h_global)
        result = user32.SetClipboardData(CF_HDROP, h_global)
        if not result:
            logger.error("❌ SetClipboardData(CF_HDROP) 失败")
            return False
        logger.info(f"   ✅ 剪贴板已设置文件 HDROP ({len(data)} bytes): {abs_path}")
        return True
    finally:
        user32.CloseClipboard()


def input_file_via_clipboard(hwnd, file_path):
    """用剪贴板 + Ctrl+V 输入文件（视频/文档/任意文件，模拟 Explorer 复制粘贴）。

    流程：
    1. 验证文件存在
    2. 把文件路径以 CF_HDROP 格式放到剪贴板（模拟 Explorer 复制）
    3. 在目标窗口按 Ctrl+V 粘贴

    微信会根据文件类型自动处理：
    - 视频（mp4/mov 等）→ 发送为视频
    - 其他文件 → 发送为文件

    Args:
        hwnd: 目标窗口句柄
        file_path: 文件路径

    Returns:
        bool: True=成功，False=失败
    """
    if not os.path.exists(file_path):
        logger.error(f"❌ 文件不存在: {file_path}")
        return False

    logger.info(f"   [剪贴板] 准备粘贴文件: {file_path}")

    # 设置剪贴板（CF_HDROP）
    if not _set_clipboard_file(file_path):
        return False

    # Ctrl+V 粘贴
    _press_ctrl_v(hwnd)

    logger.info(f"   ✅ 文件已粘贴到输入框")
    return True


def run_send_file(file_path, do_send=True):
    """执行阶段三（文件版）：粘贴文件（视频/文档）并发送。

    与 run_send_image 的区别：
    - 使用 CF_HDROP 剪贴板格式（模拟 Explorer 复制），而非 CF_DIB（位图）
    - 支持视频（mp4/mov 等）和任意文件类型
    - 微信自动识别文件类型并处理
    - 视频文件较大时等待时间更长（3.0s vs 1.5s）

    技术原理（用户指导）：
    "视频和文件的逻辑是一样的，都是复制粘贴然后发送，就是 explorer 里的那种复制，
     然后就可以粘贴到微信里"

    Args:
        file_path: 文件路径（视频/文档/任意文件）
        do_send: True=发送，False=只检测不发送

    Returns:
        bool: 是否成功
    """
    from send_common import (
        check_wechat_login, find_wechat_main_window,
        capture_and_detect_layout, click_input_box,
        capture_screenshot, find_send_button, click_send_button,
    )

    logger.info("=" * 60)
    if do_send:
        logger.info(f"  阶段三（文件版）：粘贴并发送文件  path={file_path!r}")
    else:
        logger.info("  阶段三（文件版）：只检测布局（粘贴文件但不发送）")
    logger.info("=" * 60)

    # 前置检查：文件存在
    if not os.path.exists(file_path):
        logger.error(f"❌ 文件不存在: {file_path}")
        return False

    # 检查文件大小（视频可能很大，警告 > 100MB）
    file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
    if file_size_mb > 100:
        logger.warning(f"⚠️ 文件较大 ({file_size_mb:.1f} MB)，发送可能需要较长时间")
    elif file_size_mb > 25:
        logger.info(f"   文件大小: {file_size_mb:.1f} MB")

    # 0. 前置检查：微信是否已登录
    logged_in, _ = check_wechat_login()
    if not logged_in:
        return False

    # 1. 找微信窗口
    window = find_wechat_main_window()
    if not window:
        return False
    hwnd = window["hwnd"]

    # 2-3. 截图 + 检测聊天区域分界线
    img, nav_right, session_right = capture_and_detect_layout(
        hwnd, screenshot_name="stage_3_file_before_send.png"
    )
    if img is None:
        return False

    h, w = img.shape[:2]

    # 4-5. 计算输入框位置 + 物理点击输入框
    offset_x, offset_y = click_input_box(hwnd, img, session_right, draw_annotation=False)
    if offset_x is None:
        return False

    # 6. 粘贴文件（CF_HDROP 格式，微信自动识别类型）
    logger.info(f"\n[6] 粘贴文件: {file_path}")
    if not input_file_via_clipboard(hwnd, file_path):
        logger.error("❌ 粘贴文件失败")
        return False

    # 等待微信处理文件（视频/大文件加载比图片慢）
    # 根据文件大小动态调整等待时间
    if file_size_mb > 50:
        wait_time = 4.0  # 大文件等待 4s
    elif file_size_mb > 10:
        wait_time = 3.0  # 中等文件等待 3s
    else:
        wait_time = 2.0  # 小文件等待 2s
    logger.info(f"   等待微信处理文件 ({wait_time}s)...")
    time.sleep(wait_time)

    # 7. 重新截图（此时发送按钮应变绿）
    logger.info("\n[7] 重新截图（发送按钮应变绿）")
    img_after_input = capture_screenshot(hwnd, "stage_3_file_after_input.png")
    if img_after_input is None:
        return False

    # 8. 定位发送按钮
    send_cx, send_cy, _ = find_send_button(
        img_after_input, session_right, screenshot_name="stage_3_file_send_button.png"
    )
    if send_cx is None:
        return False

    if not do_send:
        logger.info("\n[只检测模式] 已找到发送按钮，未点击发送")
        return True

    # 9. 物理点击发送按钮（文件上传慢，等待更久）
    click_send_button(hwnd, send_cx, send_cy, offset_x, offset_y, wait_seconds=4.0)

    # 10. 截图验证（发送后）
    logger.info("\n[10] 截图验证（发送后）")
    after_img = capture_screenshot(hwnd, "stage_3_file_after_send.png")
    if after_img is None:
        return False

    # 11. 文件发送验证：检查输入框清空 OR 聊天区域有新消息
    # 文件发送与图片发送的 UI 变化不同：
    # - 图片发送：图片预览在输入框区域，发送后预览消失 → 输入框差异大
    # - 文件发送：文件消息直接出现在聊天区域 → 聊天区域差异大，输入框差异小
    # 因此需要同时检查两个区域，任一差异大即认为发送成功
    logger.info("\n[11] 文件发送验证（输入框清空 + 聊天区域新消息检测）")
    h_img = img_after_input.shape[0]

    # 检查输入框区域（图片预览消失检测）
    input_box_before = img_after_input[h_img - 120:h_img, session_right:]
    input_box_after = after_img[h_img - 120:h_img, session_right:]
    input_diff = cv2.absdiff(input_box_after, input_box_before)
    input_mean = float(input_diff.mean())

    # 检查聊天区域（新消息出现检测）
    chat_before = img_after_input[100:h_img - 120, session_right:]
    chat_after = after_img[100:h_img - 120, session_right:]
    chat_diff = cv2.absdiff(chat_after, chat_before)
    chat_mean = float(chat_diff.mean())

    logger.info(f"    输入框差异: {input_mean:.2f}, 聊天区域差异: {chat_mean:.2f}")

    # 输入框清空 OR 聊天区域有新消息 → 发送成功
    if input_mean > 5.0 or chat_mean > 5.0:
        if chat_mean > 5.0:
            logger.info(f"    ✅ 聊天区域检测到新消息（差异值 {chat_mean:.2f}），文件发送成功")
        else:
            logger.info(f"    ✅ 输入框已清空（差异值 {input_mean:.2f}），文件发送成功")
    else:
        logger.warning(f"    ⚠️ 输入框未清空（{input_mean:.2f}）且聊天区域无新消息（{chat_mean:.2f}），可能未发送成功")
        return False

    logger.info("\n" + "=" * 60)
    logger.info("  阶段三（文件版）完成")
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
