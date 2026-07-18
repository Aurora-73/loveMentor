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
    import ctypes.wintypes as wintypes
    import time

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass

    user32 = ctypes.windll.user32

    from engine.wechat_sender.test_current_wechat import find_wechat_window

    # 1. 检查主窗口是否已可见（必须 >= 500x400 才算主窗口）
    window = find_wechat_window()
    if window and window["width"] >= 500 and window["height"] >= 400:
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

    # 3. 进程在运行但窗口不可见，尝试多种方法恢复
    import subprocess

    # 方法 A: 启动新 Weixin.exe 触发已运行实例显示窗口
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

    # 短暂等待方法 A 生效
    time.sleep(2.0)
    window = find_wechat_window()
    if window and window["width"] >= 500 and window["height"] >= 400:
        return {
            "success": True,
            "window_visible": True,
            "action": "restored",
            "message": f"微信主窗口已恢复可见 ({window['width']}x{window['height']}，方法A:启动新进程)",
        }

    # 方法 B: 点击任务栏微信图标
    try:
        from engine.wechat_sender.click_search_and_input import click_taskbar_wechat
        click_taskbar_wechat(max_wait=3.0)
    except Exception as e:
        pass

    # 方法 C: 用 ShowWindow 恢复最小化的窗口
    try:
        from wechat_window_utils import restore_wechat_windows
        restore_wechat_windows()
    except Exception:
        pass

    # 4. 轮询等待窗口出现（必须 >= 500x400 才算主窗口恢复）
    start_time = time.time()
    while time.time() - start_time < max_wait:
        time.sleep(1.0)
        window = find_wechat_window()
        if window and window["width"] >= 500 and window["height"] >= 400:
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


# ── 并发锁（修复 P1-4：防止 wechat_send / wechat_ocr 并发执行互相干扰）──
import threading
_wechat_op_lock = threading.Lock()


# ── 联系人解析（name → 微信号 alias）────────────────────────────

def _resolve_contact(name: str) -> dict:
    """解析联系人标识符，返回唯一的微信号（alias）用于搜索。

    微信号的唯一性保证搜索结果准确，避免按昵称搜索时出现重名（如 'h'、'Y' 等）。

    查找顺序（逐步精确匹配，非模糊搜索）：
    1. 精确匹配 alias（微信号）—— 微信号唯一，直接使用
    2. 精确匹配 id（wxid）—— wxid 唯一，取该记录的 alias
    3. 精确匹配 display_name / nickname / remark —— 可能重名

    匹配规则：
    - 若第 1/2 步命中：直接返回（唯一）
    - 若第 3 步命中且仅 1 条：返回该记录
    - 若第 3 步命中多条：拒绝发送，返回所有匹配项供 Agent 决策
    - 若全部未命中：返回 CONTACT_NOT_FOUND

    Args:
        name: 联系人标识符（微信号 / wxid / 昵称 / 备注名 均可）

    Returns:
        dict: {
            "success": bool,
            "search_term": str,       # 用于微信搜索的关键词（优先 alias）
            "display_name": str,      # 用于头像模板查找的名称
            "alias": str|None,        # 微信号（可能为空）
            "id": str,                # wxid
            "matches": list[dict],    # 匹配的联系人列表（多匹配时用于错误信息）
            "match_count": int,       # 匹配数量
            "error": str|None,        # 错误类型
            "message": str,           # 描述信息
        }
    """
    import sqlite3

    DB_PATH = os.path.join(_PROJECT_ROOT, "data", "raw", "core.db")
    if not os.path.exists(DB_PATH):
        return {
            "success": False,
            "search_term": name,
            "display_name": name,
            "alias": None,
            "id": "",
            "matches": [],
            "match_count": 0,
            "error": "DATABASE_NOT_FOUND",
            "message": f"联系人数据库不存在: {DB_PATH}",
        }

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    try:
        # 步骤 1: 精确匹配 alias（微信号）
        cur.execute(
            "SELECT id, nickname, remark, alias, display_name FROM contacts "
            "WHERE alias = ?",
            (name,),
        )
        rows = cur.fetchall()
        if len(rows) == 1:
            row = rows[0]
            alias = row["alias"]
            display_name = row["display_name"] or row["nickname"] or name
            return {
                "success": True,
                "search_term": alias,  # 用微信号搜索
                "display_name": display_name,
                "alias": alias,
                "id": row["id"],
                "matches": [],
                "match_count": 1,
                "error": None,
                "message": f"通过微信号匹配到联系人: {display_name}",
            }
        if len(rows) > 1:
            # 微信号重复（极罕见），也拒绝
            matches = [
                {"id": r["id"], "display_name": r["display_name"],
                 "alias": r["alias"], "nickname": r["nickname"]}
                for r in rows
            ]
            return {
                "success": False,
                "search_term": name,
                "display_name": name,
                "alias": None,
                "id": "",
                "matches": matches,
                "match_count": len(matches),
                "error": "MULTIPLE_MATCHES",
                "message": f"微信号 {name!r} 匹配到 {len(matches)} 个联系人（微信号重复），拒绝发送",
            }

        # 步骤 2: 精确匹配 id（wxid）
        cur.execute(
            "SELECT id, nickname, remark, alias, display_name FROM contacts "
            "WHERE id = ?",
            (name,),
        )
        rows = cur.fetchall()
        if len(rows) == 1:
            row = rows[0]
            alias = row["alias"]
            display_name = row["display_name"] or row["nickname"] or name
            # 如果有微信号，用微信号搜索；否则用 display_name
            search_term = alias if alias else display_name
            return {
                "success": True,
                "search_term": search_term,
                "display_name": display_name,
                "alias": alias if alias else None,
                "id": row["id"],
                "matches": [],
                "match_count": 1,
                "error": None,
                "message": (
                    f"通过 wxid 匹配到联系人: {display_name}"
                    + (f"（使用微信号 {alias} 搜索）" if alias else "（无微信号，使用昵称搜索）")
                ),
            }

        # 步骤 3: 精确匹配 display_name / nickname / remark
        cur.execute(
            "SELECT id, nickname, remark, alias, display_name FROM contacts "
            "WHERE display_name = ? OR nickname = ? OR remark = ?",
            (name, name, name),
        )
        rows = cur.fetchall()
        if len(rows) == 0:
            return {
                "success": False,
                "search_term": name,
                "display_name": name,
                "alias": None,
                "id": "",
                "matches": [],
                "match_count": 0,
                "error": "CONTACT_NOT_FOUND",
                "message": f"在数据库中未找到匹配 {name!r} 的联系人",
            }
        if len(rows) == 1:
            row = rows[0]
            alias = row["alias"]
            display_name = row["display_name"] or row["nickname"] or name
            search_term = alias if alias else display_name
            return {
                "success": True,
                "search_term": search_term,
                "display_name": display_name,
                "alias": alias if alias else None,
                "id": row["id"],
                "matches": [],
                "match_count": 1,
                "error": None,
                "message": (
                    f"通过昵称匹配到联系人: {display_name}"
                    + (f"（使用微信号 {alias} 搜索）" if alias else "（无微信号，使用昵称搜索）")
                ),
            }
        # 多匹配：拒绝发送
        matches = [
            {"id": r["id"], "display_name": r["display_name"],
             "alias": r["alias"], "nickname": r["nickname"]}
            for r in rows
        ]
        return {
            "success": False,
            "search_term": name,
            "display_name": name,
            "alias": None,
            "id": "",
            "matches": matches,
            "match_count": len(matches),
            "error": "MULTIPLE_MATCHES",
            "message": (
                f"昵称 {name!r} 匹配到 {len(matches)} 个联系人，"
                f"无法确定发送对象，拒绝发送。"
                f"请使用微信号（alias）或 wxid 重新调用。"
                f"匹配列表: {', '.join(m['display_name'] + '(' + (m['alias'] or m['id']) + ')' for m in matches)}"
            ),
        }
    finally:
        conn.close()


# ── 工具1: wechat_send ──────────────────────────────────────────

def wechat_send(name: str, message: str) -> dict:
    """向微信联系人自动发送消息。

    通过视觉识别自动化操作微信 PC 客户端：
    1. 解析联系人标识符 → 微信号（alias）用于搜索（微信号唯一，避免重名）
    2. 搜索联系人（需 data/avatars/<display_name>.jpg 头像模板）
    3. 点击头像进入聊天界面
    4. 输入消息并点击发送

    如果微信进程在运行但主窗口不可见（最小化到托盘），
    会自动启动新 Weixin.exe 进程触发已运行实例显示主窗口。

    联系人解析逻辑（保证搜索唯一性）：
    - name 可以是：微信号(alias)、wxid、昵称、备注名
    - 优先用微信号搜索（唯一），无微信号时回退到昵称搜索
    - 若按昵称匹配到多个联系人 → 拒绝发送，返回匹配列表
    - 示例：wechat_send('[REDACTED]', '你好') → 数据库查找 [REDACTED] 的微信号 → 用微信号搜索

    Args:
        name: 微信联系人标识符（微信号 / wxid / 昵称 / 备注名 均可）
        message: 要发送的消息内容

    Returns:
        dict: {
            "success": bool,
            "message": str,        # 结果描述
            "contact": str,        # 联系人显示名
            "search_term": str,    # 实际用于搜索的关键词（微信号或昵称）
            "template": str,       # 模板路径
            "attempts": int,       # 尝试次数（成功时）
            "error": str|None,     # 失败原因
            "window_restored": bool,  # 是否触发了窗口恢复
            "matches": list|None,  # 多匹配时的联系人列表（仅 MULTIPLE_MATCHES 时有值）
        }
    """
    _wechat_op_lock.acquire()
    try:
        # ── 步骤 1: 解析联系人，获取微信号 ──
        resolution = _resolve_contact(name)
        if not resolution["success"]:
            # 匹配失败（未找到 / 多匹配），拒绝发送
            return {
                "success": False,
                "message": resolution["message"],
                "contact": name,
                "search_term": name,
                "template": "",
                "attempts": 0,
                "error": resolution["error"],
                "window_restored": False,
                "matches": resolution["matches"] if resolution["match_count"] > 1 else None,
            }

        search_term = resolution["search_term"]   # 微信号（用于搜索）
        display_name = resolution["display_name"]  # 显示名（用于头像模板）
        alias = resolution["alias"]

        # ── 步骤 2: 定位头像模板（用 display_name 查找）──
        avatars_dir = os.path.join(_PROJECT_ROOT, "data", "avatars")
        template_path = os.path.join(avatars_dir, f"{display_name}.jpg")

        # 如果原始名找不到，尝试安全文件名（emoji 等特殊字符被替换为 _）
        if not os.path.exists(template_path):
            safe_name = "".join(
                c if c.isalnum() or c in "._-" else "_" for c in display_name
            )[:50]
            safe_path = os.path.join(avatars_dir, f"{safe_name}.jpg")
            if os.path.exists(safe_path):
                template_path = safe_path

        if not os.path.exists(template_path):
            return {
                "success": False,
                "message": f"头像模板不存在: data/avatars/{display_name}.jpg",
                "contact": display_name,
                "search_term": search_term,
                "template": template_path,
                "attempts": 0,
                "error": "TEMPLATE_NOT_FOUND",
                "window_restored": False,
                "matches": None,
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
                "contact": display_name,
                "search_term": search_term,
                "template": template_path,
                "attempts": 0,
                "error": "WINDOW_NOT_AVAILABLE",
                "window_restored": window_restored,
                "matches": None,
            }

        # 导入端到端流程
        from engine.wechat_sender.wechat_e2e_run import run_e2e

        # 执行端到端发送（用微信号 search_term 搜索，用 template_path 匹配头像）
        success = run_e2e(message, search_term, template_path)

        if success:
            msg = f"消息已成功发送给 {display_name}"
            if alias:
                msg += f"（微信号: {alias}）"
            if window_restored:
                msg += "（已自动恢复微信窗口）"
            return {
                "success": True,
                "message": msg,
                "contact": display_name,
                "search_term": search_term,
                "template": template_path,
                "attempts": 1,
                "error": None,
                "window_restored": window_restored,
                "matches": None,
            }
        else:
            return {
                "success": False,
                "message": f"发送失败（端到端流程未成功，详见日志）",
                "contact": display_name,
                "search_term": search_term,
                "template": template_path,
                "attempts": 4,
                "error": "E2E_FLOW_FAILED",
                "window_restored": window_restored,
                "matches": None,
            }

    except ImportError as e:
        return {
            "success": False,
            "message": f"依赖模块导入失败: {e}",
            "contact": name,
            "search_term": name,
            "template": "",
            "attempts": 0,
            "error": "IMPORT_ERROR",
            "window_restored": False,
            "matches": None,
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"运行异常: {e}",
            "contact": name,
            "search_term": name,
            "template": "",
            "attempts": 0,
            "error": f"RUNTIME_ERROR: {traceback.format_exc()}",
            "window_restored": False,
            "matches": None,
        }
    finally:
        _wechat_op_lock.release()


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
    _wechat_op_lock.acquire()
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
    finally:
        _wechat_op_lock.release()
