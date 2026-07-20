"""微信操作录屏模块：用 BitBlt 定时截图 + OpenCV VideoWriter 合成视频。

用途：
- 每次 wechat_send 操作前启动录屏
- 操作成功 → 删除录屏
- 操作失败 → 保留录屏供用户核对（路径返回给 agent）

设计要点：
- 独立线程截图，不阻塞主流程
- BitBlt 从屏幕 DC 截图（与 open_wechat_window 一致）
- OpenCV VideoWriter 编码为 MP4（mp4v 编码器，兼容性好）
- 截屏帧率 5 FPS（足够诊断微信操作问题，文件大小约 1-2MB/分钟）
- 失败时保留 7 天，超过自动清理

录屏保存路径：data/outputs/recordings/wechat_send_<timestamp>_<contact>.mp4
⚠️ 该路径在 data/ 目录下，已被 .gitignore 忽略，不会提交到 git

用法：
    from engine.wechat_sender.wechat_recorder import WechatRecorder

    recorder = WechatRecorder(contact_name="[REDACTED]")
    recorder.start()
    try:
        # 执行微信操作...
        success = do_wechat_operation()
    finally:
        video_path = recorder.stop()
    if success:
        recorder.discard()  # 删除录屏
    else:
        logger.info(f"录屏已保留: {video_path}")
"""
import os
import sys
import time
import threading
import ctypes
import ctypes.wintypes as wintypes
import datetime

# 设置 DPI 感知（必须在其他导入前）
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from logger import get_logger  # noqa: E402

logger = get_logger(__name__)

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

# ── 录屏参数 ──────────────────────────────────────────────────
FPS = 5                          # 截图帧率（每秒 5 帧）
RECORDING_RETENTION_DAYS = 7    # 失败录屏保留天数

# VideoWriter 编码器（mp4v 兼容性最好）
FOURCC = cv2.VideoWriter_fourcc(*"mp4v")

# 项目根目录
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RECORDINGS_DIR = os.path.join(_PROJECT_ROOT, "data", "outputs", "recordings")


def _load_debug_flag() -> bool:
    """从配置文件加载 debug 标志。

    读取 data/system/config.yaml 中的 debug 字段。
    如果配置文件不存在或读取失败，默认返回 False（不录屏）。

    Returns:
        bool: debug 模式是否开启
    """
    try:
        config_path = os.path.join(_PROJECT_ROOT, "data", "system", "config.yaml")
        if not os.path.exists(config_path):
            return False
        import yaml
        with open(config_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        if isinstance(raw, dict):
            return bool(raw.get("debug", False))
    except Exception as e:
        logger.debug(f"[录屏] 读取 debug 配置失败: {e}，默认不录屏")
    return False


def _capture_screen_region(left, top, width, height):
    """用 BitBlt 从屏幕 DC 截取指定区域。

    与 open_wechat_window._capture_region 一致的实现，
    复制到这里避免循环导入。

    Args:
        left, top: 屏幕坐标左上角
        width, height: 区域尺寸

    Returns:
        numpy.ndarray (BGR) 或 None
    """
    if width <= 0 or height <= 0:
        return None

    hdc_screen = user32.GetDC(None)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
    hbmp = gdi32.CreateCompatibleBitmap(hdc_screen, width, height)
    old_bmp = gdi32.SelectObject(hdc_mem, hbmp)

    SRCCOPY = 0x00CC0020
    gdi32.BitBlt(hdc_mem, 0, 0, width, height, hdc_screen, left, top, SRCCOPY)

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.UINT),
            ("biWidth", wintypes.LONG),
            ("biHeight", wintypes.LONG),
            ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD),
            ("biCompression", wintypes.UINT),
            ("biSizeImage", wintypes.UINT),
            ("biXPelsPerMeter", wintypes.LONG),
            ("biYPelsPerMeter", wintypes.LONG),
            ("biClrUsed", wintypes.UINT),
            ("biClrImportant", wintypes.UINT),
        ]

    bih = BITMAPINFOHEADER()
    bih.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bih.biWidth = width
    bih.biHeight = -height  # 负值表示从上到下
    bih.biPlanes = 1
    bih.biBitCount = 32
    bih.biCompression = 0

    buffer_size = width * height * 4
    buffer = ctypes.create_string_buffer(buffer_size)
    gdi32.GetDIBits(hdc_mem, hbmp, 0, height, buffer, ctypes.byref(bih), 0)

    gdi32.SelectObject(hdc_mem, old_bmp)
    gdi32.DeleteObject(hbmp)
    gdi32.DeleteDC(hdc_mem)
    user32.ReleaseDC(None, hdc_screen)

    arr = np.frombuffer(buffer.raw, dtype=np.uint8).reshape((height, width, 4))
    img = arr[:, :, :3].copy()
    return img


def _get_screen_dimensions():
    """获取主屏幕的宽高（物理像素，DPI 感知后）。"""
    user32.SetProcessDpiAwareness(2) if hasattr(user32, "SetProcessDpiAwareness") else None
    width = user32.GetSystemMetrics(0)  # SM_CXSCREEN
    height = user32.GetSystemMetrics(1)  # SM_CYSCREEN
    return width, height


def cleanup_old_recordings(retention_days=RECORDING_RETENTION_DAYS):
    """清理超过保留期的录屏文件。

    在 wechat_send 入口调用，清理 retention_days 天前的录屏。

    Args:
        retention_days: 保留天数（默认 7 天）

    Returns:
        int: 删除的文件数
    """
    if not os.path.exists(RECORDINGS_DIR):
        return 0

    cutoff_time = time.time() - retention_days * 86400
    deleted_count = 0

    for fname in os.listdir(RECORDINGS_DIR):
        if not fname.endswith(".mp4"):
            continue
        fpath = os.path.join(RECORDINGS_DIR, fname)
        try:
            mtime = os.path.getmtime(fpath)
            if mtime < cutoff_time:
                os.remove(fpath)
                deleted_count += 1
                logger.info(f"   [录屏清理] 删除过期文件: {fname}")
        except Exception as e:
            logger.warning(f"   [录屏清理] 删除失败 {fname}: {e}")

    if deleted_count > 0:
        logger.info(f"   [录屏清理] 共删除 {deleted_count} 个过期录屏（>{retention_days}天）")

    return deleted_count


class WechatRecorder:
    """微信操作录屏器：独立线程截图，OpenCV VideoWriter 写入 MP4。

    用法：
        recorder = WechatRecorder(contact_name="[REDACTED]")
        recorder.start()
        try:
            # 执行微信操作...
        finally:
            video_path = recorder.stop()
        if success:
            recorder.discard()
        else:
            # 保留录屏，路径返回给 agent
    """

    def __init__(self, contact_name="unknown", fps=FPS, debug=None):
        """初始化录屏器。

        Args:
            contact_name: 联系人名称（用于文件命名）
            fps: 截图帧率（默认 5 FPS）
            debug: 是否开启 debug 模式（开启才录屏）。None 表示从配置文件读取。
        """
        self.contact_name = contact_name
        self.fps = fps
        # debug 标志：None 时从配置文件读取，否则用传入值
        self.debug = _load_debug_flag() if debug is None else bool(debug)
        self.is_recording = False
        self._thread = None
        self._stop_event = threading.Event()
        self._video_path = None
        self._writer = None
        self._frame_count = 0
        self._start_time = None
        self._lock = threading.Lock()

        # 安全的联系人名（用于文件名）
        safe_name = "".join(
            c if c.isalnum() or c in "._-" else "_" for c in str(contact_name)
        )[:50]
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self._filename = f"wechat_send_{timestamp}_{safe_name}.mp4"

    @property
    def video_path(self):
        """返回视频文件路径（停止后有效）。"""
        return self._video_path

    def start(self):
        """启动录屏线程。

        如果 debug=False，直接返回不录屏（避免消耗资源）。
        """
        # debug=False 时不录屏
        if not self.debug:
            logger.debug("[录屏] debug 模式未开启，跳过录屏")
            return

        if self.is_recording:
            logger.warning("[录屏] 已在录制中，忽略重复 start 调用")
            return

        os.makedirs(RECORDINGS_DIR, exist_ok=True)
        self._video_path = os.path.join(RECORDINGS_DIR, self._filename)

        # 先清理过期录屏
        try:
            cleanup_old_recordings()
        except Exception as e:
            logger.warning(f"[录屏] 清理过期文件异常: {e}")

        self.is_recording = True
        self._stop_event.clear()
        self._frame_count = 0
        self._start_time = time.time()

        self._thread = threading.Thread(target=self._record_loop, daemon=True)
        self._thread.start()
        logger.info(f"[录屏] 开始录制: {self._video_path}")

    def _record_loop(self):
        """录屏线程主循环：定时截图并写入视频。"""
        frame_interval = 1.0 / self.fps
        screen_w, screen_h = _get_screen_dimensions()

        if screen_w <= 0 or screen_h <= 0:
            logger.error(f"[录屏] 屏幕尺寸异常: {screen_w}x{screen_h}，停止录制")
            self.is_recording = False
            return

        # 初始化 VideoWriter（用第一帧确定尺寸）
        first_frame = _capture_screen_region(0, 0, screen_w, screen_h)
        if first_frame is None:
            logger.error("[录屏] 首帧截图失败，停止录制")
            self.is_recording = False
            return

        try:
            self._writer = cv2.VideoWriter(
                self._video_path,
                FOURCC,
                self.fps,
                (screen_w, screen_h),
            )
            if not self._writer.isOpened():
                logger.error("[录屏] VideoWriter 打开失败，停止录制")
                self.is_recording = False
                return

            # 写入第一帧
            with self._lock:
                if self._writer:
                    self._writer.write(first_frame)
                    self._frame_count += 1

            # 循环截图
            while not self._stop_event.is_set():
                loop_start = time.time()

                frame = _capture_screen_region(0, 0, screen_w, screen_h)
                if frame is not None:
                    with self._lock:
                        if self._writer:
                            self._writer.write(frame)
                            self._frame_count += 1

                # 精确控制帧率
                elapsed = time.time() - loop_start
                sleep_time = frame_interval - elapsed
                if sleep_time > 0:
                    time.sleep(sleep_time)

        except Exception as e:
            logger.error(f"[录屏] 录制异常: {e}")
        finally:
            with self._lock:
                if self._writer:
                    self._writer.release()
                    self._writer = None

    def stop(self, timeout=5.0):
        """停止录屏并返回视频路径。

        Args:
            timeout: 等待录屏线程结束的最大秒数

        Returns:
            str: 视频文件路径，如果未开始录制则返回 None
        """
        if not self.is_recording:
            return None

        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)

        self.is_recording = False
        duration = time.time() - self._start_time if self._start_time else 0

        with self._lock:
            if self._writer:
                self._writer.release()
                self._writer = None

        logger.info(
            f"[录屏] 停止录制: {self._video_path} "
            f"(帧数={self._frame_count}, 时长={duration:.1f}s)"
        )
        return self._video_path

    def discard(self):
        """删除录屏文件（操作成功时调用）。"""
        if self._video_path and os.path.exists(self._video_path):
            try:
                os.remove(self._video_path)
                logger.info(f"[录屏] 操作成功，已删除录屏: {self._video_path}")
            except Exception as e:
                logger.warning(f"[录屏] 删除录屏失败: {e}")
        self._video_path = None

    def keep(self):
        """保留录屏文件（操作失败时调用）。

        Returns:
            str: 视频文件路径
        """
        if self._video_path and os.path.exists(self._video_path):
            logger.info(f"[录屏] 操作失败，保留录屏供核对: {self._video_path}")
            return self._video_path
        return None


# ── 录屏包装器（从 mcp_server/tools_wechat.py 迁移）──────────────

def with_recording(operation_name, func, *args, **kwargs):
    """执行微信操作并录屏（统一录屏逻辑，供所有操作微信的 MCP 工具使用）。

    在 MCP 工具层使用，统一处理录屏启动/停止/清理逻辑：
    - 操作前自动开始录屏（BitBlt + OpenCV VideoWriter，5 FPS）
    - 操作成功 → 自动删除录屏
    - 操作失败 → 保留录屏 7 天，路径加入返回值的 recording_path 字段
    - 录屏路径：data/outputs/recordings/wechat_<op>_<timestamp>_<contact>.mp4
    - ⚠️ 录屏文件在 data/ 目录下，已被 .gitignore 忽略

    Args:
        operation_name: 操作名称（用于录屏文件命名，如 "wechat_send"）
        func: 要执行的函数（返回 dict）
        *args, **kwargs: 函数参数

    Returns:
        dict: func 的返回值，添加 recording_path 字段
              - 成功时 recording_path = None（录屏已删除）
              - 失败时 recording_path = 录屏文件路径（保留 7 天）
    """
    import traceback

    recorder = WechatRecorder(contact_name=operation_name)
    recorder.start()
    result = None
    try:
        result = func(*args, **kwargs)
    except Exception as e:
        result = {
            "success": False,
            "message": f"录屏包装层异常: {e}",
            "error": f"WRAPPER_ERROR: {traceback.format_exc()}",
            "recording_path": None,
        }
    finally:
        recorder.stop()
        if result and isinstance(result, dict):
            if result.get("success"):
                recorder.discard()
                result["recording_path"] = None
            else:
                kept_path = recorder.keep()
                result["recording_path"] = kept_path
    return result


if __name__ == "__main__":
    # 命令行测试：录制 5 秒
    recorder = WechatRecorder(contact_name="test")
    recorder.start()
    print(f"录制中... (5秒)，文件: {recorder.video_path}")
    time.sleep(5)
    path = recorder.stop()
    print(f"录屏完成: {path}")
    if path and os.path.exists(path):
        size_kb = os.path.getsize(path) / 1024
        print(f"文件大小: {size_kb:.1f} KB")


