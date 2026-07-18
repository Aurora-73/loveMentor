"""微信自动发消息 MCP 工具。

通过 Win32 API + OpenCV 视觉识别，自动化操作微信 PC 客户端发送消息。
底层调用 engine/wechat_sender/wechat_e2e_run.py 的 run_e2e 函数。

前置条件：
- 微信（Weixin.exe）已运行并登录
- 联系人头像模板已存放在 data/avatars/<联系人名>.jpg
- 依赖：OpenCV, numpy, PIL（已随项目安装）
"""

import os
import sys
import traceback

# 确保项目根目录在 sys.path 中
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# wechat_sender 内部用绝对导入（from dynamic_detector import ...），
# 需要把该目录加入 sys.path
_WECHAT_SENDER_DIR = os.path.join(_PROJECT_ROOT, "engine", "wechat_sender")
if _WECHAT_SENDER_DIR not in sys.path:
    sys.path.insert(0, _WECHAT_SENDER_DIR)


# ── 微信窗口管理 ────────────────────────────────────────────────

WEIXIN_EXE = r"D:\Weixin\Weixin.exe"


def _is_wechat_running() -> bool:
    """检查微信进程是否在运行（不检查窗口）。"""
    try:
        import subprocess
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq Weixin.exe", "/NH"],
            capture_output=True, text=True, timeout=5,
        )
        return "Weixin.exe" in result.stdout
    except Exception:
        return False


def _ensure_wechat_window(max_wait: float = 15.0) -> dict:
    """确保微信主窗口可见。

    如果微信进程在运行但主窗口不可见（最小化到托盘），
    通过启动新 Weixin.exe 进程触发已运行实例显示主窗口。

    Args:
        max_wait: 等待窗口出现的最大秒数

    Returns:
        dict: {
            "success": bool,
            "window_visible": bool,
            "action": str,  # "already_visible" / "restored" / "launched_new" / "failed"
            "message": str,
        }
    """
    import ctypes
    import time

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass

    from engine.wechat_sender.test_current_wechat import find_wechat_window

    # 1. 检查主窗口是否已可见
    window = find_wechat_window()
    if window:
        return {
            "success": True,
            "window_visible": True,
            "action": "already_visible",
            "message": f"微信主窗口已可见 ({window['width']}x{window['height']})",
        }

    # 2. 检查微信进程是否在运行
    process_running = _is_wechat_running()
    if not process_running:
        return {
            "success": False,
            "window_visible": False,
            "action": "process_not_running",
            "message": "微信进程未运行，请先调用 wechat_start 启动微信",
        }

    # 3. 进程在运行但窗口不可见，启动新 Weixin.exe 触发已运行实例显示窗口
    import subprocess
    try:
        subprocess.Popen(
            [WEIXIN_EXE],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        return {
            "success": False,
            "window_visible": False,
            "action": "launch_failed",
            "message": f"启动 Weixin.exe 失败: {e}",
        }

    # 4. 轮询等待窗口出现
    start_time = time.time()
    while time.time() - start_time < max_wait:
        time.sleep(1.0)
        window = find_wechat_window()
        if window:
            elapsed = time.time() - start_time
            return {
                "success": True,
                "window_visible": True,
                "action": "restored",
                "message": f"微信主窗口已恢复可见 ({window['width']}x{window['height']}，耗时 {elapsed:.1f}s)",
            }

    return {
        "success": False,
        "window_visible": False,
        "action": "timeout",
        "message": f"等待 {max_wait}s 后窗口仍未出现，可能微信被最小化到托盘且无法自动恢复",
    }


# ── 工具1: wechat_send ──────────────────────────────────────────

def wechat_send(name: str, message: str) -> dict:
    """向微信联系人自动发送消息。

    通过视觉识别自动化操作微信 PC 客户端：
    1. 搜索联系人（需 data/avatars/<name>.jpg 头像模板）
    2. 点击头像进入聊天界面
    3. 输入消息并点击发送

    如果微信进程在运行但主窗口不可见（最小化到托盘），
    会自动启动新 Weixin.exe 进程触发已运行实例显示主窗口。

    Args:
        name: 微信联系人昵称（需与 data/avatars/<name>.jpg 文件名一致）
        message: 要发送的消息内容

    Returns:
        dict: {
            "success": bool,
            "message": str,        # 结果描述
            "contact": str,        # 联系人名
            "template": str,       # 模板路径
            "attempts": int,       # 尝试次数（成功时）
            "error": str|None,     # 失败原因
            "window_restored": bool,  # 是否触发了窗口恢复
        }
    """
    try:
        # 定位头像模板
        avatars_dir = os.path.join(_PROJECT_ROOT, "data", "avatars")
        template_path = os.path.join(avatars_dir, f"{name}.jpg")

        if not os.path.exists(template_path):
            return {
                "success": False,
                "message": f"头像模板不存在: data/avatars/{name}.jpg",
                "contact": name,
                "template": template_path,
                "attempts": 0,
                "error": "TEMPLATE_NOT_FOUND",
                "window_restored": False,
            }

        # 设置 DPI 感知
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass

        # 确保微信窗口可见（修复：后台运行无窗口时打开窗口）
        window_result = _ensure_wechat_window()
        window_restored = window_result.get("action") == "restored"

        if not window_result["success"]:
            return {
                "success": False,
                "message": f"微信窗口不可用: {window_result['message']}",
                "contact": name,
                "template": template_path,
                "attempts": 0,
                "error": "WINDOW_NOT_AVAILABLE",
                "window_restored": window_restored,
            }

        # 导入端到端流程
        from engine.wechat_sender.wechat_e2e_run import run_e2e

        # 执行端到端发送
        success = run_e2e(message, name, template_path)

        if success:
            msg = f"消息已成功发送给 {name}"
            if window_restored:
                msg += "（已自动恢复微信窗口）"
            return {
                "success": True,
                "message": msg,
                "contact": name,
                "template": template_path,
                "attempts": 1,
                "error": None,
                "window_restored": window_restored,
            }
        else:
            return {
                "success": False,
                "message": f"发送失败（端到端流程未成功，详见日志）",
                "contact": name,
                "template": template_path,
                "attempts": 4,
                "error": "E2E_FLOW_FAILED",
                "window_restored": window_restored,
            }

    except ImportError as e:
        return {
            "success": False,
            "message": f"依赖模块导入失败: {e}",
            "contact": name,
            "template": "",
            "attempts": 0,
            "error": "IMPORT_ERROR",
            "window_restored": False,
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"运行异常: {e}",
            "contact": name,
            "template": "",
            "attempts": 0,
            "error": f"RUNTIME_ERROR: {traceback.format_exc()}",
            "window_restored": False,
        }


# ── 工具2: wechat_ocr ───────────────────────────────────────────

def wechat_ocr(region: str = "full", use_cache: bool = False) -> dict:
    """截图微信窗口并进行 OCR 文字识别。

    对当前微信主窗口截图，用 RapidOCR 识别文字，返回带位置信息的结果。
    适用于：读取聊天界面文字、提取联系人信息、识别界面元素等场景。

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
            "text": str,               # 文字内容
            "bbox": [[x1,y1], [x2,y2], [x3,y3], [x4,y4]],  # 四顶点坐标
            "confidence": float,       # 置信度
            "center": [x, y],          # 中心坐标
        }
    """
    try:
        import ctypes
        import time

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass

        # 确保微信窗口可见
        window_result = _ensure_wechat_window()
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
        import numpy as np
        from engine.wechat_sender.test_current_wechat import find_wechat_window, screencap_window
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

    except ImportError as e:
        return {
            "success": False,
            "message": f"依赖模块导入失败: {e}",
            "text_count": 0,
            "texts": [],
            "full_text": "",
            "image_size": {"width": 0, "height": 0},
            "region": region,
            "screenshot_path": "",
            "error": f"IMPORT_ERROR: {e}",
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"运行异常: {e}",
            "text_count": 0,
            "texts": [],
            "full_text": "",
            "image_size": {"width": 0, "height": 0},
            "region": region,
            "screenshot_path": "",
            "error": f"RUNTIME_ERROR: {traceback.format_exc()}",
        }
