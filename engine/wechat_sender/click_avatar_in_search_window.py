"""
在搜索候选框窗口内匹配 [REDACTED] 头像并点击（含重试机制）。

优化点（按 talk.md）：
1. 等待间隔从 2.0s 改为 1.0s
2. 失败时自动重试，最多 3 次（总共最多 4 次执行）
3. 重试前把鼠标移动到搜索候选框中心，滚动滑轮几下，再点击

流程（单次尝试）：
1. 找微信主窗口
2. PrintWindow 截图主窗口，检测搜索栏位置
3. 物理点击搜索栏 + 输入 [REDACTED]
4. 等待 1 秒（搜索候选框出现）
5. 枚举窗口，找搜索候选框（标题 'Weixin' + 类名含 'ToolSaveBits'）
6. PrintWindow 截图搜索候选框
7. 多尺度匹配 [REDACTED].jpg
8. 点击头像
9. 等待 1 秒后截图主窗口，验证绿色环
10. 检查窗口数

如果绿色环验证失败，执行重试预备动作（移动鼠标到候选框中心+滚动滑轮+点击），
然后重新尝试整个流程，最多重试 3 次。

用法：
    # 匹配 + 点击 + 验证（含重试）
    python examples/wechat_auto/click_avatar_in_search_window.py --click

    # 只匹配，不点击（单次执行）
    python examples/wechat_auto/click_avatar_in_search_window.py
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
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dynamic_detector import WeChatLayoutDetector  # noqa: E402
from test_current_wechat import find_wechat_window, screencap_window  # noqa: E402
from wechat_window_utils import (  # noqa: E402  统一窗口枚举
    find_search_candidate_window,
    find_search_candidate_windows,
    count_wechat_windows,
    close_unexpected_wechat_windows,
)
from click_search_and_input import (  # noqa: E402
    get_client_offset,
    client_to_screen,
    physical_click,
    input_text_via_clipboard,
    safe_set_foreground_window,
)

user32 = ctypes.windll.user32

# 头像模板目录：data/avatars/（项目级共享）
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TEMPLATE_PATH = os.path.join(_PROJECT_ROOT, "data", "avatars", "[REDACTED].jpg")
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")
CONTACT_NAME = "[REDACTED]"

# 修复 P1-1/P1-3：从 config.py 导入统一配置，删除重复定义
from config import (
    MATCH_THRESHOLD,
    TEMPLATE_SCALES,
    NMS_MIN_DIST,
    GREEN_RING_BGR,
    GREEN_RING_TOLERANCE,
)

from logger import get_logger  # noqa: E402
logger = get_logger(__name__)

# 重试参数（按 talk.md：失败可以重试，最多重试 3 次）
MAX_RETRIES = 3
MAX_ATTEMPTS = MAX_RETRIES + 1  # 初次 + 3 次重试 = 4 次

# 鼠标事件常量
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_WHEEL = 0x0800
WHEEL_DELTA = 120


def find_search_bar_in_image(image):
    """在主窗口截图中检测搜索栏位置。

    优先使用 OCR 识别"搜索"文字精确定位，失败时回退到布局检测+固定比例。
    OCR 匹配规则：文字长度至多4字符且包含"搜索"。
    结合白色判定（布局检测）和 OCR 两个位置，取更可靠的结果。
    """
    h, w = image.shape[:2]

    # 方法1: OCR 识别"搜索"文字（最精确）
    ocr_search_x = None
    ocr_search_y = None
    try:
        from engine.importers.ocr_engine import ocr_image_array

        results = ocr_image_array(image, use_cache=False)

        for r in results:
            # 匹配规则：文字长度至多4字符且包含"搜索"
            if '搜索' in r.text and len(r.text) <= 4:
                logger.info(f"    ✅ OCR 识别到'{r.text}' center=({r.center_x}, {r.center_y}) conf={r.confidence:.3f}")
                ocr_search_x = r.center_x
                ocr_search_y = r.center_y
                break

        if ocr_search_x is None:
            logger.warning("    ⚠️ OCR 未识别到含'搜索'的文字（≤4字符），回退到布局检测")
    except Exception as e:
        logger.warning(f"    ⚠️ OCR 识别失败: {e}，回退到布局检测")

    # 方法2: 布局检测（白色判定）
    detector = WeChatLayoutDetector()
    nav_right, session_right = detector.detect(image)
    # 放宽异常判定阈值：dynamic_detector 的 nav_right=84（微信默认导航栏宽度）是合理值
    # 旧条件 nav_right < 100 会误判 84 为异常，导致覆盖为固定比例值 47（错误）
    # 新条件：只在检测完全失效时（nav_right 极小或 session_right 极小或顺序反了）才判异常
    layout_valid = not (nav_right < 30 or session_right < 150 or session_right <= nav_right)

    layout_search_x = None
    layout_search_y = None
    if layout_valid:
        layout_search_x = (nav_right + session_right) // 2
        session_region = image[:, nav_right:session_right]
        gray = cv2.cvtColor(session_region, cv2.COLOR_BGR2GRAY)
        row_brightness = np.mean(gray, axis=1)
        search_top = 0
        search_bottom = int(h * 0.3)
        layout_search_y = search_top + int(np.argmax(row_brightness[search_top:search_bottom]))
        logger.info(f"    [布局检测] 搜索栏位置: ({layout_search_x}, {layout_search_y}) nav_right={nav_right} session_right={session_right}")
    else:
        logger.warning(f"    ⚠️ 布局检测结果异常 (nav_right={nav_right}, session_right={session_right})")

    # 方法3: 固定比例回退（布局检测失败时）
    if not layout_valid:
        layout_search_x = int(w * 0.075)
        layout_search_y = int(h * 0.05)
        # 不覆盖 nav_right/session_right，保留 dynamic_detector 的原始值
        # （调用方依赖这俩值计算中间栏点击区域，覆盖会导致点击位置偏移）
        logger.info(f"    [固定比例] 搜索栏位置: ({layout_search_x}, {layout_search_y})")
        logger.info(f"    [保留] nav_right={nav_right}, session_right={session_right}（dynamic_detector 原始值）")

    # 综合判定：优先用 OCR，但结合布局检测验证
    if ocr_search_x is not None:
        # OCR 成功，验证位置合理性（应该在窗口左上区域）
        if ocr_search_x < w * 0.3 and ocr_search_y < h * 0.15:
            logger.info(f"    🎯 综合判定: 使用 OCR 位置 ({ocr_search_x}, {ocr_search_y})")
            # 用 OCR 的 y，布局检测的 x 范围（更稳健）
            if layout_valid:
                final_x = (nav_right + session_right) // 2
                final_y = ocr_search_y
                # 如果 OCR 和布局检测的 x 差距不大，用布局检测的 x（更居中）
                if abs(final_x - ocr_search_x) < 50:
                    logger.info(f"    [融合] OCR x={ocr_search_x} 与布局 x={final_x} 接近，用布局 x（更居中）")
                else:
                    final_x = ocr_search_x
            else:
                final_x = ocr_search_x
                final_y = ocr_search_y
            return final_x, final_y, nav_right, session_right
        else:
            logger.warning(f"    ⚠️ OCR 位置 ({ocr_search_x}, {ocr_search_y}) 不在合理范围，用布局检测")

    # 回退到布局检测/固定比例
    return layout_search_x, layout_search_y, nav_right, session_right


def verify_main_window_layout(image, strict=True):
    """验证主窗口截图的布局是否正常（三个区域分界线可检测）。

    用户反馈：代码有时操作的是"网络搜索窗口"而非真正的主窗口。
    通过检测三个区域（导航栏、会话列表、聊天区域）的分界线，
    可以确认截图确实来自主窗口。

    合理布局参考（来自正常微信主窗口）：
    - nav_right 在 [50, 200] 范围内（导航栏宽度）
    - session_right > nav_right + 100（中间栏至少 100px 宽）
    - session_right < width - 200（聊天区域至少 200px 宽）
    - nav_right < session_right（顺序正确）

    Args:
        image: 主窗口截图（BGR）
        strict: True=严格模式（任一条件不满足就判失败），
                False=宽松模式（只检查极端异常）

    Returns:
        tuple (is_valid: bool, layout_info: dict)
        - is_valid: 主窗口布局是否正常
        - layout_info: {
            "nav_right": int, "session_right": int,
            "width": int, "height": int,
            "reason": str  # 失败原因（is_valid=False 时有值）
          }
    """
    h, w = image.shape[:2]
    detector = WeChatLayoutDetector()
    nav_right, session_right = detector.detect(image)

    info = {
        "nav_right": nav_right,
        "session_right": session_right,
        "width": w,
        "height": h,
        "reason": "",
    }

    # 检查 1：nav_right 在合理范围
    if not (50 <= nav_right <= 200):
        info["reason"] = f"nav_right={nav_right} 不在合理范围 [50, 200]"
        return False, info

    # 检查 2：session_right > nav_right + 100（中间栏至少 100px 宽）
    if session_right <= nav_right + 100:
        info["reason"] = (
            f"session_right={session_right} <= nav_right+100={nav_right + 100}，"
            f"中间栏宽度不足"
        )
        return False, info

    # 检查 3：session_right < width - 200（聊天区域至少 200px 宽）
    if session_right >= w - 200:
        info["reason"] = (
            f"session_right={session_right} >= width-200={w - 200}，"
            f"聊天区域宽度不足"
        )
        return False, info

    # 检查 4（严格模式）：nav_right < session_right（顺序正确）
    if strict and nav_right >= session_right:
        info["reason"] = (
            f"nav_right={nav_right} >= session_right={session_right}，"
            f"分界线顺序异常"
        )
        return False, info

    return True, info


def find_template_multiscale(scene, template_path, scales, threshold, nms_min_dist):
    """多尺度模板匹配"""
    template = cv2.cvtColor(np.array(Image.open(template_path)), cv2.COLOR_RGB2BGR)
    sh, sw = scene.shape[:2]
    all_points = []
    best_score = -1.0

    for scale in scales:
        th = tw = int(scale)
        if th >= sh or tw >= sw:
            continue
        scaled = cv2.resize(template, (tw, th), interpolation=cv2.INTER_AREA)
        result = cv2.matchTemplate(scene, scaled, cv2.TM_CCOEFF_NORMED)
        ys, xs = np.where(result >= threshold)
        for x, y in zip(xs, ys):
            score = float(result[y, x])
            cx = int(x + tw // 2)
            cy = int(y + th // 2)
            all_points.append((cx, cy, score, scale))
            if score > best_score:
                best_score = score

    all_points = nms_points(all_points, nms_min_dist)
    all_points = sorted(all_points, key=lambda p: (p[1], p[0]))
    return all_points, best_score


def nms_points(points, min_dist):
    if not points:
        return []
    points = sorted(points, key=lambda p: -p[2])
    kept = []
    for p in points:
        x, y, _, _ = p
        too_close = False
        for kx, ky, _, _ in kept:
            if (x - kx) ** 2 + (y - ky) ** 2 < min_dist ** 2:
                too_close = True
                break
        if not too_close:
            kept.append(p)
    return kept


def find_search_box_in_candidate(image):
    """在搜索候选框截图中检测搜索框位置（顶部最亮的区域）"""
    h, w = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    row_brightness = np.mean(gray, axis=1)
    search_top = 0
    search_bottom = int(h * 0.2)
    search_y = search_top + int(np.argmax(row_brightness[search_top:search_bottom]))
    search_x = w // 2
    return search_x, search_y


def draw_match_result(image, points, target, search_x, search_y):
    out = image.copy()
    font = cv2.FONT_HERSHEY_SIMPLEX
    cv2.line(out, (search_x - 20, search_y), (search_x + 20, search_y), (0, 255, 255), 2)
    cv2.line(out, (search_x, search_y - 20), (search_x, search_y + 20), (0, 255, 255), 2)
    cv2.putText(out, "SEARCH_BOX", (search_x + 25, search_y + 5),
                font, 0.5, (0, 255, 255), 1, cv2.LINE_AA)
    for i, (cx, cy, score, scale) in enumerate(points):
        half = scale // 2
        cv2.rectangle(out, (cx - half, cy - half),
                      (cx + half, cy + half), (0, 255, 0), 2)
        cv2.putText(out, f"#{i} {score:.2f} s={scale}",
                    (cx - half, max(0, cy - half - 8)),
                    font, 0.5, (0, 255, 0), 1, cv2.LINE_AA)
    if target is not None:
        tx, ty, tscore, tscale = target
        half = tscale // 2
        cv2.rectangle(out, (tx - half, ty - half),
                      (tx + half, ty + half), (0, 0, 255), 3)
        cv2.line(out, (tx - 25, ty), (tx + 25, ty), (0, 0, 255), 3)
        cv2.line(out, (tx, ty - 25), (tx, ty + 25), (0, 0, 255), 3)
        cv2.putText(out, f"CLICK ({tx},{ty}) {tscore:.3f}",
                    (tx + 30, ty + 8), font, 0.7, (0, 0, 255), 2, cv2.LINE_AA)
    return out


def find_green_ring(image, avatar_cx, avatar_cy, avatar_size,
                    target_bgr=GREEN_RING_BGR, tolerance=GREEN_RING_TOLERANCE,
                    min_ratio=0.4):
    """绿色环检测（以头像为中心，1.2 倍宽度方形区域）。

    双重验证：
    1. 绿色像素占比 >= min_ratio
    2. 霍夫圆变换检测到圆环形状（加分项，非必须）
    """
    h, w = image.shape[:2]
    outer_size = int(avatar_size * 1.2)
    inner_size = int(avatar_size)
    half_outer = outer_size // 2
    half_inner = inner_size // 2
    x1 = avatar_cx - half_outer
    y1 = avatar_cy - half_outer
    x2 = avatar_cx + half_outer
    y2 = avatar_cy + half_outer
    debug = image.copy()
    if x1 < 0 or y1 < 0 or x2 > w or y2 > h:
        cv2.putText(debug, "OUT_OF_BOUNDS", (avatar_cx - 60, avatar_cy),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        return False, 0.0, debug
    outer = image[y1:y2, x1:x2]
    mask = np.ones((outer_size, outer_size), dtype=np.uint8) * 255
    inner_x1 = half_outer - half_inner
    inner_y1 = half_outer - half_inner
    inner_x2 = half_outer + half_inner
    inner_y2 = half_outer + half_inner
    mask[inner_y1:inner_y2, inner_x1:inner_x2] = 0
    lower = np.array([max(0, c - tolerance) for c in target_bgr], dtype=np.uint8)
    upper = np.array([min(255, c + tolerance) for c in target_bgr], dtype=np.uint8)
    green_mask_full = cv2.inRange(outer, lower, upper)
    green_mask = cv2.bitwise_and(green_mask_full, mask)
    ring_total = int(np.count_nonzero(mask))
    green_pixels = int(np.count_nonzero(green_mask))
    green_ratio = green_pixels / ring_total if ring_total > 0 else 0.0

    # 霍夫圆变换验证形状（加分项）
    # 将绿色掩码转为灰度图用于霍夫圆检测
    circles_found = False
    try:
        # 高斯模糊降低噪声
        green_blur = cv2.GaussianBlur(green_mask, (5, 5), 0)
        # 霍夫圆检测：半径范围 [inner_size//2 - 5, outer_size//2 + 5]
        min_radius = max(inner_size // 2 - 5, 5)
        max_radius = outer_size // 2 + 5
        circles = cv2.HoughCircles(
            green_blur, cv2.HOUGH_GRADIENT, dp=1, minDist=outer_size,
            param1=50, param2=15,
            minRadius=min_radius, maxRadius=max_radius,
        )
        if circles is not None:
            # 检查是否有圆心在头像附近
            for c in circles[0]:
                cx_local, cy_local, r = int(c[0]), int(c[1]), int(c[2])
                dist_to_center = ((cx_local - half_outer) ** 2 + (cy_local - half_outer) ** 2) ** 0.5
                if dist_to_center < outer_size * 0.3:  # 圆心在头像附近
                    circles_found = True
                    cv2.circle(debug, (x1 + cx_local, y1 + cy_local), r, (255, 0, 0), 2)
                    cv2.circle(debug, (x1 + cx_local, y1 + cy_local), 2, (255, 0, 0), 3)
                    break
    except Exception:
        pass  # 霍夫圆失败不影响主判断

    mask_bgr = np.zeros_like(outer)
    mask_bgr[green_mask > 0] = (0, 0, 255)
    debug[y1:y2, x1:x2] = cv2.addWeighted(outer, 0.7, mask_bgr, 0.3, 0)
    cv2.rectangle(debug, (x1, y1), (x2, y2), (0, 255, 255), 2)
    cv2.rectangle(debug, (avatar_cx - half_inner, avatar_cy - half_inner),
                  (avatar_cx + half_inner, avatar_cy + half_inner),
                  (255, 0, 255), 2)
    # 显示双重验证结果
    shape_info = "+圆" if circles_found else ""
    cv2.putText(debug, f"ratio={green_ratio:.3f}{shape_info} ({green_pixels}/{ring_total})",
                (x1, max(0, y1 - 8)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2, cv2.LINE_AA)

    # 判定（修复 P0-5：实现真正的双重验证，原代码 circles_found 是死代码）
    # - 占比 ≥ 0.5：高置信，直接通过
    # - 占比 ≥ 0.35 且检测到圆：中等置信，霍夫圆补充验证
    # - 其他：不通过
    high_ratio = 0.5
    mid_ratio = 0.35
    if green_ratio >= high_ratio:
        passed = True
    elif green_ratio >= mid_ratio and circles_found:
        passed = True
    else:
        passed = False
    return passed, green_ratio, debug


def scroll_in_main_middle_column():
    """重试前预备动作（按 talk.md 协议澄清版）：
    在微信主窗口的中间栏（nav_right 和 session_right 之间）滑动滑轮几下，再点击一下。

    用户澄清：
    - 滑动是在微信主界面的中间栏（不是搜索候选框）
    - 失败后搜索候选框一定不存在，重试时重新从点击搜索栏开始

    流程：
    1. PrintWindow 截图主窗口，检测分界线
    2. 计算中间栏中心
    3. 移动鼠标到中间栏中心
    4. 滚动滑轮 3 下向下（让会话列表滚动刷新）
    5. 点击中间栏中心（让主窗口激活/获取焦点）
    """
    window = find_wechat_window()
    if not window:
        logger.info("    [重试预备] 未找到微信主窗口，跳过滚动")
        return False

    hwnd_main = window["hwnd"]
    logger.info(f"    [重试预备] 微信主窗口: hwnd={hwnd_main}")

    # 截图主窗口，检测分界线
    img = screencap_window(hwnd_main)
    if img is None:
        logger.info("    [重试预备] 主窗口截图失败，跳过滚动")
        return False

    h, w = img.shape[:2]
    detector = WeChatLayoutDetector()
    nav_right, session_right = detector.detect(img)
    logger.info(f"    [重试预备] 分界线: nav_right={nav_right} session_right={session_right}")

    # 中间栏中心（截图坐标系）
    middle_x = (nav_right + session_right) // 2
    middle_y = h // 2
    logger.info(f"    [重试预备] 中间栏中心(截图坐标): ({middle_x}, {middle_y})")

    # 转屏幕坐标
    offset_x, offset_y = get_client_offset(hwnd_main)
    client_x = middle_x - offset_x
    client_y = middle_y - offset_y
    screen_x, screen_y = client_to_screen(hwnd_main, client_x, client_y)
    logger.info(f"    [重试预备] 中间栏中心(屏幕坐标): ({screen_x}, {screen_y})")

    # 1. 移动鼠标到中间栏中心
    user32.SetCursorPos(screen_x, screen_y)
    time.sleep(0.3)

    # 2. 滚动滑轮 3 下向下（让会话列表滚动刷新）
    logger.info("    [重试预备] 滚动滑轮 3 下（向下）...")
    for _ in range(3):
        user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, WHEEL_DELTA, 0)
        time.sleep(0.15)

    # 3. 点击中间栏中心（让主窗口激活）
    logger.info(f"    [重试预备] 点击中间栏中心 ({screen_x}, {screen_y})")
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.05)
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    time.sleep(0.5)

    return True


def run_one_attempt(attempt_idx, max_attempts, do_click,
                    contact_name=CONTACT_NAME, template_path=TEMPLATE_PATH):
    """执行一次完整流程，返回 (success: bool, target: tuple|None, count_after: int)

    Args:
        contact_name: 联系人昵称（用于搜索栏输入），默认 CONTACT_NAME
        template_path: 联系人头像模板路径，默认 TEMPLATE_PATH
    """
    # 修复 VK_CONTROL 作用域：在函数顶部统一定义，避免 if/else 分支作用域冲突
    # （原 if 分支内局部赋值会导致 Python 将整个函数的 VK_CONTROL 视为局部变量，
    #  else 分支使用时触发 "cannot access local variable" 错误）
    VK_CONTROL = 0x11

    logger.info(f"\n{'=' * 20} 第 {attempt_idx}/{max_attempts} 次尝试 {'=' * 20}")

    # ========== 阶段 A：点击前窗口数 + 健壮性清理 + 主窗口布局验证 ==========
    count_before, wins_before = count_wechat_windows()
    logger.info(f"\n[A] 点击前微信窗口数: {count_before}")
    for w in wins_before:
        logger.info(f"    - hwnd={w['hwnd']} title={w['title']!r} class={w['class']!r}")
    if count_before == 0:
        logger.error("❌ 微信窗口未打开")
        return False, None, 0

    # 健壮性增强（用户反馈）：
    # 1. 关闭意外窗口（如"搜索网络结果"窗口、Chrome_WidgetWin_0 内嵌浏览器窗口）
    # 2. 关闭搜索候选框（如果存在，避免重试时累加操作到搜索框）
    # 3. 将微信主程序重新置顶（执行操作时微信主窗口必须位于顶端）
    # 4. 验证主窗口布局正常（三个区域分界线可检测）
    # 触发场景：
    #   - 上次点击位置错误 → 弹出"搜索网络结果"窗口 → 后续操作在错误窗口里进行
    #   - 上次匹配失败但搜索候选框还在 → 重试时累加操作到搜索框

    # 步骤 1：关闭意外窗口
    try:
        closed_count, closed_wins = close_unexpected_wechat_windows()
        if closed_count > 0:
            logger.warning(
                f"    ⚠️ [健壮性] 检测到 {closed_count} 个意外微信窗口，已关闭："
            )
            for cw in closed_wins:
                logger.warning(
                    f"      - hwnd={cw['hwnd']} title={cw['title']!r} class={cw['class']!r}"
                )
            time.sleep(0.5)
            count_before, wins_before = count_wechat_windows()
            logger.info(f"    [健壮性] 关闭意外窗口后，微信窗口数: {count_before}")
            if count_before == 0:
                logger.error("❌ 关闭意外窗口后微信主窗口也消失了")
                return False, None, 0
    except Exception as e:
        logger.warning(f"    ⚠️ [健壮性] 关闭意外窗口异常: {e}（继续执行）")

    # 步骤 2：关闭搜索候选框（避免重试时累加操作到搜索框）
    try:
        from wechat_window_utils import find_search_candidate_windows
        search_candidates = find_search_candidate_windows()
        if search_candidates:
            logger.info(
                f"    [健壮性] 检测到 {len(search_candidates)} 个搜索候选框，关闭它们避免重试累加操作"
            )
            WM_CLOSE = 0x0010
            for sc in search_candidates:
                user32.PostMessageW(sc["hwnd"], WM_CLOSE, 0, 0)
                logger.info(
                    f"      - 关闭搜索候选框 hwnd={sc['hwnd']}"
                )
            time.sleep(0.5)
    except Exception as e:
        logger.warning(f"    ⚠️ [健壮性] 关闭搜索候选框异常: {e}（继续执行）")

    # 步骤 3：确保微信主窗口在前台
    try:
        main_win = find_wechat_window()
        if main_win:
            fg_ok_a = safe_set_foreground_window(main_win["hwnd"])
            if fg_ok_a:
                logger.info(f"    [健壮性] 微信主窗口已置顶 (hwnd={main_win['hwnd']})")
                time.sleep(0.5)
            else:
                logger.warning(f"    ⚠️ [健壮性] 微信主窗口置顶失败，继续执行")
    except Exception as e:
        logger.warning(f"    ⚠️ [健壮性] 主窗口置顶异常: {e}（继续执行）")

    # 步骤 4：验证主窗口布局（三个区域分界线可检测）
    # 用户反馈：代码有时操作的是"网络搜索窗口"而非真正的主窗口
    try:
        main_win_verify = find_wechat_window()
        if main_win_verify:
            verify_img = screencap_window(main_win_verify["hwnd"])
            if verify_img is not None:
                layout_ok, layout_info = verify_main_window_layout(verify_img, strict=True)
                if layout_ok:
                    logger.info(
                        f"    [健壮性] 主窗口布局验证通过 "
                        f"(nav_right={layout_info['nav_right']}, "
                        f"session_right={layout_info['session_right']}, "
                        f"size={layout_info['width']}x{layout_info['height']})"
                    )
                else:
                    logger.error(
                        f"    ❌ [健壮性] 主窗口布局验证失败：{layout_info['reason']}"
                    )
                    logger.error(
                        f"    可能操作的不是真正的主窗口（如网络搜索窗口），"
                        f"本次尝试判失败"
                    )
                    return False, None, 0
    except Exception as e:
        logger.warning(f"    ⚠️ [健壮性] 主窗口布局验证异常: {e}（继续执行）")

    # ========== 阶段 B：主窗口截图 + 点击搜索栏 + 输入 ==========
    logger.info(f"\n[B] 主窗口截图 + 点击搜索栏 + 输入 {contact_name}")
    window = find_wechat_window()
    if not window:
        logger.error("❌ find_wechat_window 返回 None")
        return False, None, 0
    hwnd_main = window["hwnd"]
    logger.info(f"    主窗口: hwnd={hwnd_main} size={window['width']}x{window['height']}")

    # 关键修复：截图前先把微信设为前台，确保 PrintWindow 截到最新内容
    # 否则微信在后台时截图可能是旧内容，导致布局检测失败
    safe_set_foreground_window(hwnd_main)
    # 等待窗口完全渲染（窗口刚恢复时内容可能需要时间渲染）
    time.sleep(1.5)

    pw_image = screencap_window(hwnd_main)
    if pw_image is None:
        logger.error("❌ 主窗口截图失败")
        return False, None, 0
    pw_path = os.path.join(OUTPUT_DIR, f"stage_b_main_printwindow_{attempt_idx}.png")
    cv2.imwrite(pw_path, pw_image)
    logger.info(f"    主窗口截图: {pw_path}")

    pw_search_x, pw_search_y, nav_right, session_right = find_search_bar_in_image(pw_image)
    logger.info(f"    搜索栏位置(主窗口): ({pw_search_x}, {pw_search_y})")

    offset_x, offset_y = get_client_offset(hwnd_main)
    client_x = pw_search_x - offset_x
    client_y = pw_search_y - offset_y
    screen_x, screen_y = client_to_screen(hwnd_main, client_x, client_y)

    logger.info(f"    搜索栏屏幕坐标: ({screen_x}, {screen_y})")
    logger.info("    safe_set_foreground_window + 点击中间栏激活焦点 + Ctrl+F + 输入 ...")
    fg_ok = safe_set_foreground_window(hwnd_main)
    time.sleep(0.3)

    if not fg_ok:
        # SetForegroundWindow 失败，用 PostMessage 方式（不需要窗口在前台）
        logger.warning("    ⚠️ SetForegroundWindow 失败，改用 PostMessage 方式...")
        WM_LBUTTONDOWN = 0x0201
        WM_LBUTTONUP = 0x0202
        WM_KEYDOWN = 0x0100
        WM_KEYUP = 0x0101
        WM_CHAR = 0x0102
        MK_LBUTTON = 0x0001
        # VK_CONTROL 已在函数顶部统一定义（避免作用域冲突）
        VK_BACK = 0x08

        # 1. PostMessage 点击搜索栏（客户区坐标），激活搜索框
        click_lparam = (client_y << 16) | (client_x & 0xFFFF)
        user32.PostMessageW(hwnd_main, WM_LBUTTONDOWN, MK_LBUTTON, click_lparam)
        time.sleep(0.1)
        user32.PostMessageW(hwnd_main, WM_LBUTTONUP, 0, click_lparam)
        time.sleep(0.5)

        # 2. 清空搜索框（用 Backspace 删除，不用 Ctrl+A 因为 Qt 会把 A 当普通字符输入）
        for _ in range(50):  # 最多删除 50 个字符
            user32.PostMessageW(hwnd_main, WM_KEYDOWN, VK_BACK, 0)
            time.sleep(0.01)
            user32.PostMessageW(hwnd_main, WM_KEYUP, VK_BACK, 0)
            time.sleep(0.01)
        time.sleep(0.3)

        # 3. PostMessage 发送 WM_CHAR 逐字符输入（不用 Ctrl+F，避免 F 被当作普通字符输入）
        for ch in contact_name:
            user32.PostMessageW(hwnd_main, WM_CHAR, ord(ch), 0)
            time.sleep(0.05)
        time.sleep(0.5)

        logger.info(f"    已通过 PostMessage 输入: {contact_name}")

    else:
        # SetForegroundWindow 成功，用 Ctrl+F 快捷键打开搜索栏
        # 用户确认：Ctrl+F 可直接打开微信搜索栏，是最佳方案（不依赖精确点击位置）
        # 先点击主窗口中间栏70%区域内的随机位置，确保焦点在微信窗口上（Ctrl+F 依赖焦点）
        # 随机化避免每次点击同一位置（防检测），同时避开边缘 15%（不点导航栏/搜索栏/聊天区域边缘）
        # 用户反馈：40% 太窄，70% 合适（中间栏判定已修复，范围正确）
        # ⚠️ 严禁双击中间栏（会弹出对话框），只能用 physical_click 单击
        import random as _random
        h_img, w_img = pw_image.shape[:2]
        mid_col_width = session_right - nav_right
        # x: 中间栏70%区域（避开左右边缘各15%）
        mid_x = int(nav_right + mid_col_width * (0.15 + 0.7 * _random.random()))
        # y: 窗口高度70%区域（避开上下边缘各15%）
        mid_y = int(h_img * (0.15 + 0.7 * _random.random()))
        mid_screen_x, mid_screen_y = client_to_screen(
            hwnd_main, mid_x - offset_x, mid_y - offset_y
        )
        logger.info(f"    随机点击中间栏激活焦点: 客户区({mid_x},{mid_y}) 屏幕({mid_screen_x},{mid_screen_y})")
        physical_click(mid_screen_x, mid_screen_y)
        time.sleep(0.3)

        # 用 Ctrl+F 快捷键打开搜索栏（比点击更可靠，不依赖精确位置）
        # 已升级为 SendInput 带扫描码（通过 human_sim._press_key_combo）
        from human_sim import _press_key_combo, VK_CONTROL, VK_F
        _press_key_combo(VK_CONTROL, VK_F)
        time.sleep(0.8)

        # 输入联系人名
        input_text_via_clipboard(hwnd_main, contact_name)

    logger.info("    等待 1.0 秒，让搜索候选框出现...")
    time.sleep(1.0)

    # ========== 阶段 C：找搜索候选框窗口 ==========
    logger.info("\n[C] 查找搜索候选框窗口")
    candidates = find_search_candidate_windows()
    logger.info(f"    找到 {len(candidates)} 个搜索候选框窗口")
    if not candidates:
        logger.error("❌ 未找到搜索候选框窗口（标题 'Weixin' + 类名含 'ToolSaveBits'）")
        count_now, wins_now = count_wechat_windows()
        logger.info(f"    当前微信窗口数: {count_now}")
        for w in wins_now:
            logger.info(f"    - hwnd={w['hwnd']} title={w['title']!r} class={w['class']!r}")
        return False, None, 0

    for i, c in enumerate(candidates):
        logger.info(f"    #{i}: hwnd={c['hwnd']} title={c['title']!r} "
              f"class={c['class']!r} size=({c['width']},{c['height']}) "
              f"rect=({c['left']},{c['top']},{c['right']},{c['bottom']})")

    search_win = candidates[0]
    hwnd_search = search_win["hwnd"]
    logger.info(f"    选定搜索候选框: hwnd={hwnd_search}")

    # ========== 阶段 D：截图搜索候选框 + 匹配 ==========
    logger.info("\n[D] 截图搜索候选框 + 多尺度匹配")
    search_img = screencap_window(hwnd_search)
    if search_img is None:
        logger.error("❌ 搜索候选框截图失败")
        return False, None, 0
    search_img_path = os.path.join(OUTPUT_DIR, f"stage_d_search_candidate_{attempt_idx}.png")
    cv2.imwrite(search_img_path, search_img)
    logger.info(f"    搜索候选框截图: {search_img_path} "
          f"({search_img.shape[1]}x{search_img.shape[0]})")

    # OCR 验证候选框内容包含联系人名（防止误识别其他窗口）
    try:
        from engine.importers.ocr_engine import ocr_image_array
        ocr_results = ocr_image_array(search_img, use_cache=False)
        ocr_text_all = ''.join(r.text for r in ocr_results)
        # 去空格比较（OCR 可能多识别或少识别空格）
        contact_clean = contact_name.replace(' ', '')
        ocr_clean = ocr_text_all.replace(' ', '')
        if contact_clean in ocr_clean:
            logger.info(f"    ✅ [OCR] 候选框内容包含联系人名 '{contact_name}'")
        else:
            logger.warning(f"    ⚠️ [OCR] 候选框内容未包含联系人名 '{contact_name}'")
            logger.info(f"    [OCR] 识别到的文字: {ocr_text_all[:100]}")
            # 不 return False，因为 OCR 可能漏识别，继续用头像匹配验证
    except Exception as e:
        logger.warning(f"    ⚠️ [OCR] 候选框内容验证异常: {e}")

    s_box_x, s_box_y = find_search_box_in_candidate(search_img)
    logger.info(f"    搜索框位置(候选框内): ({s_box_x}, {s_box_y})")

    points, best_score = find_template_multiscale(
        search_img, template_path, TEMPLATE_SCALES, MATCH_THRESHOLD, NMS_MIN_DIST
    )

    if not points:
        logger.error(f"❌ 未找到匹配点 (最高置信度={best_score:.3f})")
        template = cv2.cvtColor(np.array(Image.open(template_path)), cv2.COLOR_RGB2BGR)
        logger.info("    各尺度最高置信度:")
        for s in TEMPLATE_SCALES:
            if s >= search_img.shape[0] or s >= search_img.shape[1]:
                continue
            scaled = cv2.resize(template, (s, s), interpolation=cv2.INTER_AREA)
            res = cv2.matchTemplate(search_img, scaled, cv2.TM_CCOEFF_NORMED)
            _, mx, _, ml = cv2.minMaxLoc(res)
            logger.info(f"    - {s}px: max={mx:.3f} at ({ml[0]+s//2}, {ml[1]+s//2})")
        return False, None, 0

    logger.info(f"    找到 {len(points)} 个匹配点:")
    for i, (x, y, s, sc) in enumerate(points):
        dist = ((x - s_box_x) ** 2 + (y - s_box_y) ** 2) ** 0.5
        logger.info(f"    #{i}: ({x}, {y}) conf={s:.3f} scale={sc}px "
              f"距搜索框={dist:.0f}px")

    # 改进：先按置信度筛选，再综合置信度和位置评分选择
    # 搜索候选框中头像应在搜索框下方，y 坐标 > s_box_y 的匹配点优先
    # 严格阈值：低于 MIN_CONFIDENCE_FOR_SELECTION(0.7) 一律不点击，直接判本次失败触发上层重试
    # （用户要求：匹配度低就不该点击，避免点错位置触发"搜索网络结果"等意外窗口）
    MIN_CONFIDENCE_FOR_SELECTION = 0.7
    high_conf_points = [p for p in points if p[2] >= MIN_CONFIDENCE_FOR_SELECTION]
    if not high_conf_points:
        # 严格判定本次失败，不点击，触发上层重试机制：
        # - 4 次失败后 _refresh_avatar_and_maybe_retry 强制刷新头像
        # - 头像变了才重试，仍失败则反馈给 agent
        logger.error(
            f"    ❌ 所有匹配点置信度 < {MIN_CONFIDENCE_FOR_SELECTION}，"
            f"严格判定本次失败（不点击，避免点错位置触发意外窗口）"
        )
        return False, None, 0

    # 用加权评分：confidence_score * 0.6 + position_score * 0.4
    # position_score：距搜索框越近、在搜索框下方，分数越高
    max_dist = max(((p[0] - s_box_x) ** 2 + (p[1] - s_box_y) ** 2) ** 0.5
                   for p in high_conf_points) or 1
    best_score_val = -1
    target = high_conf_points[0]
    for p in high_conf_points:
        x, y, conf, _ = p
        dist = ((x - s_box_x) ** 2 + (y - s_box_y) ** 2) ** 0.5
        # 位置分：距离归一化（越近越高），在搜索框下方加分
        dist_score = 1.0 - (dist / max_dist)
        below_bonus = 0.2 if y > s_box_y else 0.0  # 在搜索框下方加分
        position_score = min(1.0, dist_score + below_bonus)
        # 综合评分
        total_score = conf * 0.6 + position_score * 0.4
        logger.info(f"    #?: ({x},{y}) conf={conf:.3f} dist={dist:.0f} "
              f"pos_score={position_score:.3f} total={total_score:.3f}")
        if total_score > best_score_val:
            best_score_val = total_score
            target = p
    logger.info(f"    选中(综合评分最高): ({target[0]}, {target[1]}) "
          f"conf={target[2]:.3f} scale={target[3]}px score={best_score_val:.3f}")

    logger.info(f"    最终选择: ({target[0]}, {target[1]}) "
          f"conf={target[2]:.3f} scale={target[3]}px")
    # 注：find_template_multiscale 已经过滤 < MATCH_THRESHOLD 的点，
    # 且上面 high_conf_points 非空才走到这里，所以 target 的置信度一定 >= 0.7，
    # 不需要额外的"低置信度警告"分支（原代码在此处仍有警告但不 return False，已删除）。

    match_vis = draw_match_result(search_img, points, target, s_box_x, s_box_y)
    match_path = os.path.join(OUTPUT_DIR, f"stage_d_match_result_{attempt_idx}.png")
    cv2.imwrite(match_path, match_vis)
    logger.info(f"    匹配结果图: {match_path}")

    if not do_click:
        logger.info("\n[只匹配模式] 请检查匹配结果图，确认后用 --click 运行")
        return True, target, count_before

    # ========== 阶段 E：点击头像 ==========
    logger.info(f"\n[E] 点击头像 ({target[0]}, {target[1]})")
    client_origin_x, client_origin_y = client_to_screen(hwnd_search, 0, 0)
    # 修复 P1-2：wechat_window_utils 返回的字段是 left/top/right/bottom，不是 rect
    search_win_rect = (search_win['left'], search_win['top'], search_win['right'], search_win['bottom'])
    logger.info(f"    搜索候选框窗口 rect: {search_win_rect}")
    logger.info(f"    ClientToScreen(0, 0) = ({client_origin_x}, {client_origin_y})")
    logger.info(f"    偏移: dx={client_origin_x - search_win_rect[0]}, "
          f"dy={client_origin_y - search_win_rect[1]}")

    # 修复 P0-4：截图坐标需减去客户区偏移再传给 client_to_screen
    offset_x, offset_y = get_client_offset(hwnd_search)
    click_screen_x, click_screen_y = client_to_screen(hwnd_search, target[0] - offset_x, target[1] - offset_y)
    logger.info(f"    点击屏幕坐标: ({click_screen_x}, {click_screen_y})")

    pre_click_img = screencap_window(hwnd_search)
    if pre_click_img is not None:
        pre_click_path = os.path.join(OUTPUT_DIR, f"stage_e_pre_click_{attempt_idx}.png")
        cv2.imwrite(pre_click_path, pre_click_img)
        logger.info(f"    点击前搜索候选框截图: {pre_click_path}")

    # 修复：直接用 human_physical_click 点击头像，不调用 safe_set_foreground_window。
    # 原因：safe_set_foreground_window 失败后会调用 click_taskbar_wechat（点击任务栏微信图标），
    #       这会激活微信主窗口并关闭搜索候选框，导致后续操作失败。
    # mouse_event 是全局的，点击会到达鼠标位置下的窗口，不需要窗口在前台。
    # 防封号：使用 human_physical_click，带 3px 随机抖动和随机点击间隔。
    logger.info(f"    物理点击头像 ({click_screen_x}, {click_screen_y}) ...")
    from human_sim import human_physical_click
    human_physical_click(click_screen_x, click_screen_y, jitter_radius=3)

    logger.info("    等待 1.0 秒，让聊天界面出现...")  # 优化点1：1.5s → 1.0s
    time.sleep(1.0)

    # ========== 阶段 F：验证绿色环 ==========
    logger.info("\n[F] 验证绿色环")
    post_img = screencap_window(hwnd_main)
    post_path = os.path.join(OUTPUT_DIR, f"stage_f_after_click_{attempt_idx}.png")
    cv2.imwrite(post_path, post_img)
    logger.info(f"    点击后主窗口截图: {post_path}")

    post_points, post_best = find_template_multiscale(
        post_img, template_path, TEMPLATE_SCALES, MATCH_THRESHOLD, NMS_MIN_DIST
    )
    if not post_points:
        logger.error(f"    ❌ 主窗口内未匹配到 [REDACTED] 头像 (最高置信度={post_best:.3f})")
        template = cv2.cvtColor(np.array(Image.open(template_path)), cv2.COLOR_RGB2BGR)
        logger.info("    主窗口内各尺度最高置信度:")
        for s in TEMPLATE_SCALES:
            if s >= post_img.shape[0] or s >= post_img.shape[1]:
                continue
            scaled = cv2.resize(template, (s, s), interpolation=cv2.INTER_AREA)
            res = cv2.matchTemplate(post_img, scaled, cv2.TM_CCOEFF_NORMED)
            _, mx, _, ml = cv2.minMaxLoc(res)
            logger.info(f"    - {s}px: max={mx:.3f} at ({ml[0]+s//2}, {ml[1]+s//2})")
        found = False
        ratio = 0.0
        debug = post_img.copy()
    else:
        logger.info(f"    主窗口内匹配到 {len(post_points)} 个 [REDACTED] 头像:")
        for i, (x, y, s, sc) in enumerate(post_points):
            logger.info(f"      #{i}: ({x}, {y}) conf={s:.3f} scale={sc}px")
        post_target = max(post_points, key=lambda p: p[2])
        logger.info(f"    用置信度最高的点检测绿色环: ({post_target[0]}, {post_target[1]})")
        found, ratio, debug = find_green_ring(
            post_img, post_target[0], post_target[1], post_target[3]
        )

    debug_path = os.path.join(OUTPUT_DIR, f"stage_f_verify_green_ring_{attempt_idx}.png")
    cv2.imwrite(debug_path, debug)
    logger.info(f"    绿色像素占比: {ratio:.3f} (阈值 0.4)")
    logger.info(f"    验证图: {debug_path}")

    if found:
        logger.info("    ✅ 检测到绿色环，点击成功")
    else:
        logger.error("    ❌ 未检测到绿色环")

    # ========== 阶段 G：检查窗口数 ==========
    logger.info("\n[G] 检查点击后窗口数")
    count_after, wins_after = count_wechat_windows()
    logger.info(f"    点击后微信窗口数: {count_after}")
    for w in wins_after:
        logger.info(f"    - hwnd={w['hwnd']} title={w['title']!r} class={w['class']!r}")

    logger.info("\n" + "=" * 60)
    logger.info(f"  第 {attempt_idx} 次尝试结果")
    logger.info("=" * 60)
    logger.info(f"  匹配点: ({target[0]}, {target[1]}) conf={target[2]:.3f}")
    logger.error(f"  绿色环验证: {'✅ 通过' if found else '❌ 未通过'}")
    logger.info(f"  窗口数变化: {count_before} -> {count_after}")
    if count_after == 1:
        logger.info("  分支: 1 个窗口 → 联系人聊天界面")
    elif count_after == 2:
        logger.info("  分支: 2 个窗口 → 历史聊天界面（需再次匹配+双击）")
    else:
        logger.info(f"  分支: {count_after} 个窗口（未预期）")
    logger.info("=" * 60)

    return found, target, count_after


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    do_click = "--click" in sys.argv

    logger.info("=" * 60)
    logger.info("  在搜索候选框窗口内匹配 [REDACTED] 头像（含重试机制）")
    logger.info(f"  模式: {'匹配+点击+验证+重试' if do_click else '只匹配（不点击）'}")
    logger.info(f"  最多尝试次数: {MAX_ATTEMPTS}（初次 + {MAX_RETRIES} 次重试）")
    logger.info("=" * 60)

    if not do_click:
        # 只匹配模式：执行一次，不点击
        run_one_attempt(1, 1, do_click=False)
        return

    # 点击模式：最多 MAX_ATTEMPTS 次执行（初次 + 最多 MAX_RETRIES 次重试）
    final_success = False
    final_target = None
    final_count_after = 0

    for attempt in range(1, MAX_ATTEMPTS + 1):
        if attempt > 1:
            # 优化点3（澄清版）：重试前在主窗口中间栏滚动滑轮+点击
            # 失败后搜索候选框已关闭，重试时重新从点击搜索栏开始
            logger.info("\n[重试预备] 在主窗口中间栏执行滚动+点击...")
            scroll_in_main_middle_column()
            time.sleep(0.5)

        success, target, count_after = run_one_attempt(attempt, MAX_ATTEMPTS, do_click=True)
        final_success = success
        final_target = target
        final_count_after = count_after

        if success:
            logger.info(f"\n✅ 第 {attempt} 次尝试成功，流程完成")
            break
        else:
            logger.error(f"\n❌ 第 {attempt} 次尝试失败")
            if attempt < MAX_ATTEMPTS:
                logger.info(f"   0.5 秒后将进行第 {attempt + 1} 次尝试...")
                time.sleep(0.5)

    logger.info("\n" + "=" * 60)
    logger.info("  最终结果")
    logger.info("=" * 60)
    if final_success:
        logger.info(f"  ✅ 流程成功")
        if final_target:
            logger.info(f"  匹配点: ({final_target[0]}, {final_target[1]}) "
                  f"conf={final_target[2]:.3f}")
        logger.info(f"  点击后窗口数: {final_count_after}")
        if final_count_after == 1:
            logger.info("  分支: 1 个窗口 → 联系人聊天界面，阶段一完成")
        elif final_count_after == 2:
            logger.info("  分支: 2 个窗口 → 历史聊天界面，需进入阶段二（再次匹配+双击）")
    else:
        logger.error(f"  ❌ {MAX_ATTEMPTS} 次尝试全部失败")
        logger.info("  建议检查：")
        logger.info("  - 微信是否正常显示")
        logger.info("  - 搜索候选框是否出现")
        logger.info("  - [REDACTED] 头像是否在搜索结果中")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
