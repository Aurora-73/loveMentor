"""阶段三（表情包版）：通过表情面板搜索并发送表情包。

关键设计（用户澄清）：
- 表情面板是独立的小窗口（类似搜索候选框），不是主窗口的一部分
- 实现策略：点击表情按钮前后对比窗口列表，找出新出现的窗口 = 表情面板
- 后续所有操作（搜索键、输入、点击表情）都在表情面板窗口上进行

流程：
1. 找微信主窗口 + 截图
2. 检测布局（找到聊天区域 session_right）
3. 在主窗口上：模板匹配 "表情按钮.png" → 点击进入表情面板
4. 枚举窗口，找出新出现的独立窗口 = 表情面板 hwnd
5. 在表情面板窗口上截图 → 模板匹配 "表情搜索键.png" → 点击搜索键
6. 在表情面板上输入表情关键词
7. 等待搜索结果加载
8. 重新截图表情面板 → 模板匹配 '表情搜索后的"全部表情".png' → 在该标题下方点击第一个表情
   （微信表情面板中点击搜索结果表情会直接发送，无需再点发送按钮）
9. 验证：等待 1s 后截图，检查 "全部表情" 标题是否已消失（发送后面板自动关闭）

用法：
    # 只检测不发送
    python send_emoji_run.py

    # 检测 + 发送
    python send_emoji_run.py "猫猫"
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
# 添加项目根目录到 sys.path（用于 from engine.wechat_sender.xxx import 的绝对导入）
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
from dynamic_detector import WeChatLayoutDetector  # noqa: E402
from window_capture import find_wechat_window, screencap_window  # noqa: E402
from wechat_window_utils import (  # noqa: E402
    find_largest_wechat_window,
    enumerate_visible_windows,
    _is_wechat_window,
)
from click_search_and_input import (  # noqa: E402
    get_client_offset,
    client_to_screen,
    physical_click,
    input_text_via_clipboard,
    safe_set_foreground_window,
)
from template_matcher import match_template_best  # noqa: E402

from logger import get_logger  # noqa: E402
logger = get_logger(__name__)

user32 = ctypes.windll.user32

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")

# 表情面板截图黑边配置
# PrintWindow 对 ToolSaveBits 类独立窗口截图时会包含窗口阴影区域（四周约 30 像素黑色边框）
# 动态检测黑边，最大不超过 50 像素（防止误判）
BLACK_BORDER_MAX = 50
BLACK_BORDER_THRESHOLD = 10  # 像素均值小于此值视为黑色


def _detect_black_border(image, threshold=BLACK_BORDER_THRESHOLD,
                          max_border=BLACK_BORDER_MAX):
    """动态检测截图四周的黑边宽度。

    PrintWindow 对表情面板这种 ToolSaveBits 独立窗口截图时，
    会包含窗口阴影区域（四周约 30 像素黑色边框）。需要检测并裁剪掉，
    否则模板匹配会在黑边区域失败。

    Args:
        image: 截图（BGR numpy 数组）
        threshold: 像素均值小于此值视为黑色行/列
        max_border: 最大黑边宽度（防止误判全黑图）

    Returns:
        tuple (top, left) 黑边宽度
        - top: 上边黑边宽度（与下边相同，假设对称）
        - left: 左边黑边宽度（与右边相同，假设对称）
    """
    h, w = image.shape[:2]

    # 检测上边界（从上往下找第一个非黑行）
    top = 0
    for y in range(min(max_border, h)):
        if image[y].mean() > threshold:
            top = y
            break

    # 检测左边界（从左往右找第一个非黑列）
    left = 0
    for x in range(min(max_border, w)):
        if image[:, x].mean() > threshold:
            left = x
            break

    return top, left


def _capture_emoji_panel(panel_hwnd):
    """截图表情面板并裁剪四周的黑边。

    PrintWindow 对表情面板（ToolSaveBits 独立窗口）截图时包含窗口阴影，
    导致四周有约 30 像素的黑色边框。本函数截图后动态检测并裁剪黑边，
    返回裁剪后的图及偏移量。

    坐标关系：
    - 截图坐标系 = 客户区坐标系（因表情面板客户区 = 窗口尺寸，无边框）
    - 裁剪后图坐标 + (crop_x, crop_y) = 原始截图坐标 = 客户区坐标
    - 后续坐标计算时：client_x = match.center_x + crop_x - offset_x

    Args:
        panel_hwnd: 表情面板窗口句柄

    Returns:
        tuple (cropped_img, crop_x, crop_y) 或 (None, 0, 0)
        - cropped_img: 裁剪后的图
        - crop_x, crop_y: 裁剪偏移量（原始坐标 = 裁剪后坐标 + 偏移量）
    """
    img = screencap_window(panel_hwnd)
    if img is None:
        return None, 0, 0

    h, w = img.shape[:2]
    top, left = _detect_black_border(img)

    if top == 0 and left == 0:
        # 无黑边，直接返回
        return img, 0, 0

    # 对称裁剪（四周黑边宽度基本相同）
    # 下边和右边也用同样的宽度（略保守，多裁 2 像素避免过渡区）
    crop = max(top, left) + 2
    if h > crop * 2 and w > crop * 2:
        cropped = img[crop:h - crop, crop:w - crop]
        logger.info(
            f"    [表情面板] 裁剪黑边: top={top} left={left} → crop={crop}px, "
            f"原图 {w}x{h} → 裁剪后 {cropped.shape[1]}x{cropped.shape[0]}"
        )
        return cropped, crop, crop

    # 裁剪后太小，返回原图
    logger.warning(f"    [表情面板] 裁剪后尺寸过小，返回原图（黑边未裁剪）")
    return img, 0, 0


def _find_emoji_button(image, session_right):
    """定位聊天输入框旁的"表情按钮"（笑脸图标）。

    表情按钮在聊天输入框下方工具栏的左侧（靠近聊天区域左边界），
    不是右侧。搜索区域：聊天区域底部 30%（输入框工具栏区域）。

    Args:
        image: 微信窗口截图（BGR numpy 数组）
        session_right: 聊天区域左边界 x

    Returns:
        TemplateMatch 或 None
    """
    h, w = image.shape[:2]
    # 表情按钮在输入框工具栏左侧（靠近聊天区域左边界）
    # 搜索区域：聊天区域底部 30%（y > h*0.70），x 范围是整个聊天区域
    search_region = (
        session_right,    # x1：聊天区域左边界
        int(h * 0.70),    # y1：底部 30%
        w,                # x2：窗口右边界
        h,                # y2：窗口底部
    )
    return match_template_best(
        image, "表情按钮.png",
        threshold=0.85,
        search_region=search_region,
    )


def _find_emoji_panel_window(before_hwnds, timeout=3.0, poll_interval=0.3):
    """通过对比点击前后的窗口列表，找出新出现的表情面板窗口。

    用户澄清：表情面板是独立的小窗口（类似搜索候选框）。
    策略：枚举当前所有可见窗口，排除点击前已存在的窗口，
    在剩余的微信相关窗口中找表情面板。

    Args:
        before_hwnds: 点击表情按钮前已存在的窗口 hwnd 集合
        timeout: 等待表情面板出现的最大秒数
        poll_interval: 轮询间隔秒数

    Returns:
        dict 或 None: 表情面板窗口信息（hwnd/title/class/left/top/width/height），
                     未找到返回 None
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        all_windows = enumerate_visible_windows()
        new_windows = [w for w in all_windows if w["hwnd"] not in before_hwnds]

        # 在新窗口中找微信相关的窗口
        for w in new_windows:
            # 必须是微信相关窗口
            if not _is_wechat_window(w["title"], w["class"], w.get("pid")):
                continue
            # 排除太小的窗口（托盘图标等），表情面板应该有一定大小
            # 表情面板通常至少 300x400
            if w["width"] < 200 or w["height"] < 200:
                continue
            # 排除主窗口（标题="微信" + Qt/WeChatMainWndForPC 类）
            # 表情面板的标题可能不同，或类名不同
            cls = w["class"]
            if w["title"] == "微信" and any(c in cls for c in ("Qt", "WeChatMainWndForPC", "WeixinMainWndForPC")):
                # 这是主窗口，跳过（可能是因为主窗口被重新创建）
                # 但实际上主窗口 hwnd 不会变，所以这种情况不会发生
                continue
            logger.info(
                f"    [表情面板] 找到新窗口: hwnd={w['hwnd']} "
                f"title={w['title']!r} class={w['class']!r} "
                f"size={w['width']}x{w['height']} "
                f"pos=({w['left']},{w['top']})"
            )
            return w

        time.sleep(poll_interval)

    logger.warning("    [表情面板] 等待超时，未找到新出现的表情面板窗口")
    return None


def _find_emoji_search_button(image):
    """定位表情面板内的"搜索键"。

    表情面板打开后，搜索键通常在面板顶部或右上角。
    搜索区域：全图（表情面板截图，直接全图搜索）。

    Args:
        image: 表情面板窗口截图

    Returns:
        TemplateMatch 或 None
    """
    # 表情面板是独立窗口，截图就是面板本身，直接全图搜索
    return match_template_best(
        image, "表情搜索键.png",
        threshold=0.80,
    )


def _find_emoji_all_header(image):
    """定位搜索后出现的"全部表情"标题文字。

    搜索结果出现后，"全部表情"作为分组标题显示，搜索结果表情在其下方。
    点击下方的第一个表情即可直接发送（无需再点发送按钮）。

    模板文件已重命名为 '全部表情.png'（无中文引号问题）。

    Args:
        image: 表情面板窗口截图

    Returns:
        TemplateMatch 或 None
    """
    return match_template_best(
        image, "全部表情.png",
        threshold=0.80,
    )


def _click_first_emoji_below_header(panel_hwnd, image, header_match, offset_x, offset_y,
                                     crop_offset_x=0, crop_offset_y=0):
    """在"全部表情"标题下方点击第一个表情。

    微信表情面板中，搜索结果在"全部表情"标题正下方以网格排列。
    点击第一个表情会直接发送（不需要再点发送按钮）。

    Args:
        panel_hwnd: 表情面板窗口句柄
        image: 表情面板截图（已裁剪黑边）
        header_match: "全部表情"的 TemplateMatch（坐标基于裁剪后图）
        offset_x, offset_y: 客户区偏移（get_client_offset 返回值）
        crop_offset_x, crop_offset_y: 截图黑边裁剪偏移
            裁剪后图坐标 + crop_offset = 原始截图坐标 = 客户区坐标

    Returns:
        tuple (screen_x, screen_y) 或 None
    """
    # 点击位置：标题正下方约 60px（第一个表情的中心位置）
    # 表情网格通常每行高约 80-100px，第一行中心约在标题下方 60px
    click_offset_y = 60  # 标题下方 60px（第一个表情的中心）
    click_x = header_match.center_x
    click_y = header_match.center_y + click_offset_y

    logger.info(
        f"    标题位置（裁剪后图）: ({header_match.center_x}, {header_match.center_y})，"
        f"点击位置: ({click_x}, {click_y})（标题下方 {click_offset_y}px）"
    )

    # 标注点击位置（在裁剪后图上标注）
    debug = image.copy()
    cv2.circle(debug, (click_x, click_y), 15, (0, 255, 0), 3)
    cv2.putText(debug, f"EMOJI ({click_x},{click_y})",
                (click_x + 20, click_y), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                (0, 0, 255), 2, cv2.LINE_AA)
    # 画标题框
    left, top, right, bottom = header_match.rect
    cv2.rectangle(debug, (left, top), (right, bottom), (0, 255, 255), 2)
    cv2.putText(debug, "HEADER",
                (left, top - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                (0, 255, 255), 1, cv2.LINE_AA)
    debug_path = os.path.join(OUTPUT_DIR, "stage_3_emoji_click.png")
    cv2.imwrite(debug_path, debug)
    logger.info(f"    点击位置标注图: {debug_path}")

    # 转换为屏幕坐标并点击
    # 裁剪后图坐标 + crop_offset = 原始截图坐标 = 客户区坐标
    # 客户区坐标 - offset = client_to_screen 输入坐标
    client_x = click_x + crop_offset_x - offset_x
    client_y = click_y + crop_offset_y - offset_y
    screen_x, screen_y = client_to_screen(panel_hwnd, client_x, client_y)
    logger.info(
        f"    表情点击屏幕坐标: ({screen_x}, {screen_y}) "
        f"(裁剪后图({click_x},{click_y}) + crop({crop_offset_x},{crop_offset_y}) - offset({offset_x},{offset_y}))"
    )

    safe_set_foreground_window(panel_hwnd)
    time.sleep(0.3)
    physical_click(screen_x, screen_y)
    return screen_x, screen_y


def run_send_emoji(emoji_keyword, do_send=True):
    """执行阶段三（表情包版）：通过表情面板搜索并发送表情包。

    流程：
    1. 找微信主窗口 + 截图
    2. 检测布局（找到聊天区域 session_right）
    3. 在主窗口上：模板匹配 "表情按钮.png" → 点击进入表情面板
    4. 枚举窗口，找出新出现的独立窗口 = 表情面板 hwnd
    5. 在表情面板上截图 → 模板匹配 "表情搜索键.png" → 点击搜索键
    6. 在表情面板上输入表情关键词
    7. 等待搜索结果加载
    8. 重新截图表情面板 → 模板匹配 '表情搜索后的"全部表情".png' → 在其下方点击第一个表情
    9. 验证：等待 1s 后截图，检查 "全部表情" 标题是否已消失

    Args:
        emoji_keyword: 表情搜索关键词（如 "猫猫"、"感谢"、"开心"）
        do_send: True=发送，False=只检测不发送

    Returns:
        bool: 是否成功
    """
    from send_common import (
        check_wechat_login, find_wechat_main_window,
        capture_and_detect_layout,
    )

    logger.info("=" * 60)
    if do_send:
        logger.info(f"  阶段三（表情包版）：搜索并发送表情  keyword={emoji_keyword!r}")
    else:
        logger.info("  阶段三（表情包版）：只检测布局（不发送）")
    logger.info("=" * 60)

    # 0. 前置检查：微信是否已登录
    logged_in, _ = check_wechat_login()
    if not logged_in:
        return False

    # 1. 找微信主窗口
    window = find_wechat_main_window()
    if not window:
        return False
    main_hwnd = window["hwnd"]

    # 2-3. 截图主窗口 + 检测布局
    img, nav_right, session_right = capture_and_detect_layout(
        main_hwnd, screenshot_name="stage_3_emoji_before.png"
    )
    if img is None:
        return False

    # 4. 在主窗口上定位表情按钮
    logger.info("\n[4] 定位表情按钮（聊天输入框旁的笑脸图标）")
    emoji_btn_match = _find_emoji_button(img, session_right)

    if emoji_btn_match is None:
        logger.error("    ❌ 未找到表情按钮")
        logger.info("    可能原因：聊天界面未打开，或表情按钮图标与模板不匹配")
        debug_path = os.path.join(OUTPUT_DIR, "stage_3_emoji_button_not_found.png")
        cv2.imwrite(debug_path, img)
        return False

    logger.info(
        f"    ✅ 找到表情按钮: ({emoji_btn_match.center_x}, {emoji_btn_match.center_y}) "
        f"conf={emoji_btn_match.confidence:.4f}"
    )

    # 标注表情按钮位置
    debug = img.copy()
    cv2.circle(debug, (emoji_btn_match.center_x, emoji_btn_match.center_y), 15,
               (0, 255, 0), 3)
    cv2.putText(debug, f"EMOJI_BTN ({emoji_btn_match.center_x},{emoji_btn_match.center_y})",
                (emoji_btn_match.center_x + 20, emoji_btn_match.center_y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2, cv2.LINE_AA)
    debug_path = os.path.join(OUTPUT_DIR, "stage_3_emoji_button.png")
    cv2.imwrite(debug_path, debug)

    if not do_send:
        logger.info("\n[只检测模式] 已找到表情按钮，未点击")
        return True

    # 5. 点击表情按钮前：记录当前所有窗口 hwnd
    logger.info("\n[5] 记录点击表情按钮前的窗口列表")
    before_windows = enumerate_visible_windows()
    before_hwnds = {w["hwnd"] for w in before_windows}
    logger.info(f"    当前窗口数: {len(before_hwnds)}")

    # 6. 点击表情按钮，打开表情面板
    logger.info(f"\n[6] 点击表情按钮，打开表情面板")
    offset_x, offset_y = get_client_offset(main_hwnd)
    client_x = emoji_btn_match.center_x - offset_x
    client_y = emoji_btn_match.center_y - offset_y
    screen_x, screen_y = client_to_screen(main_hwnd, client_x, client_y)
    logger.info(f"    表情按钮屏幕坐标: ({screen_x}, {screen_y})")
    safe_set_foreground_window(main_hwnd)
    time.sleep(0.5)
    physical_click(screen_x, screen_y)
    time.sleep(1.0)  # 等待表情面板打开

    # 7. 枚举窗口，找出新出现的表情面板窗口
    logger.info("\n[7] 枚举窗口，查找新出现的表情面板窗口")
    panel_window = _find_emoji_panel_window(before_hwnds, timeout=3.0)
    if panel_window is None:
        logger.error("    ❌ 未找到表情面板窗口")
        logger.info("    可能原因：表情面板未作为独立窗口打开，或窗口枚举失败")
        # 尝试回退方案：直接在主窗口上搜索表情搜索键
        logger.info("    尝试回退方案：直接在主窗口截图上搜索表情搜索键...")
        # 这里不实现回退，直接返回失败，让用户测试时确认表情面板的窗口属性
        return False

    panel_hwnd = panel_window["hwnd"]
    logger.info(
        f"    ✅ 表情面板窗口: hwnd={panel_hwnd} "
        f"title={panel_window['title']!r} class={panel_window['class']!r} "
        f"size={panel_window['width']}x{panel_window['height']}"
    )

    # 8. 在表情面板上截图，定位表情搜索键
    logger.info("\n[8] 截图表情面板，定位表情搜索键（自动裁剪黑边）")
    panel_img, crop_offset_x, crop_offset_y = _capture_emoji_panel(panel_hwnd)
    if panel_img is None:
        logger.error("❌ 表情面板截图失败")
        return False
    panel_path = os.path.join(OUTPUT_DIR, "stage_3_emoji_panel.png")
    cv2.imwrite(panel_path, panel_img)
    logger.info(f"    表情面板截图（裁剪后）: {panel_path} ({panel_img.shape[1]}x{panel_img.shape[0]})")
    logger.info(f"    黑边裁剪偏移: ({crop_offset_x}, {crop_offset_y})")

    search_btn_match = _find_emoji_search_button(panel_img)
    if search_btn_match is None:
        logger.error("    ❌ 未找到表情搜索键")
        logger.info("    可能原因：表情面板布局与预期不符，或搜索键图标与模板不匹配")
        return False

    logger.info(
        f"    ✅ 找到表情搜索键: ({search_btn_match.center_x}, {search_btn_match.center_y}) "
        f"conf={search_btn_match.confidence:.4f}"
    )

    # 标注搜索键
    debug = panel_img.copy()
    cv2.circle(debug, (search_btn_match.center_x, search_btn_match.center_y), 10,
               (0, 255, 0), 3)
    cv2.putText(debug, f"SEARCH_BTN ({search_btn_match.center_x},{search_btn_match.center_y})",
                (search_btn_match.center_x + 20, search_btn_match.center_y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2, cv2.LINE_AA)
    debug_path = os.path.join(OUTPUT_DIR, "stage_3_emoji_search_btn.png")
    cv2.imwrite(debug_path, debug)

    # 9. 点击搜索键，打开搜索输入框
    logger.info(f"\n[9] 点击表情搜索键，打开搜索输入框")
    offset_x, offset_y = get_client_offset(panel_hwnd)
    # 裁剪后图坐标 + crop_offset = 原始截图坐标 = 客户区坐标
    # 客户区坐标 - offset = client_to_screen 输入坐标
    client_x = search_btn_match.center_x + crop_offset_x - offset_x
    client_y = search_btn_match.center_y + crop_offset_y - offset_y
    screen_x, screen_y = client_to_screen(panel_hwnd, client_x, client_y)
    logger.info(
        f"    搜索键屏幕坐标: ({screen_x}, {screen_y}) "
        f"(裁剪后图({search_btn_match.center_x},{search_btn_match.center_y}) + "
        f"crop({crop_offset_x},{crop_offset_y}) - offset({offset_x},{offset_y}))"
    )
    safe_set_foreground_window(panel_hwnd)
    time.sleep(0.3)
    physical_click(screen_x, screen_y)
    time.sleep(0.8)  # 等待搜索输入框打开

    # 10. 输入表情关键词
    logger.info(f"\n[10] 输入表情关键词: {emoji_keyword!r}")
    input_text_via_clipboard(panel_hwnd, emoji_keyword)
    time.sleep(3.0)  # 等待搜索结果加载（微信反应较慢，至少 3s）

    # 11. 重新截图表情面板（用于调试记录）
    logger.info('\n[11] 重新截图表情面板（用于调试记录）')
    img_after_search, crop_offset_x, crop_offset_y = _capture_emoji_panel(panel_hwnd)
    if img_after_search is None:
        logger.error("❌ 搜索后截图失败")
        return False
    search_path = os.path.join(OUTPUT_DIR, "stage_3_emoji_search_result.png")
    cv2.imwrite(search_path, img_after_search)
    logger.info(f"    搜索结果截图（裁剪后）: {search_path}")

    # 12-13. 随机点击表情 + 验证（带重试）
    # 用户反馈：点击区域可行，但有概率点到空白区域
    # 如果点击之后窗口没有消失，就再次随机点击
    import random
    MAX_CLICK_RETRIES = 3  # 最多重试 3 次（共 4 次点击）
    offset_x, offset_y = get_client_offset(panel_hwnd)

    for attempt in range(1, MAX_CLICK_RETRIES + 2):  # attempt = 1, 2, 3, 4
        logger.info(f"\n[12] 随机点击表情（第 {attempt}/{MAX_CLICK_RETRIES + 1} 次尝试）")

        # 每次重试前重新截图（前一次点击可能改变了面板内容）
        if attempt > 1:
            img_retry, crop_offset_x, crop_offset_y = _capture_emoji_panel(panel_hwnd)
            if img_retry is None:
                logger.error("❌ 重试时截图失败")
                return False
            h, w = img_retry.shape[:2]
        else:
            h, w = img_after_search.shape[:2]

        # 表情包网格区域：x=10%-80%, y=20%-80%（基于裁剪后图）
        # 避开边缘（标题栏、搜索框、边界）
        click_x_in_crop = random.randint(int(w * 0.10), int(w * 0.80))
        click_y_in_crop = random.randint(int(h * 0.20), int(h * 0.80))
        # 裁剪后图坐标 + crop_offset = 客户区坐标
        client_x = click_x_in_crop + crop_offset_x - offset_x
        client_y = click_y_in_crop + crop_offset_y - offset_y
        screen_x, screen_y = client_to_screen(panel_hwnd, client_x, client_y)
        logger.info(
            f"    随机点击位置: 裁剪后图({click_x_in_crop},{click_y_in_crop}) "
            f"→ 客户区({client_x},{client_y}) → 屏幕({screen_x},{screen_y})"
        )
        safe_set_foreground_window(panel_hwnd)
        time.sleep(0.3)
        physical_click(screen_x, screen_y)

        time.sleep(1.5)  # 等待表情发送（点击表情直接发送，无需点发送按钮）

        # 13. 验证：检查表情面板窗口是否已关闭（发送后面板通常自动关闭）
        logger.info(f"\n[13] 验证：检查表情面板窗口是否已关闭（第 {attempt} 次点击后）")
        time.sleep(0.5)
        # 检查表情面板 hwnd 是否还存在且可见
        if not user32.IsWindow(panel_hwnd):
            logger.info(f"    ✅ 表情面板窗口已销毁，第 {attempt} 次点击发送成功")
            logger.info("\n" + "=" * 60)
            logger.info("  阶段三（表情包版）完成")
            logger.info("=" * 60)
            return True

        if not user32.IsWindowVisible(panel_hwnd):
            logger.info(f"    ✅ 表情面板窗口已隐藏，第 {attempt} 次点击发送成功")
            logger.info("\n" + "=" * 60)
            logger.info("  阶段三（表情包版）完成")
            logger.info("=" * 60)
            return True

        # 窗口仍可见
        if attempt <= MAX_CLICK_RETRIES:
            logger.warning(
                f"    ⚠️ 表情面板窗口仍可见，可能点到了空白区域，将再次随机点击重试"
                f"（剩余 {MAX_CLICK_RETRIES + 1 - attempt} 次）"
            )
            # 截图查看当前状态（仅第一次重试时保存）
            if attempt == 1:
                img_after_send, _, _ = _capture_emoji_panel(panel_hwnd)
                if img_after_send is not None:
                    after_path = os.path.join(OUTPUT_DIR, "stage_3_emoji_after_send.png")
                    cv2.imwrite(after_path, img_after_send)
                    logger.info(f"    发送后截图: {after_path}")
        else:
            # 已达到最大重试次数
            logger.error(
                f"    ❌ 已尝试 {MAX_CLICK_RETRIES + 1} 次点击，表情面板仍未关闭"
            )
            img_after_send, _, _ = _capture_emoji_panel(panel_hwnd)
            if img_after_send is not None:
                after_path = os.path.join(OUTPUT_DIR, "stage_3_emoji_after_send.png")
                cv2.imwrite(after_path, img_after_send)
                logger.info(f"    发送后截图: {after_path}")

    logger.warning("    ⚠️ 表情面板未关闭，可能表情未发送（多次点击位置都不在表情上）")
    return False


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    if len(sys.argv) >= 2:
        keyword = sys.argv[1]
        do_send = True
    else:
        keyword = "猫猫"  # 只检测模式用的测试关键词
        do_send = False

    success = run_send_emoji(keyword, do_send=do_send)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
