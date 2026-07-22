"""
阶段三：输入和发送消息（对应 talk.md 阶段三）。

用户澄清：
- 绿色发送按钮只有在输入框内有内容时才是绿色
- 发送按钮一般就在右下角附近，可以从右下角开始向左上角寻找绿色

流程：
1. 找微信窗口 + 截图
2. 检测聊天区域分界线（session_right）
3. 计算输入框位置（聊天区域底部中心，距底部约 80px）
4. 物理点击输入框
5. 用剪贴板输入消息内容（此时发送按钮变绿）
6. 重新截图（此时发送按钮是绿色）
7. 从右下角开始向左上角找绿色发送按钮（BGR 96, 193, 7）
8. 物理点击发送按钮
9. 截图验证

用法：
    # 只检测布局（不发送）：点击输入框 + 输入测试文本 + 找发送按钮 + 不点击发送
    python examples/wechat_auto/send_message_run.py

    # 检测 + 发送消息
    python examples/wechat_auto/send_message_run.py "你好，这是测试消息"
"""
import os
import re
import sys
import time

import ctypes
import ctypes.wintypes as wintypes

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# 添加项目根目录到 sys.path（用于 from engine.wechat_sender.xxx import 的绝对导入）
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
from dynamic_detector import WeChatLayoutDetector  # noqa: E402
from window_capture import find_wechat_window, screencap_window  # noqa: E402
from wechat_window_utils import find_largest_wechat_window  # noqa: E402  统一窗口枚举
from click_search_and_input import (  # noqa: E402
    get_client_offset,
    client_to_screen,
    physical_click,
    input_text_via_clipboard,
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


def find_send_button_by_ocr(image):
    """定位发送按钮（v3.0 三层架构：图标模板匹配 → OCR → 颜色检测）。

    识别策略：
    - 方法0: 图标模板匹配（v6 验证 conf=1.0000，速度快 100 倍）—— 最优先
        - 可发送态: send_green_full.png / send_green_compact.png
        - 不可发送态: 发送-灰色.png
    - 方法1: OCR 识别"发送"文字 —— 回退

    Args:
        image: 微信窗口截图（BGR numpy 数组）

    Returns:
        tuple: (center_x, center_y, marked_image) 或 (None, None, image)
    """
    marked = image.copy()

    # 方法0: 图标模板匹配（v3.0 新增，v6 验证 conf=1.0000）
    try:
        # sys.path 已在模块顶部配置（_PROJECT_ROOT）
        from engine.wechat_sender.template_matcher import find_send_button as find_send_button_template

        template_match = find_send_button_template(image, threshold=0.85)
        if template_match is not None:
            cx, cy = template_match.center_x, template_match.center_y
            logger.info(
                f"    ✅ [模板匹配] 发送按钮 conf={template_match.confidence:.4f} "
                f"pos=({cx}, {cy})"
            )
            # 在图上标注
            cv2.circle(marked, (cx, cy), 15, (0, 255, 0), 3)
            cv2.putText(
                marked, f"SEND ({cx},{cy}) conf={template_match.confidence:.3f}",
                (cx + 20, cy), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                (0, 0, 255), 2, cv2.LINE_AA,
            )
            return cx, cy, marked
        else:
            logger.info("    [模板匹配] 未找到发送按钮，回退到 OCR")
    except Exception as e:
        logger.warning(f"    ⚠️ 模板匹配失败: {e}，回退到 OCR", exc_info=True)

    # 方法1: OCR 识别"发送"文字
    try:
        from engine.importers.ocr_engine import ocr_image_array

        results = ocr_image_array(image, use_cache=False)

        for r in results:
            # 匹配规则：文字长度至多4字符且包含"发送"
            if '发送' in r.text and len(r.text) <= 4:
                cx, cy = r.center_x, r.center_y
                logger.info(f"    ✅ OCR 识别到'{r.text}' center=({cx}, {cy}) conf={r.confidence:.3f}")
                # 在图上标注
                pts = [(int(p[0]), int(p[1])) for p in r.bbox]
                cv2.polylines(marked, [np.array(pts)], True, (0, 255, 0), 2)
                cv2.circle(marked, (cx, cy), 10, (0, 255, 0), 2)
                return cx, cy, marked

        logger.warning("    ⚠️ OCR 未识别到含'发送'的文字（≤4字符）")
    except Exception as e:
        logger.warning(f"    ⚠️ OCR 识别失败: {e}", exc_info=True)

    return None, None, marked


def find_send_button_from_bottom_right(image, session_right):
    """从右下角开始向左上角找绿色发送按钮。

    用户澄清：发送按钮一般就在右下角附近，前提是输入框有内容。

    算法：
    1. 在聊天区域右下角 1/3 区域内找绿色像素（BGR 96, 193, 7，容差 30）
    2. 用连通组件分析，找最大的绿色组件
    3. 返回组件中心

    Returns:
        (send_cx, send_cy, debug_image) 或 (None, None, debug_image)
    """
    h, w = image.shape[:2]
    chat_w = w - session_right

    # 搜索区域：聊天区域右下角 1/3，但最小宽度 200px（避免窄窗口搜索区域过小）
    search_width = max(chat_w // 3, min(200, chat_w))
    search_x1 = w - search_width
    search_y1 = h * 2 // 3
    search_x2 = w
    search_y2 = h
    search_area = image[search_y1:search_y2, search_x1:search_x2]

    debug = image.copy()
    # 画搜索区域（蓝色框）
    cv2.rectangle(debug, (search_x1, search_y1), (search_x2, search_y2), (255, 0, 0), 1)
    cv2.putText(debug, "SEARCH_AREA", (search_x1 + 5, search_y1 + 20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 1, cv2.LINE_AA)

    # 绿色像素检测
    lower = np.array([max(0, c - SEND_BTN_TOLERANCE) for c in SEND_BTN_BGR], dtype=np.uint8)
    upper = np.array([min(255, c + SEND_BTN_TOLERANCE) for c in SEND_BTN_BGR], dtype=np.uint8)
    green_mask = cv2.inRange(search_area, lower, upper)

    # 连通组件分析
    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(green_mask)

    best_component = None
    best_area = 0
    for i in range(1, num_labels):
        area = stats[i, cv2.CC_STAT_AREA]
        if area > best_area and area > 20:  # 至少 20 像素
            best_area = area
            best_component = i

    if best_component is None:
        return None, None, debug

    # 组件中心（转换为全图坐标）
    cx = int(centroids[best_component][0]) + search_x1
    cy = int(centroids[best_component][1]) + search_y1

    # 在 debug 图上标注
    x = stats[best_component, cv2.CC_STAT_LEFT] + search_x1
    y = stats[best_component, cv2.CC_STAT_TOP] + search_y1
    cw = stats[best_component, cv2.CC_STAT_WIDTH]
    ch = stats[best_component, cv2.CC_STAT_HEIGHT]
    cv2.rectangle(debug, (x, y), (x + cw, y + ch), (0, 255, 0), 2)
    cv2.circle(debug, (cx, cy), 15, (0, 0, 255), 3)
    cv2.putText(debug, f"SEND ({cx},{cy}) area={best_area}",
                (cx + 20, cy), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                (0, 0, 255), 2, cv2.LINE_AA)

    return cx, cy, debug


def draw_input_box(image, input_cx, input_cy, session_right):
    """在图上标注输入框位置"""
    out = image.copy()
    cv2.circle(out, (input_cx, input_cy), 20, (0, 255, 255), 3)
    cv2.line(out, (input_cx - 30, input_cy), (input_cx + 30, input_cy),
             (0, 255, 255), 3)
    cv2.line(out, (input_cx, input_cy - 30), (input_cx, input_cy + 30),
             (0, 255, 255), 3)
    cv2.putText(out, f"INPUT_BOX ({input_cx},{input_cy})",
                (input_cx + 40, input_cy), cv2.FONT_HERSHEY_SIMPLEX,
                0.7, (0, 255, 255), 2, cv2.LINE_AA)
    cv2.line(out, (session_right, 0), (session_right, out.shape[0]), (255, 0, 0), 1)
    return out


def run_send_message(message, do_send=True):
    """执行阶段三：输入和发送消息"""
    from send_common import (
        check_wechat_login, find_wechat_main_window,
        capture_and_detect_layout, click_input_box,
        capture_screenshot, find_send_button, click_send_button,
    )

    logger.info("=" * 60)
    if do_send:
        logger.info(f"  阶段三：输入和发送消息  message={message!r}")
    else:
        logger.info("  阶段三：只检测布局（输入测试文本但不发送）")
    logger.info("=" * 60)

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
    img, nav_right, session_right = capture_and_detect_layout(hwnd)
    if img is None:
        return False

    h, w = img.shape[:2]

    # 4-5. 计算输入框位置 + 物理点击输入框
    offset_x, offset_y = click_input_box(hwnd, img, session_right)
    if offset_x is None:
        return False

    # 6. 输入消息（此时发送按钮变绿）
    # 超长消息分段输入+发送，避免输入框滚动导致发送按钮位置变化
    MAX_MSG_LENGTH = 500  # 微信输入框单次最大推荐长度
    logger.info(f"\n[6] 输入消息: {message!r}")

    if len(message) <= MAX_MSG_LENGTH:
        # 短消息：一次性输入+发送
        input_text_via_clipboard(hwnd, message)
        time.sleep(0.8)
    else:
        # 长消息：分段输入+发送
        logger.info(f"    消息较长（{len(message)} 字符），分 {(len(message) + MAX_MSG_LENGTH - 1) // MAX_MSG_LENGTH} 段发送")
        segments = [message[i:i+MAX_MSG_LENGTH] for i in range(0, len(message), MAX_MSG_LENGTH)]
        for seg_idx, segment in enumerate(segments, 1):
            logger.info(f"    --- 第 {seg_idx}/{len(segments)} 段 ---")
            input_text_via_clipboard(hwnd, segment)
            time.sleep(0.8)

            # 找发送按钮并发送本段
            seg_img = screencap_window(hwnd)
            if seg_img is None:
                logger.error(f"    ❌ 第 {seg_idx} 段截图失败")
                return False
            seg_cx, seg_cy, _ = find_send_button_by_ocr(seg_img)
            if seg_cx is None:
                seg_cx, seg_cy, _ = find_send_button_from_bottom_right(seg_img, session_right)
            if seg_cx is None:
                logger.error(f"    ❌ 第 {seg_idx} 段未找到发送按钮")
                return False
            logger.info(f"    第 {seg_idx} 段发送按钮: ({seg_cx}, {seg_cy})")
            seg_offset_x, seg_offset_y = get_client_offset(hwnd)
            seg_screen_x, seg_screen_y = client_to_screen(hwnd, seg_cx - seg_offset_x, seg_cy - seg_offset_y)
            safe_set_foreground_window(hwnd)
            time.sleep(0.3)
            physical_click(seg_screen_x, seg_screen_y)
            time.sleep(1.0)

        # 所有分段发送完成，直接返回成功（跳过后续单次发送逻辑）
        logger.info("\n" + "=" * 60)
        logger.info("  阶段三完成（分段发送）")
        logger.info("=" * 60)
        return True

    # 7. 重新截图（此时发送按钮应变绿）
    logger.info("\n[7] 重新截图（发送按钮应变绿）")
    img_after_input = capture_screenshot(hwnd, "stage_3_after_input.png")
    if img_after_input is None:
        return False

    # 8. 定位发送按钮（OCR 优先，回退到绿色按钮检测）
    send_cx, send_cy, _ = find_send_button(img_after_input, session_right)
    if send_cx is None:
        return False

    if not do_send:
        logger.info("\n[只检测模式] 已找到发送按钮，未点击发送")
        return True

    # 9. 物理点击发送按钮
    click_send_button(hwnd, send_cx, send_cy, offset_x, offset_y, wait_seconds=1.5)

    # 10. 截图验证（发送后）
    logger.info("\n[10] 截图验证（发送后）")
    after_img = capture_screenshot(hwnd, "stage_3_after_send.png")
    if after_img is None:
        return False

    # 11. OCR 验证：确认消息出现在聊天记录中
    logger.info("\n[11] OCR 验证消息是否出现在聊天记录")
    verify_ok = verify_message_sent(after_img, message, session_right)
    if verify_ok:
        logger.info("    ✅ 消息验证成功：发送的消息出现在聊天记录中")
    else:
        logger.warning("    ⚠️ 消息验证失败：未在聊天记录中找到发送的消息")
        logger.info("    （可能消息已发送但 OCR 未能识别，或消息位置在可视区域外）")
        return False

    logger.info("\n" + "=" * 60)
    logger.info("  阶段三完成")
    logger.info("=" * 60)
    return True


def verify_message_sent(image, message, session_right):
    """用 OCR 验证消息是否出现在聊天记录中。

    在聊天区域（session_right 右侧）识别文字，检查是否包含发送的消息内容。

    Args:
        image: 发送后的微信窗口截图
        message: 发送的消息内容
        session_right: 会话列表右边界（聊天区域起始 x）

    Returns:
        bool: 是否找到发送的消息
    """
    try:
        _project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        if _project_root not in sys.path:
            sys.path.insert(0, _project_root)
        from engine.importers.ocr_engine import ocr_image_array

        # 裁剪聊天区域（避免会话列表干扰）
        h, w = image.shape[:2]
        if session_right > 0 and session_right < w:
            chat_region = image[:, session_right:]
        else:
            chat_region = image

        # OCR 识别
        results = ocr_image_array(chat_region, use_cache=False)

        # 准备匹配：去除标点符号，只保留中英文和数字
        # 原因：OCR 识别结果常丢失下划线、+、_ 等标点，导致完全匹配失败
        def _normalize_text(text):
            text = text.replace(' ', '').replace('\n', '')
            # 去除所有标点符号（保留中英文、数字）
            return re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9]', '', text)

        message_clean = _normalize_text(message)

        # 检查是否包含发送的消息
        for r in results:
            text_clean = _normalize_text(r.text)
            # 完全匹配或消息内容包含在 OCR 文字中
            if text_clean == message_clean or message_clean in text_clean:
                logger.info(f"    [OCR] 找到匹配: {r.text!r} (center=({r.center_x + session_right}, {r.center_y}), conf={r.confidence:.3f})")
                return True

        # 如果消息较长，分段匹配（OCR 可能只识别到部分）
        if len(message_clean) > 10:
            # 取消息中间一段作为匹配特征
            mid = len(message_clean) // 2
            segment = message_clean[max(0, mid-5):mid+5]
            if len(segment) >= 4:
                for r in results:
                    text_clean = _normalize_text(r.text)
                    if segment in text_clean:
                        logger.info(f"    [OCR] 分段匹配: {r.text!r} 包含 {segment!r}")
                        return True

        logger.info(f"    [OCR] 未找到匹配的消息（共识别 {len(results)} 条文字）")
        return False

    except Exception as e:
        logger.info(f"    [OCR] 验证异常: {e}")
        return False


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # 命令行参数：无参数=只检测（输入测试文本但不发送），有参数=检测+发送
    if len(sys.argv) >= 2:
        message = sys.argv[1]
        do_send = True
    else:
        message = "测试消息"  # 只检测模式用的测试文本
        do_send = False

    run_send_message(message, do_send=do_send)


if __name__ == "__main__":
    main()
