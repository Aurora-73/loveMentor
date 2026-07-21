"""微信自动发消息 MCP 工具（薄包装层）。

本模块只做 MCP 工具注册和并发控制，所有业务逻辑都在 engine/wechat_sender/ 中：
- 窗口管理：engine/wechat_sender/ensure_window.py
- 联系人解析：engine/wechat_sender/contact_profile.py
- 消息发送：engine/wechat_sender/wechat_e2e_run.py (send_message_with_retry)
- OCR 识别：engine/wechat_sender/wechat_ocr.py
- 录屏包装：engine/wechat_sender/wechat_recorder.py (with_recording)

前置条件：
- 微信（Weixin.exe）已运行并登录
- 依赖：OpenCV, numpy, PIL（已随项目安装）
"""

import os
import sys
import logging
import threading
import traceback

logger = logging.getLogger(__name__)

# 确保项目根目录在 sys.path 中
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# wechat_sender 内部用绝对导入（from dynamic_detector import ...），
# 需要把该目录加入 sys.path
_WECHAT_SENDER_DIR = os.path.join(_PROJECT_ROOT, "engine", "wechat_sender")
if _WECHAT_SENDER_DIR not in sys.path:
    sys.path.insert(0, _WECHAT_SENDER_DIR)


# ── 并发锁（防止 wechat_send / wechat_ocr 并发执行互相干扰）──
_wechat_op_lock = threading.Lock()


# ── 工具1: wechat_send ──────────────────────────────────────────

def wechat_send(name: str, message: str) -> dict:
    """向微信联系人自动发送消息。

    通过视觉识别自动化操作微信 PC 客户端：
    1. 解析联系人标识符 → 微信号（alias）用于搜索和头像定位（微信号唯一，避免重名）
    2. 搜索联系人（需 data/avatars/<wxid>.jpg 头像模板）
    3. 点击头像进入聊天界面
    4. 输入消息并点击发送

    如果微信进程在运行但主窗口不可见（最小化到托盘），会自动恢复窗口。

    联系人解析逻辑（保证搜索唯一性）：
    - name 可以是：微信号(alias)、wxid、昵称、备注名
    - 优先用微信号搜索（唯一），无微信号时回退到昵称搜索
    - 若按昵称匹配到多个联系人 → 拒绝发送，返回匹配列表
    - 示例：wechat_send('[REDACTED]', '你好') → 数据库查找 [REDACTED] 的微信号 → 用微信号搜索

    头像定位逻辑（重要：用 wxid 而非显示名）：
    - 头像模板文件名用 wxid（唯一，不会冲突）
    - 本地有 <wxid>.jpg → 直接用
    - 本地无 <wxid>.jpg → 立即调用 avatar_fetcher 获取并保存

    录屏功能（诊断失败用）：
    - 每次操作前自动开始录屏（BitBlt + OpenCV VideoWriter，5 FPS）
    - 操作成功 → 自动删除录屏
    - 操作失败 → 保留录屏 7 天，路径在返回值的 recording_path 字段
    - 录屏路径：data/outputs/recordings/wechat_send_<timestamp>_<contact>.mp4
    - ⚠️ 录屏文件在 data/ 目录下，已被 .gitignore 忽略，不会提交到 git

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
            "recording_path": str|None,  # 失败时的录屏文件路径（成功时为 None）
        }
    """
    from engine.wechat_sender.wechat_recorder import with_recording
    from engine.wechat_sender.wechat_e2e_run import send_message_with_retry

    def _impl():
        _wechat_op_lock.acquire()
        try:
            return send_message_with_retry(name, message)
        finally:
            _wechat_op_lock.release()

    return with_recording(name, _impl)


# ── 工具2: open_wechat_window ───────────────────────────────────

def open_wechat_window(timeout: float = 10.0) -> dict:
    """在微信已启动但窗口不可见（被关闭/最小化到托盘）时，唤醒主窗口。

    通过点击任务栏右下角托盘的微信绿色图标唤醒主窗口。
    实现：HSV颜色匹配托盘区域 → 物理点击图标 → 轮询等待窗口出现。
    基于录屏分析：闪烁周期约1.867秒，常态下图标稳定绿色，单次截图即可匹配。

    使用场景：
    - wechat_send 失败提示"微信窗口未打开"时，先调用本工具唤醒窗口
    - 主动唤醒微信窗口进行 OCR 或其他操作

    前置条件：微信进程已启动（Weixin.exe 在运行）。

    Args:
        timeout: 等待窗口出现的最大秒数，默认 10.0

    Returns:
        dict: {
            "success": bool,
            "message": str,
            "action": str,  # "already_visible" / "tray_click" / "failed"
            "window": dict|None,  # {"hwnd": int, "width": int, "height": int}
            "elapsed": float|None,
            "error": str|None,
            "recording_path": str|None,  # 失败时的录屏文件路径（成功时为 None）
        }
    """
    from engine.wechat_sender.wechat_recorder import with_recording
    from engine.wechat_sender.ensure_window import wake_wechat_window

    def _impl():
        _wechat_op_lock.acquire()
        try:
            return wake_wechat_window(timeout=timeout)
        finally:
            _wechat_op_lock.release()

    return with_recording("open_wechat_window", _impl)


# ── 工具3: wechat_ocr ───────────────────────────────────────────

def wechat_ocr(region: str = "full", use_cache: bool = False) -> dict:
    """截图微信窗口并进行 OCR 文字识别。

    对当前微信主窗口截图，用 RapidOCR 识别文字，返回带位置信息的结果。
    适用于：读取聊天界面文字、提取联系人信息、识别界面元素等场景。

    录屏功能：操作前自动开始录屏，成功删除，失败保留 7 天（路径在 recording_path 字段）。

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
            "recording_path": str|None,  # 失败时的录屏文件路径（成功时为 None）
        }

        texts 中每个元素: {
            "text": str,               # 文字内容
            "bbox": [[x1,y1], [x2,y2], [x3,y3], [x4,y4]],  # 四顶点坐标
            "confidence": float,       # 置信度
            "center": [x, y],          # 中心坐标
        }
    """
    from engine.wechat_sender.wechat_recorder import with_recording
    from engine.wechat_sender.wechat_ocr import ocr_wechat_window

    def _impl():
        _wechat_op_lock.acquire()
        try:
            return ocr_wechat_window(region=region, use_cache=use_cache)
        finally:
            _wechat_op_lock.release()

    return with_recording("wechat_ocr", _impl)


# ── 工具4: wechat_send_emoji ─────────────────────────────────────

def wechat_send_emoji(name: str, emoji_keyword: str) -> dict:
    """向微信联系人自动发送表情包。

    通过视觉识别自动化操作微信 PC 客户端：
    1. 解析联系人标识符 → 微信号（alias）用于搜索和头像定位（与 wechat_send 相同）
    2. 搜索联系人（需 data/avatars/<wxid>.jpg 头像模板）
    3. 点击头像进入聊天界面
    4. 点击表情按钮 → 打开表情面板（独立小窗口）
    5. 点击表情搜索键 → 输入关键词 → 点击搜索结果中的第一个表情（直接发送）

    与 wechat_send 的区别：
    - 阶段一/二完全相同（搜索联系人 + 点击头像 + 验证）
    - 阶段三不同：不输入文字，而是通过表情面板搜索并发送表情包
    - 表情面板是独立小窗口（类似搜索候选框），不是主窗口的一部分
    - 点击表情搜索结果会直接发送，无需点击发送按钮

    如果微信进程在运行但主窗口不可见（最小化到托盘），会自动恢复窗口。

    Args:
        name: 微信联系人标识符（微信号 / wxid / 昵称 / 备注名 均可）
        emoji_keyword: 表情搜索关键词（如 "猫猫"、"感谢"、"开心"、"晚安"）

    Returns:
        dict: {
            "success": bool,
            "message": str,        # 结果描述
            "contact": str,        # 联系人显示名
            "search_term": str,    # 实际用于搜索的关键词（微信号或昵称）
            "template": str,       # 头像模板路径
            "attempts": int,       # 尝试次数（成功时）
            "error": str|None,     # 失败原因
            "window_restored": bool,  # 是否触发了窗口恢复
            "matches": list|None,  # 多匹配时的联系人列表
            "recording_path": str|None,  # 失败时的录屏文件路径（成功时为 None）
        }
    """
    from engine.wechat_sender.wechat_recorder import with_recording
    from engine.wechat_sender.wechat_e2e_run import send_emoji_with_retry

    def _impl():
        _wechat_op_lock.acquire()
        try:
            return send_emoji_with_retry(name, emoji_keyword)
        finally:
            _wechat_op_lock.release()

    return with_recording(name, _impl)
