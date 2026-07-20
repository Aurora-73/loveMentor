# -*- coding: utf-8 -*-
"""微信窗口截图 + OCR 识别。

从 mcp_server/tools_wechat.py 的 _wechat_ocr_impl 迁移。

流程：
1. 确保微信窗口可见（ensure_wechat_window）
2. 截图微信主窗口
3. 根据区域裁剪（full/chat/session）
4. 保存截图
5. OCR 识别
6. 返回带位置信息的结果

用法：
    from engine.wechat_sender.wechat_ocr import ocr_wechat_window
    result = ocr_wechat_window(region="chat", use_cache=False)
"""
import os
import sys
import ctypes
import logging
import traceback

logger = logging.getLogger(__name__)

# 项目根目录（wechat_ocr.py 在 engine/wechat_sender/ 下，上三级是项目根）
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def ocr_wechat_window(region: str = "full", use_cache: bool = False) -> dict:
    """截图微信窗口并进行 OCR 文字识别。

    Args:
        region: 截图区域，可选值：
            - "full"（默认）: 整个微信窗口
            - "chat": 仅聊天区域（右侧大部分）
            - "session": 仅会话列表区域（中间栏）
        use_cache: 是否使用 OCR 缓存（默认 False，因为界面内容会变化）

    Returns:
        dict: {
            "success": bool,
            "message": str,
            "text_count": int,         # 识别到的文字条数
            "texts": list[dict],       # 文字列表
            "full_text": str,          # 所有文字拼接（按 y 坐标排序，换行分隔）
            "image_size": dict,        # 截图尺寸 {"width": int, "height": int}
            "region": str,             # 实际截图区域
            "screenshot_path": str,    # 截图保存路径
            "error": str|None,
        }

        texts 中每个元素: {
            "text": str,
            "bbox": [[x1,y1], [x2,y2], [x3,y3], [x4,y4]],
            "confidence": float,
            "center": [x, y],
        }
    """
    import time

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass

    # 确保微信窗口可见
    from engine.wechat_sender.ensure_window import ensure_wechat_window
    window_result = ensure_wechat_window()
    if not window_result["success"]:
        return {
            "success": False,
            "message": f"微信窗口不可用: {window_result['message']}",
            "text_count": 0,
            "texts": [],
            "full_text": "",
            "image_size": {"width": 0, "height": 0},
            "region": region,
            "screenshot_path": "",
            "error": "WINDOW_NOT_AVAILABLE",
        }

    # 导入截图和布局检测
    import cv2
    from engine.wechat_sender.window_capture import find_wechat_window, screencap_window
    from engine.wechat_sender.dynamic_detector import WeChatLayoutDetector

    # 获取微信窗口
    window = find_wechat_window()
    if not window:
        return {
            "success": False,
            "message": "未找到微信主窗口",
            "text_count": 0,
            "texts": [],
            "full_text": "",
            "image_size": {"width": 0, "height": 0},
            "region": region,
            "screenshot_path": "",
            "error": "WINDOW_NOT_FOUND",
        }

    hwnd = window["hwnd"]

    # 截图
    img = screencap_window(hwnd)
    if img is None:
        return {
            "success": False,
            "message": "微信窗口截图失败",
            "text_count": 0,
            "texts": [],
            "full_text": "",
            "image_size": {"width": 0, "height": 0},
            "region": region,
            "screenshot_path": "",
            "error": "SCREENSHOT_FAILED",
        }

    h, w = img.shape[:2]

    # 根据区域裁剪
    nav_right = 0
    session_right = 0
    if region != "full":
        detector = WeChatLayoutDetector()
        nav_right, session_right = detector.detect(img)

    if region == "chat":
        # 聊天区域：session_right 到右边
        if session_right > 0:
            crop_img = img[:, session_right:]
            crop_offset_x = session_right
        else:
            crop_img = img
            crop_offset_x = 0
    elif region == "session":
        # 会话列表：nav_right 到 session_right
        if nav_right > 0 and session_right > 0:
            crop_img = img[:, nav_right:session_right]
            crop_offset_x = nav_right
        else:
            crop_img = img
            crop_offset_x = 0
    else:
        # full
        crop_img = img
        crop_offset_x = 0

    # 保存截图
    output_dir = os.path.join(_PROJECT_ROOT, "data", "outputs", "wechat_ocr")
    os.makedirs(output_dir, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    screenshot_path = os.path.join(output_dir, f"wechat_ocr_{timestamp}.png")
    cv2.imwrite(screenshot_path, crop_img)

    # OCR 识别
    from engine.importers.ocr_engine import ocr_image

    ocr_results = ocr_image(screenshot_path, use_cache=use_cache)

    # 转换为返回格式，并修正坐标偏移（裁剪后的坐标要加回偏移量）
    texts = []
    for r in ocr_results:
        texts.append({
            "text": r.text,
            "bbox": [[p[0] + crop_offset_x, p[1]] for p in r.bbox],
            "confidence": round(r.confidence, 3),
            "center": [r.center_x + crop_offset_x, r.center_y],
        })

    # 拼接完整文字
    full_text = "\n".join(r.text for r in ocr_results)

    crop_h, crop_w = crop_img.shape[:2]
    return {
        "success": True,
        "message": f"OCR 识别完成：{len(texts)} 条文字，截图尺寸 {crop_w}x{crop_h}",
        "text_count": len(texts),
        "texts": texts,
        "full_text": full_text,
        "image_size": {"width": crop_w, "height": crop_h},
        "region": region,
        "screenshot_path": screenshot_path,
        "error": None,
    }
