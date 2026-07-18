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
from dynamic_detector import WeChatLayoutDetector  # noqa: E402
from test_current_wechat import find_wechat_window, screencap_window  # noqa: E402
from click_search_and_input import (  # noqa: E402
    get_client_offset,
    client_to_screen,
    physical_click,
    input_text_via_clipboard,
    safe_set_foreground_window,
)

user32 = ctypes.windll.user32

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")

# 微信发送按钮颜色（用户澄清：RGB(0, 195, 117) = BGR(117, 195, 0)）
SEND_BTN_BGR = (117, 195, 0)  # 用 tuple 避免 uint8 溢出
SEND_BTN_TOLERANCE = 30

# 输入框位置：距底部 80px（输入框中心的大概位置）
INPUT_BOX_OFFSET_FROM_BOTTOM = 80


def find_largest_wechat_window():
    """找到最大的微信窗口（避免找到托盘图标等小窗口）"""
    candidates = []

    def enum_proc(hwnd, lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd) + 1
        if length <= 1:
            return True
        buf = ctypes.create_unicode_buffer(length)
        user32.GetWindowTextW(hwnd, buf, length)
        title = buf.value
        cls_buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls_buf, 256)
        cls_name = cls_buf.value
        if "微信" in title or "WeChat" in cls_name or "WeChatMainWnd" in cls_name:
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            w = rect.right - rect.left
            h = rect.bottom - rect.top
            candidates.append({
                "hwnd": hwnd,
                "title": title,
                "class": cls_name,
                "width": w,
                "height": h,
                "left": rect.left,
                "top": rect.top,
            })
        return True

    callback = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)(enum_proc)
    user32.EnumWindows(callback, 0)

    if not candidates:
        return None

    # 按面积排序，选最大的
    candidates.sort(key=lambda c: c["width"] * c["height"], reverse=True)
    print(f"找到 {len(candidates)} 个微信窗口候选:")
    for i, c in enumerate(candidates):
        print(f"  {i+1}. 标题: '{c['title']}', 类名: '{c['class']}', "
              f"尺寸: {c['width']}x{c['height']}")

    return candidates[0]


def find_send_button_by_ocr(image):
    """用 OCR 识别"发送"文字定位发送按钮。

    Args:
        image: 微信窗口截图（BGR numpy 数组）

    Returns:
        tuple: (center_x, center_y, marked_image) 或 (None, None, image)
    """
    marked = image.copy()

    try:
        # 确保项目根目录在 sys.path 中
        _project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        if _project_root not in sys.path:
            sys.path.insert(0, _project_root)
        from engine.importers.ocr_engine import ocr_image_array

        results = ocr_image_array(image, use_cache=False)

        for r in results:
            # 匹配规则：文字长度至多4字符且包含"发送"
            if '发送' in r.text and len(r.text) <= 4:
                cx, cy = r.center_x, r.center_y
                print(f"    ✅ OCR 识别到'{r.text}' center=({cx}, {cy}) conf={r.confidence:.3f}")
                # 在图上标注
                pts = [(int(p[0]), int(p[1])) for p in r.bbox]
                cv2.polylines(marked, [np.array(pts)], True, (0, 255, 0), 2)
                cv2.circle(marked, (cx, cy), 10, (0, 255, 0), 2)
                return cx, cy, marked

        print("    ⚠️ OCR 未识别到含'发送'的文字（≤4字符）")
    except Exception as e:
        print(f"    ⚠️ OCR 识别失败: {e}")

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
    print("=" * 60)
    if do_send:
        print(f"  阶段三：输入和发送消息  message={message!r}")
    else:
        print("  阶段三：只检测布局（输入测试文本但不发送）")
    print("=" * 60)

    # 1. 找微信窗口（选最大的，避免找到托盘图标等小窗口）
    window = find_largest_wechat_window()
    if not window:
        print("❌ 未找到微信窗口")
        return False
    hwnd = window["hwnd"]
    print(f"\n[1] 微信窗口: hwnd={hwnd} size={window['width']}x{window['height']}")

    # 检查窗口大小（避免找到托盘图标等小窗口）
    if window["width"] < 500 or window["height"] < 400:
        print(f"❌ 微信窗口太小 ({window['width']}x{window['height']})，可能不是主窗口")
        print("   请确认微信主窗口已打开并显示在屏幕上")
        return False

    # 2. 截图（发送前）
    print("\n[2] 截图（发送前）")
    img = screencap_window(hwnd)
    if img is None:
        print("❌ 截图失败")
        return False
    img_path = os.path.join(OUTPUT_DIR, "stage_3_before_send.png")
    cv2.imwrite(img_path, img)
    print(f"    截图: {img_path} ({img.shape[1]}x{img.shape[0]})")

    h, w = img.shape[:2]

    # 3. 检测聊天区域分界线
    print("\n[3] 检测聊天区域分界线")
    detector = WeChatLayoutDetector()
    nav_right, session_right = detector.detect(img)
    print(f"    nav_right={nav_right} session_right={session_right}")

    chat_x = session_right
    chat_w = w - session_right
    print(f"    聊天区域: x={chat_x} w={chat_w}")

    # 4. 计算输入框位置（聊天区域底部中心，距底部 80px）
    input_cx = chat_x + chat_w // 2
    input_cy = h - INPUT_BOX_OFFSET_FROM_BOTTOM
    print(f"\n[4] 输入框位置(截图坐标): ({input_cx}, {input_cy})")

    # 标注输入框位置
    input_vis = draw_input_box(img, input_cx, input_cy, session_right)
    input_vis_path = os.path.join(OUTPUT_DIR, "stage_3_input_box.png")
    cv2.imwrite(input_vis_path, input_vis)
    print(f"    输入框标注图: {input_vis_path}")

    # 5. 物理点击输入框
    print(f"\n[5] 物理点击输入框")
    offset_x, offset_y = get_client_offset(hwnd)
    client_x = input_cx - offset_x
    client_y = input_cy - offset_y
    screen_x, screen_y = client_to_screen(hwnd, client_x, client_y)
    print(f"    输入框屏幕坐标: ({screen_x}, {screen_y})")
    safe_set_foreground_window(hwnd)
    time.sleep(0.5)
    physical_click(screen_x, screen_y)
    time.sleep(0.8)

    # 6. 输入消息（此时发送按钮变绿）
    print(f"\n[6] 输入消息: {message!r}")
    input_text_via_clipboard(hwnd, message)
    time.sleep(0.8)

    # 7. 重新截图（此时发送按钮是绿色）
    print("\n[7] 重新截图（发送按钮应变绿）")
    img_after_input = screencap_window(hwnd)
    if img_after_input is None:
        print("❌ 重新截图失败")
        return False
    img_after_input_path = os.path.join(OUTPUT_DIR, "stage_3_after_input.png")
    cv2.imwrite(img_after_input_path, img_after_input)
    print(f"    截图: {img_after_input_path}")

    # 8. 用 OCR 识别"发送"文字定位发送按钮（优先），回退到绿色按钮检测
    print("\n[8] 定位发送按钮（OCR 优先）")
    send_cx, send_cy, send_debug = find_send_button_by_ocr(img_after_input)

    if send_cx is None:
        print("    OCR 未找到，回退到绿色按钮检测...")
        send_cx, send_cy, send_debug = find_send_button_from_bottom_right(
            img_after_input, session_right
        )

    send_debug_path = os.path.join(OUTPUT_DIR, "stage_3_send_button.png")
    cv2.imwrite(send_debug_path, send_debug)
    print(f"    发送按钮检测图: {send_debug_path}")

    if send_cx is None:
        print("    ❌ 未找到发送按钮")
        print("    可能原因：消息未输入成功，或发送按钮位置不在右下角 1/3 区域")
        return False

    print(f"    ✅ 找到发送按钮: ({send_cx}, {send_cy})")

    if not do_send:
        print("\n[只检测模式] 已找到发送按钮，未点击发送")
        return True

    # 9. 物理点击发送按钮
    print(f"\n[9] 物理点击发送按钮 ({send_cx}, {send_cy})")
    client_x = send_cx - offset_x
    client_y = send_cy - offset_y
    screen_x, screen_y = client_to_screen(hwnd, client_x, client_y)
    print(f"    发送按钮屏幕坐标: ({screen_x}, {screen_y})")
    physical_click(screen_x, screen_y)
    time.sleep(1.5)

    # 10. 截图验证 + OCR 确认消息已发送
    print("\n[10] 截图验证（发送后）")
    after_img = screencap_window(hwnd)
    if after_img is None:
        print("❌ 发送后截图失败")
        return False
    after_path = os.path.join(OUTPUT_DIR, "stage_3_after_send.png")
    cv2.imwrite(after_path, after_img)
    print(f"    发送后截图: {after_path}")

    # 11. OCR 验证：确认消息出现在聊天记录中
    print("\n[11] OCR 验证消息是否出现在聊天记录")
    verify_ok = verify_message_sent(after_img, message, session_right)
    if verify_ok:
        print("    ✅ 消息验证成功：发送的消息出现在聊天记录中")
    else:
        print("    ⚠️ 消息验证失败：未在聊天记录中找到发送的消息")
        print("    （可能消息已发送但 OCR 未能识别，或消息位置在可视区域外）")
        # 不 return False，因为消息可能已发送只是 OCR 没识别到
        # 保留警告让调用方判断

    print("\n" + "=" * 60)
    print("  阶段三完成")
    print("=" * 60)
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

        # 准备匹配：去掉空格和换行，提高匹配容错
        message_clean = message.replace(' ', '').replace('\n', '')

        # 检查是否包含发送的消息
        for r in results:
            text_clean = r.text.replace(' ', '').replace('\n', '')
            # 完全匹配或消息内容包含在 OCR 文字中
            if text_clean == message_clean or message_clean in text_clean or text_clean in message_clean:
                print(f"    [OCR] 找到匹配: {r.text!r} (center=({r.center_x + session_right}, {r.center_y}), conf={r.confidence:.3f})")
                return True

        # 如果消息较长，分段匹配（OCR 可能只识别到部分）
        if len(message_clean) > 10:
            # 取消息中间一段作为匹配特征
            mid = len(message_clean) // 2
            segment = message_clean[max(0, mid-5):mid+5]
            if len(segment) >= 4:
                for r in results:
                    text_clean = r.text.replace(' ', '').replace('\n', '')
                    if segment in text_clean:
                        print(f"    [OCR] 分段匹配: {r.text!r} 包含 {segment!r}")
                        return True

        print(f"    [OCR] 未找到匹配的消息（共识别 {len(results)} 条文字）")
        return False

    except Exception as e:
        print(f"    [OCR] 验证异常: {e}")
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
