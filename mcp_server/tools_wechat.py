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
import traceback
import yaml
from datetime import datetime, timedelta
from typing import Optional

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
# v4 升级：从 threading.Lock（进程内）改为 CrossProcessLock（跨进程 Win32 Named Mutex）
# 防止 Agent 进程 + 其他工具进程同时调用 wechat_send 导致视觉自动化冲突
# 进程崩溃时 Windows 自动释放锁（WAIT_ABANDONED 机制），避免死锁
from cross_process_lock import CrossProcessLock
_wechat_op_lock = CrossProcessLock("loveMentor_wechat_op")

# ── 发送状态文件（记录 last_send_time，用于回复冷却校验）──
_SEND_STATE_FILE = os.path.join(_PROJECT_ROOT, "data", "system", "wechat_send_state.yaml")

# ── 按关系阶段的最小冷却秒数（v4 5.3 节）──
# Stage 1-2 初识/基本互动: 30 分钟（低频聊天，秒回显得需求感强）
# Stage 3 高频聊天: 5 分钟（高频但不秒回）
# Stage 4+ 已约见/持续接触: 3 分钟（稳定关系可稍快）
_STAGE_COOLDOWN_SECONDS = {
    1: 1800,
    2: 1800,
    3: 300,
    4: 180,
    5: 180,
}
_DEFAULT_COOLDOWN = 300  # 默认 5 分钟（阶段未知时）


def _load_send_state() -> dict:
    """加载发送状态文件。"""
    if not os.path.exists(_SEND_STATE_FILE):
        return {"last_send_times": {}, "last_updated": None}
    try:
        with open(_SEND_STATE_FILE, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {"last_send_times": {}, "last_updated": None}
    except Exception as e:
        logger.warning(f"send_state 加载失败: {e}")
        return {"last_send_times": {}, "last_updated": None}


def _save_send_state(state: dict) -> None:
    """保存发送状态文件。"""
    state["last_updated"] = datetime.now().isoformat(timespec="seconds")
    os.makedirs(os.path.dirname(_SEND_STATE_FILE), exist_ok=True)
    with open(_SEND_STATE_FILE, "w", encoding="utf-8") as f:
        yaml.dump(state, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def _get_person_stage_num(name: str) -> int:
    """获取联系人的关系阶段数字（1-5）。失败返回 3（默认高频聊天阶段）。

    阶段文本标签 → 数字映射（基于 engine.analyzers.stage_recognizer）：
      "初识" → 1
      "基本互动" → 2
      "高频聊天" → 3
      "已约见" → 4
      "持续接触" / "稳定关系" → 5
      其他 → 默认 3
    """
    try:
        from engine.tools import _resolve
        from engine.analyzers.stage_recognizer import recognize_stage
        conn, config, person = _resolve(name)
        try:
            result = recognize_stage(conn, config, person)
            stage_label = (result.current_stage or "").strip()
            return _STAGE_LABEL_TO_NUM.get(stage_label, 3)
        finally:
            conn.close()
    except Exception as e:
        logger.debug(f"获取阶段失败 {name}: {e}，使用默认阶段 3")
    return 3


# 阶段文本标签 → 数字映射
_STAGE_LABEL_TO_NUM = {
    "初识": 1,
    "基本互动": 2,
    "高频聊天": 3,
    "已约见": 4,
    "持续接触": 5,
    "稳定关系": 5,
    "暧昧": 3,        # 暧昧归入高频聊天
    "约会": 4,        # 约会归入已约见
}


def _check_user_took_over(name: str) -> dict:
    """硬约束 0：用户介入取消校验（v4 7.8.2 节）。

    检查 conversation_thread.user_took_over 是否为 True。
    若用户已手动接管，拒绝发送。

    Returns:
        dict: {"passed": bool, "reason": str}
    """
    try:
        from mcp_server.tools_thread import conversation_thread

        thread_result = conversation_thread(action="get", name=name)
        if "error" in thread_result:
            # 线索文件不存在，视为通过（首次发送无线索）
            return {"passed": True, "reason": "线索文件不存在，跳过校验"}

        thread = thread_result.get("thread", {})
        if thread.get("user_took_over", False):
            took_over_time = thread.get("user_took_over_time", "未知时间")
            return {
                "passed": False,
                "reason": f"用户已手动接管（{took_over_time}），自动回复已暂停",
                "suggestion": f"用户可通过 talk.md 写入 '恢复 {name} 的自动回复' 清除接管状态",
            }
        return {"passed": True, "reason": "用户未接管"}
    except Exception as e:
        logger.warning(f"用户接管校验异常 {name}: {e}，跳过校验")
        return {"passed": True, "reason": f"校验异常，跳过: {e}"}


def _check_thread_read(name: str) -> dict:
    """硬约束 1：校验对话线索已读（v4 6.4 节）。

    检查 conversation_thread 的 last_processed_message_id 是否 >= 数据库中最新消息 ID。
    若未读取最新消息，返回需 catch_up 的错误。

    Returns:
        dict: {"passed": bool, "reason": str, "unprocessed_count": int}
    """
    try:
        from mcp_server.tools_thread import conversation_thread

        # 获取线索文件
        thread_result = conversation_thread(action="get", name=name)
        if "error" in thread_result:
            # 线索文件不存在，视为通过（首次发送无线索）
            return {"passed": True, "reason": "线索文件不存在，跳过校验", "unprocessed_count": 0}

        thread = thread_result.get("thread", {})
        last_processed_id = thread.get("last_processed_message_id", 0)

        # 获取数据库中最新消息 ID
        # 通过 chat_data 拿最近 1 条消息
        try:
            from engine.tools import chat_data
            data = chat_data(name, recent=1)
            messages = data.get("messages", [])
            if not messages:
                return {"passed": True, "reason": "无消息记录", "unprocessed_count": 0}
            latest_msg = messages[-1]
            latest_msg_id = int(latest_msg.get("id", 0) or 0)

            if last_processed_id >= latest_msg_id:
                return {"passed": True, "reason": "线索已读", "unprocessed_count": 0}
            else:
                unprocessed = latest_msg_id - last_processed_id
                return {
                    "passed": False,
                    "reason": f"尚未处理 {unprocessed} 条新消息",
                    "unprocessed_count": unprocessed,
                    "last_processed_message_id": last_processed_id,
                    "latest_message_id": latest_msg_id,
                    "suggestion": f"请先调用 conversation_thread(action='catch_up', name='{name}')",
                }
        except Exception as e:
            logger.warning(f"获取最新消息 ID 失败 {name}: {e}，跳过线索校验")
            return {"passed": True, "reason": f"获取最新消息失败，跳过校验: {e}", "unprocessed_count": 0}
    except Exception as e:
        logger.warning(f"线索已读校验异常 {name}: {e}，跳过校验")
        return {"passed": True, "reason": f"校验异常，跳过: {e}", "unprocessed_count": 0}


def _check_cooldown(name: str, urgent: bool, stage: int) -> dict:
    """硬约束 2：回复冷却校验（v4 5.3 节）。

    按阶段最小冷却：Stage 1-2: 30min, Stage 3: 5min, Stage 4+: 3min。
    urgent=True 时绕过冷却。

    Returns:
        dict: {"passed": bool, "reason": str, "wait_seconds": float}
    """
    if urgent:
        return {"passed": True, "reason": "urgent=True 绕过冷却", "wait_seconds": 0}

    cooldown = _STAGE_COOLDOWN_SECONDS.get(stage, _DEFAULT_COOLDOWN)
    state = _load_send_state()
    last_send_times = state.get("last_send_times", {})
    last_send_str = last_send_times.get(name)

    if not last_send_str:
        return {"passed": True, "reason": "无历史发送记录", "wait_seconds": 0}

    try:
        last_send = datetime.fromisoformat(last_send_str)
    except (ValueError, TypeError):
        return {"passed": True, "reason": "历史记录格式异常", "wait_seconds": 0}

    elapsed = (datetime.now() - last_send).total_seconds()
    if elapsed >= cooldown:
        return {"passed": True, "reason": "冷却已过", "wait_seconds": 0}

    wait = cooldown - elapsed
    return {
        "passed": False,
        "reason": f"回复冷却中，还需等待 {wait:.0f} 秒",
        "wait_seconds": wait,
        "cooldown_seconds": cooldown,
        "elapsed_seconds": elapsed,
        "stage": stage,
    }


def _update_send_time(name: str) -> None:
    """发送成功后更新 last_send_time。"""
    state = _load_send_state()
    if "last_send_times" not in state:
        state["last_send_times"] = {}
    state["last_send_times"][name] = datetime.now().isoformat(timespec="seconds")
    _save_send_state(state)


# ── 工具1: wechat_send ──────────────────────────────────────────

def wechat_send(name: str, message: str, urgent: bool = False) -> dict:
    """向微信联系人自动发送消息（v4 三重硬约束）。

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

    v4 三重硬约束（5.3 + 6.4 节，发送前自动校验）：
    1. 线索已读校验：conversation_thread.last_processed_message_id >= 数据库最新消息 ID
       - 未读取最新消息时拒绝发送，返回 suggestion 调用 catch_up
       - 线索文件不存在或读取异常时跳过校验（兼容首次发送）
    2. 回复冷却校验：按关系阶段最小冷却（Stage 1-2: 30min / Stage 3: 5min / Stage 4+: 3min）
       - urgent=True 时绕过冷却（用于对方连续追问等紧急场景）
       - 冷却中拒绝发送，返回 wait_seconds 告知剩余等待时间
    3. 互斥锁校验：视觉自动化串行（原有逻辑保留）

    Args:
        name: 微信联系人标识符（微信号 / wxid / 昵称 / 备注名 均可）
        message: 要发送的消息内容
        urgent: 紧急模式（True 时绕过回复冷却校验，但仍然校验线索已读）。
                用于对方连续追问"在吗"等需要立即响应的场景。

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
            "hard_constraints": dict,  # v4 新增：三重硬约束校验结果
                # {"thread_read": "passed"/"failed", "cooldown": "passed"/"failed"/"bypassed",
                #  "mutex": "passed", "stage": int, "urgent": bool}
        }
    """
    from engine.wechat_sender.wechat_recorder import with_recording
    from engine.wechat_sender.wechat_e2e_run import send_message_with_retry

    # v4 硬约束 0：用户介入取消校验（7.8.2 节，最高优先级）
    took_over_check = _check_user_took_over(name)
    if not took_over_check["passed"]:
        return {
            "success": False,
            "error": "USER_TOOK_OVER",
            "message": took_over_check["reason"],
            "suggestion": took_over_check.get("suggestion", ""),
            "hard_constraints": {
                "user_took_over": "failed",
                "thread_read": "skipped",
                "cooldown": "skipped",
                "mutex": "skipped",
                "urgent": urgent,
            },
        }

    # v4 硬约束 1：校验线索已读（urgent 也不能绕过，因为这是安全要求）
    thread_check = _check_thread_read(name)
    if not thread_check["passed"]:
        return {
            "success": False,
            "error": "THREAD_NOT_CAUGHT_UP",
            "message": f"线索未读取最新消息：{thread_check['reason']}",
            "suggestion": thread_check.get("suggestion", ""),
            "unprocessed_count": thread_check.get("unprocessed_count", 0),
            "hard_constraints": {
                "user_took_over": "passed",
                "thread_read": "failed",
                "cooldown": "skipped",
                "mutex": "skipped",
                "urgent": urgent,
            },
        }

    # v4 硬约束 2：回复冷却校验（urgent 可绕过）
    stage = _get_person_stage_num(name)
    cooldown_check = _check_cooldown(name, urgent=urgent, stage=stage)
    if not cooldown_check["passed"]:
        return {
            "success": False,
            "error": "COOLDOWN_ACTIVE",
            "message": cooldown_check["reason"],
            "wait_seconds": cooldown_check.get("wait_seconds", 0),
            "cooldown_seconds": cooldown_check.get("cooldown_seconds", 0),
            "elapsed_seconds": cooldown_check.get("elapsed_seconds", 0),
            "stage": stage,
            "suggestion": "等待冷却结束后重试，或使用 urgent=True 绕过（仅紧急情况）",
            "hard_constraints": {
                "user_took_over": "passed",
                "thread_read": "passed",
                "cooldown": "failed",
                "mutex": "skipped",
                "stage": stage,
                "urgent": urgent,
            },
        }

    # v4 硬约束 3：互斥锁（原有逻辑）+ 正常发送流程
    def _impl():
        _wechat_op_lock.acquire()
        try:
            return send_message_with_retry(name, message)
        finally:
            _wechat_op_lock.release()

    result = with_recording(name, _impl)

    # 发送成功后更新 last_send_time（用于下次冷却校验）
    if result.get("success"):
        _update_send_time(name)

    # 附加硬约束校验结果到返回值
    result["hard_constraints"] = {
        "user_took_over": "passed",
        "thread_read": "passed",
        "cooldown": "bypassed" if urgent else "passed",
        "mutex": "passed" if result.get("success") else "passed",  # 互斥锁本身总是 passed（获取成功）
        "stage": stage,
        "urgent": urgent,
    }

    return result


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


def wechat_send_image(name: str, image_path: str, urgent: bool = False) -> dict:
    """向微信联系人自动发送图片（v4 第十六章多媒体发送能力 + 三重硬约束）。

    技术方案（v4 16.2 节）：复用文本发送的剪贴板机制，把剪贴板内容从文字换成图片。
    流程：
    1. 解析联系人 → 微信号搜索 + 头像定位（与 wechat_send 相同）
    2. 搜索联系人 + 点击头像进入聊天界面（阶段一/二与 wechat_send 相同）
    3. 阶段三：点击输入框 → 剪贴板放图片 → Ctrl+V → 微信显示预览 → 点击发送

    与 wechat_send 的区别：
    - 阶段一/二完全相同（搜索联系人 + 点击头像 + 验证）
    - 阶段三不同：不输入文字，而是通过剪贴板粘贴图片
    - 图片预览加载比文字慢，等待时间更长（1.5s vs 0.8s）
    - 验证方式不同：用发送按钮颜色变化判断（无法用 OCR 文字验证）

    支持的图片格式：jpg/jpeg/png/bmp/gif/webp/tiff

    v4 三重硬约束（与 wechat_send 相同）：
    1. 线索已读校验：未读取最新消息时拒绝发送
    2. 回复冷却校验：urgent=True 可绕过
    3. 互斥锁校验：视觉自动化串行

    Args:
        name: 微信联系人标识符（微信号 / wxid / 昵称 / 备注名 均可）
        image_path: 图片文件路径（支持 jpg/jpeg/png/bmp/gif/webp/tiff）
        urgent: 紧急模式（True 时绕过回复冷却校验，但仍然校验线索已读）。

    Returns:
        dict: {
            "success": bool,
            "message": str,
            "contact": str,
            "search_term": str,
            "template": str,
            "attempts": int,
            "error": str|None,
            "window_restored": bool,
            "matches": list|None,
            "recording_path": str|None,
            "hard_constraints": dict,  # 三重硬约束校验结果
        }
    """
    import os as _os
    from engine.wechat_sender.wechat_recorder import with_recording
    from engine.wechat_sender.wechat_e2e_run import send_image_with_retry

    # 前置检查：图片文件
    if not image_path or not _os.path.exists(image_path):
        return {
            "success": False,
            "error": "IMAGE_NOT_FOUND",
            "message": f"图片文件不存在: {image_path}",
            "contact": name,
            "search_term": name,
            "template": "",
            "attempts": 0,
            "window_restored": False,
            "matches": None,
            "recording_path": None,
            "hard_constraints": {
                "user_took_over": "skipped",
                "thread_read": "skipped",
                "cooldown": "skipped",
                "mutex": "skipped",
                "urgent": urgent,
            },
        }

    # v4 硬约束 0：用户介入取消校验（7.8.2 节，最高优先级）
    took_over_check = _check_user_took_over(name)
    if not took_over_check["passed"]:
        return {
            "success": False,
            "error": "USER_TOOK_OVER",
            "message": took_over_check["reason"],
            "suggestion": took_over_check.get("suggestion", ""),
            "hard_constraints": {
                "user_took_over": "failed",
                "thread_read": "skipped",
                "cooldown": "skipped",
                "mutex": "skipped",
                "urgent": urgent,
            },
        }

    # v4 硬约束 1：校验线索已读
    thread_check = _check_thread_read(name)
    if not thread_check["passed"]:
        return {
            "success": False,
            "error": "THREAD_NOT_CAUGHT_UP",
            "message": f"线索未读取最新消息：{thread_check['reason']}",
            "suggestion": thread_check.get("suggestion", ""),
            "unprocessed_count": thread_check.get("unprocessed_count", 0),
            "hard_constraints": {
                "user_took_over": "passed",
                "thread_read": "failed",
                "cooldown": "skipped",
                "mutex": "skipped",
                "urgent": urgent,
            },
        }

    # v4 硬约束 2：回复冷却校验
    stage = _get_person_stage_num(name)
    cooldown_check = _check_cooldown(name, urgent=urgent, stage=stage)
    if not cooldown_check["passed"]:
        return {
            "success": False,
            "error": "COOLDOWN_ACTIVE",
            "message": cooldown_check["reason"],
            "wait_seconds": cooldown_check.get("wait_seconds", 0),
            "cooldown_seconds": cooldown_check.get("cooldown_seconds", 0),
            "elapsed_seconds": cooldown_check.get("elapsed_seconds", 0),
            "stage": stage,
            "suggestion": "等待冷却结束后重试，或使用 urgent=True 绕过（仅紧急情况）",
            "hard_constraints": {
                "user_took_over": "passed",
                "thread_read": "passed",
                "cooldown": "failed",
                "mutex": "skipped",
                "stage": stage,
                "urgent": urgent,
            },
        }

    # v4 硬约束 3：互斥锁 + 正常发送流程
    def _impl():
        _wechat_op_lock.acquire()
        try:
            return send_image_with_retry(name, image_path)
        finally:
            _wechat_op_lock.release()

    result = with_recording(name, _impl)

    # 发送成功后更新 last_send_time
    if result.get("success"):
        _update_send_time(name)

    result["hard_constraints"] = {
        "user_took_over": "passed",
        "thread_read": "passed",
        "cooldown": "bypassed" if urgent else "passed",
        "mutex": "passed",
        "stage": stage,
        "urgent": urgent,
    }

    return result


def wechat_send_file(name: str, file_path: str, urgent: bool = False) -> dict:
    """向微信联系人自动发送文件/视频（v4 第十六章多媒体发送能力扩展 + 三重硬约束）。

    技术方案（用户指导）：
    "视频和文件的逻辑是一样的，都是复制粘贴然后发送，就是 explorer 里的那种复制，
     然后就可以粘贴到微信里"

    使用 CF_HDROP 剪贴板格式（模拟 Explorer 复制文件），微信自动识别文件类型：
    - 视频（mp4/mov/avi/mkv/flv/wmv/m4v/3gp）→ 发送为视频
    - 其他文件（pdf/doc/zip 等）→ 发送为文件

    与 wechat_send_image 的区别：
    - 剪贴板格式：CF_HDROP（文件拖放）vs CF_DIB（位图）
    - 支持文件类型：视频 + 任意文件（不限图片）
    - 文件较大时等待时间更长（根据文件大小动态调整 2-4s）

    v4 三重硬约束（与 wechat_send 相同）：
    1. 线索已读校验：未读取最新消息时拒绝发送
    2. 回复冷却校验：urgent=True 可绕过
    3. 互斥锁校验：视觉自动化串行

    Args:
        name: 微信联系人标识符（微信号 / wxid / 昵称 / 备注名 均可）
        file_path: 文件路径（视频/文档/任意文件）
        urgent: 紧急模式（True 时绕过回复冷却校验，但仍然校验线索已读）。

    Returns:
        dict: {
            "success": bool,
            "message": str,
            "contact": str,
            "search_term": str,
            "template": str,
            "attempts": int,
            "error": str|None,
            "window_restored": bool,
            "matches": list|None,
            "recording_path": str|None,
            "hard_constraints": dict,
        }
    """
    import os as _os
    from engine.wechat_sender.wechat_recorder import with_recording
    from engine.wechat_sender.wechat_e2e_run import send_file_with_retry

    # 前置检查：文件存在
    if not file_path or not _os.path.exists(file_path):
        return {
            "success": False,
            "error": "FILE_NOT_FOUND",
            "message": f"文件不存在: {file_path}",
            "contact": name,
            "search_term": name,
            "template": "",
            "attempts": 0,
            "window_restored": False,
            "matches": None,
            "recording_path": None,
            "hard_constraints": {
                "user_took_over": "skipped",
                "thread_read": "skipped",
                "cooldown": "skipped",
                "mutex": "skipped",
                "urgent": urgent,
            },
        }

    # v4 硬约束 0：用户介入取消校验
    took_over_check = _check_user_took_over(name)
    if not took_over_check["passed"]:
        return {
            "success": False,
            "error": "USER_TOOK_OVER",
            "message": took_over_check["reason"],
            "suggestion": took_over_check.get("suggestion", ""),
            "hard_constraints": {
                "user_took_over": "failed",
                "thread_read": "skipped",
                "cooldown": "skipped",
                "mutex": "skipped",
                "urgent": urgent,
            },
        }

    # v4 硬约束 1：校验线索已读
    thread_check = _check_thread_read(name)
    if not thread_check["passed"]:
        return {
            "success": False,
            "error": "THREAD_NOT_CAUGHT_UP",
            "message": f"线索未读取最新消息：{thread_check['reason']}",
            "suggestion": thread_check.get("suggestion", ""),
            "unprocessed_count": thread_check.get("unprocessed_count", 0),
            "hard_constraints": {
                "user_took_over": "passed",
                "thread_read": "failed",
                "cooldown": "skipped",
                "mutex": "skipped",
                "urgent": urgent,
            },
        }

    # v4 硬约束 2：回复冷却校验
    stage = _get_person_stage_num(name)
    cooldown_check = _check_cooldown(name, urgent=urgent, stage=stage)
    if not cooldown_check["passed"]:
        return {
            "success": False,
            "error": "COOLDOWN_ACTIVE",
            "message": cooldown_check["reason"],
            "wait_seconds": cooldown_check.get("wait_seconds", 0),
            "cooldown_seconds": cooldown_check.get("cooldown_seconds", 0),
            "elapsed_seconds": cooldown_check.get("elapsed_seconds", 0),
            "stage": stage,
            "suggestion": "等待冷却结束后重试，或使用 urgent=True 绕过（仅紧急情况）",
            "hard_constraints": {
                "user_took_over": "passed",
                "thread_read": "passed",
                "cooldown": "failed",
                "mutex": "skipped",
                "stage": stage,
                "urgent": urgent,
            },
        }

    # v4 硬约束 3：互斥锁 + 正常发送流程
    def _impl():
        _wechat_op_lock.acquire()
        try:
            return send_file_with_retry(name, file_path)
        finally:
            _wechat_op_lock.release()

    result = with_recording(name, _impl)

    # 发送成功后更新 last_send_time
    if result.get("success"):
        _update_send_time(name)

    result["hard_constraints"] = {
        "user_took_over": "passed",
        "thread_read": "passed",
        "cooldown": "bypassed" if urgent else "passed",
        "mutex": "passed",
        "stage": stage,
        "urgent": urgent,
    }

    return result


# ── 工具4: wechat_send_batch ────────────────────────────────────

def wechat_send_batch(name: str, messages: list, urgent: bool = False) -> dict:
    """向同一联系人连续发送多条混合消息（v4 连续发送 + 混合消息能力 + 三重硬约束）。

    支持在一次调用中连续发送文字/表情/图片/视频/文件混合消息：
    - 第一条消息走完整流程（搜索+点击头像+发送）
    - 后续消息跳过搜索，直接在当前聊天界面发送
    - 每次发送前校验聊天框左上角显示名
    - 校验失败则回退到完整流程（重新搜索联系人）
    - 根据每条消息的 type 自动选择对应的发送函数

    消息格式（两种，可混用）：
    - 字符串：当作文字消息
    - 字典：{"type": "text"|"emoji"|"image"|"video"|"file", "content": "..."}
      - text: content 为消息文本
      - emoji: content 为表情搜索关键词（如"微笑"、"加油"）
      - image: content 为图片文件路径（支持 jpg/png/bmp 等常见格式）
      - video: content 为视频文件路径（支持 mp4/mov/avi 等，使用 CF_HDROP 剪贴板）
      - file: content 为任意文件路径（pdf/doc/zip 等，使用 CF_HDROP 剪贴板）

    示例：
        messages = [
            "你好",                                          # 文字（字符串简写）
            {"type": "text", "content": "今天天气不错"},     # 文字（字典形式）
            {"type": "emoji", "content": "微笑"},            # 表情
            {"type": "image", "content": "C:/pic.jpg"},      # 图片
            {"type": "video", "content": "C:/video.mp4"},    # 视频
            {"type": "file", "content": "C:/doc.pdf"},       # 文件
        ]

    适用场景：分段发送长文本、文字+表情混合、文字+图片/视频混合等。

    v4 三重硬约束（与 wechat_send 相同，只在第一条消息前校验一次）：
    1. 线索已读校验：未读取最新消息时拒绝发送
    2. 回复冷却校验：urgent=True 可绕过
    3. 互斥锁校验：整个批量发送过程串行

    Args:
        name: 微信联系人标识符（微信号 / wxid / 昵称 / 备注名 均可）
        messages: 要发送的消息列表（字符串或字典，可混用）
        urgent: 紧急模式（True 时绕过回复冷却校验，但仍然校验线索已读）。

    Returns:
        dict: {
            "success": bool,       # 全部成功=True，任一失败=False
            "message": str,        # 结果摘要
            "contact": str,
            "total": int,          # 总消息数
            "succeeded": int,      # 成功数
            "failed": int,         # 失败数
            "results": list[dict], # 每条消息的详细结果（含 type 字段）
            "error": str|None,
            "hard_constraints": dict,
        }
    """
    from engine.wechat_sender.wechat_recorder import with_recording
    from engine.wechat_sender.wechat_e2e_run import send_message_batch

    # 前置检查：消息列表
    if not messages:
        return {
            "success": False,
            "error": "EMPTY_MESSAGES",
            "message": "消息列表为空",
            "contact": name,
            "total": 0,
            "succeeded": 0,
            "failed": 0,
            "results": [],
            "hard_constraints": {
                "user_took_over": "skipped",
                "thread_read": "skipped",
                "cooldown": "skipped",
                "mutex": "skipped",
                "urgent": urgent,
            },
        }

    # v4 硬约束 0：用户介入取消校验
    took_over_check = _check_user_took_over(name)
    if not took_over_check["passed"]:
        return {
            "success": False,
            "error": "USER_TOOK_OVER",
            "message": took_over_check["reason"],
            "suggestion": took_over_check.get("suggestion", ""),
            "contact": name,
            "total": len(messages),
            "succeeded": 0,
            "failed": len(messages),
            "results": [],
            "hard_constraints": {
                "user_took_over": "failed",
                "thread_read": "skipped",
                "cooldown": "skipped",
                "mutex": "skipped",
                "urgent": urgent,
            },
        }

    # v4 硬约束 1：校验线索已读
    thread_check = _check_thread_read(name)
    if not thread_check["passed"]:
        return {
            "success": False,
            "error": "THREAD_NOT_CAUGHT_UP",
            "message": f"线索未读取最新消息：{thread_check['reason']}",
            "suggestion": thread_check.get("suggestion", ""),
            "unprocessed_count": thread_check.get("unprocessed_count", 0),
            "contact": name,
            "total": len(messages),
            "succeeded": 0,
            "failed": len(messages),
            "results": [],
            "hard_constraints": {
                "user_took_over": "passed",
                "thread_read": "failed",
                "cooldown": "skipped",
                "mutex": "skipped",
                "urgent": urgent,
            },
        }

    # v4 硬约束 2：回复冷却校验
    stage = _get_person_stage_num(name)
    cooldown_check = _check_cooldown(name, urgent=urgent, stage=stage)
    if not cooldown_check["passed"]:
        return {
            "success": False,
            "error": "COOLDOWN_ACTIVE",
            "message": cooldown_check["reason"],
            "wait_seconds": cooldown_check.get("wait_seconds", 0),
            "cooldown_seconds": cooldown_check.get("cooldown_seconds", 0),
            "elapsed_seconds": cooldown_check.get("elapsed_seconds", 0),
            "stage": stage,
            "suggestion": "等待冷却结束后重试，或使用 urgent=True 绕过（仅紧急情况）",
            "contact": name,
            "total": len(messages),
            "succeeded": 0,
            "failed": len(messages),
            "results": [],
            "hard_constraints": {
                "user_took_over": "passed",
                "thread_read": "passed",
                "cooldown": "failed",
                "mutex": "skipped",
                "stage": stage,
                "urgent": urgent,
            },
        }

    # v4 硬约束 3：互斥锁 + 批量发送流程
    def _impl():
        _wechat_op_lock.acquire()
        try:
            return send_message_batch(name, messages)
        finally:
            _wechat_op_lock.release()

    result = with_recording(name, _impl)

    # 发送成功后更新 last_send_time（只要有任意一条成功）
    if result.get("succeeded", 0) > 0:
        _update_send_time(name)

    result["hard_constraints"] = {
        "user_took_over": "passed",
        "thread_read": "passed",
        "cooldown": "bypassed" if urgent else "passed",
        "mutex": "passed",
        "stage": stage,
        "urgent": urgent,
    }

    return result


# ── 工具5: wechat_verify_send ───────────────────────────────────

def wechat_verify_send(name: str, before_ts: int, max_retries: int = 3, interval: int = 10) -> dict:
    """通过数据同步管道验证消息发送结果（v4 二次验证能力）。

    在 wechat_send / wechat_send_batch / wechat_send_image 发送后调用，
    通过增量同步管道对比发送前后我方消息，验证消息是否真正送达。

    适用场景：
    - 截图验证（OCR/输入框检测）通过，但想二次确认消息真正送达
    - 图片/表情包等无法用 OCR 文字验证的消息类型
    - 怀疑发送失败时（如网络问题）的排查

    注意：
    - WeChat→WCD 同步有延迟，采用轮询策略（默认 10s×3 次，最长 30s）
    - 验证结果"未验证"≠"发送失败"，可能是同步延迟较长
    - 只对比我方消息（sender_id == my_wxid），不对比对方消息

    消息类型展示：
    - 文字(type 1)：原样显示
    - 图片(type 3)：[图片描述] xxx 或 [图片]
    - 表情贴纸(type 47)：[表情] xxx
    - 语音(type 34)：[语音转文字] xxx 或 [语音]

    Args:
        name: 微信联系人标识符（与发送时使用的 name 一致）
        before_ts: 发送前的 Unix 时间戳（秒）。
                   应在调用 wechat_send 前记录 int(time.time())，发送后传入。
        max_retries: 最大重试次数（默认 3）
        interval: 每次重试间隔秒数（默认 10）

    Returns:
        dict: {
            "verified": bool,       # 是否验证成功
            "new_messages": list,   # 新增的我方消息列表
            "new_count": int,       # 新增消息数
            "attempts": int,        # 尝试次数
            "elapsed": float,       # 总耗时秒数
            "conversation_id": str, # 联系人 wxid
            "my_wxid": str,         # 登录用户 wxid
            "error": str|None,
        }
    """
    from engine.wechat_sender.send_verify import verify_send_via_sync

    if not before_ts or before_ts <= 0:
        return {
            "verified": False,
            "new_messages": [],
            "new_count": 0,
            "attempts": 0,
            "elapsed": 0,
            "conversation_id": "",
            "my_wxid": "",
            "error": "before_ts 无效（应为发送前的 Unix 时间戳秒）",
        }

    return verify_send_via_sync(
        name=name,
        before_ts=before_ts,
        max_retries=max_retries,
        interval=interval,
    )
