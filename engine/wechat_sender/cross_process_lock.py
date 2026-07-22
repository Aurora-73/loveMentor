"""跨进程互斥锁（基于 Win32 命名互斥体）。

用于防止多个进程同时执行微信视觉自动化操作（如 Agent 进程 + 其他工具进程
同时调用 wechat_send）。命名互斥体在 Windows 内核中共享，任何进程都可以
通过名称获取同一把锁。

相比 threading.Lock 的优势：
- 跨进程：多个 Python 进程共享同一把锁
- 内核级安全：比文件锁更可靠，无文件残留问题
- 自动回收：进程崩溃时 Windows 自动释放锁（WAIT_ABANDONED 机制）

相比 portalocker 的优势：
- 无外部依赖（Windows 原生 API）
- 无文件锁残留风险
- 性能更高（内核对象 vs 文件系统）

用法：
    lock = CrossProcessLock("loveMentor_wechat_op")
    lock.acquire()
    try:
        # 临界区
    finally:
        lock.release()

    # 或用作上下文管理器
    with CrossProcessLock("loveMentor_wechat_op"):
        # 临界区
"""
import ctypes
import ctypes.wintypes as wintypes
import logging

logger = logging.getLogger(__name__)

# ── Win32 API 声明（64 位系统必须设置函数原型，否则句柄被截断）──
_kernel32 = ctypes.windll.kernel32
_kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.CreateMutexW.restype = wintypes.HANDLE
_kernel32.ReleaseMutex.argtypes = [wintypes.HANDLE]
_kernel32.ReleaseMutex.restype = wintypes.BOOL
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.CloseHandle.restype = wintypes.BOOL

_kernel32.GetLastError.argtypes = []
_kernel32.GetLastError.restype = wintypes.DWORD

# WaitForSingleObject 在 kernel32.dll 中（不是 user32）
_kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
_kernel32.WaitForSingleObject.restype = wintypes.DWORD

# WaitForSingleObject 返回值
WAIT_OBJECT_0 = 0x00000000       # 获取成功
WAIT_ABANDONED = 0x00000080      # 前持有者进程崩溃，锁已转交（状态可能不一致）
WAIT_TIMEOUT = 0x00000102        # 超时
WAIT_FAILED = 0xFFFFFFFF         # 调用失败

ERROR_ALREADY_EXISTS = 183       # 互斥体已由其他进程创建
INFINITE = 0xFFFFFFFF            # 无限等待（与 threading.Lock 行为一致）


class CrossProcessLock:
    """跨进程互斥锁（Win32 Named Mutex）。

    命名互斥体在 Windows 内核中全局共享（同会话内），多个进程通过相同名称
    获取同一把锁。进程崩溃时 Windows 自动释放锁（下一个等待者收到
    WAIT_ABANDONED），避免死锁。

    注意：名称不加 "Global\\" 前缀，仅在当前会话内共享（单用户场景足够，
    避免跨会话权限问题）。

    Args:
        name: 互斥体名称（如 "loveMentor_wechat_op"）
        timeout_ms: acquire 默认超时毫秒数，默认 INFINITE（无限等待，与 threading.Lock 一致）
    """

    def __init__(self, name: str, timeout_ms: int = INFINITE):
        self._name = name
        self._timeout_ms = timeout_ms
        self._handle = None

    def acquire(self, timeout_ms: int = None) -> bool:
        """获取锁。

        Args:
            timeout_ms: 超时毫秒数，None 表示用默认值（默认 INFINITE 无限等待）。
                        传 0xFFFFFFFF = INFINITE（无限等待）。
                        传 0 = 立即返回（不等待）。
                        传正整数 = 等待指定毫秒数。

        Returns:
            bool: True=获取成功

        Raises:
            TimeoutError: 超时未获取到锁
            OSError: Win32 API 调用失败
        """
        if timeout_ms is None:
            timeout_ms = self._timeout_ms

        # 延迟创建互斥体（首次 acquire 时创建）
        if self._handle is None:
            self._handle = _kernel32.CreateMutexW(None, False, self._name)
            if not self._handle:
                err = _kernel32.GetLastError()
                raise OSError(f"CreateMutexW({self._name!r}) 失败: error={err}")
            # ERROR_ALREADY_EXISTS 是正常的（其他进程已创建同名互斥体）
            # 我们仍然可以 WaitForSingleObject 获取它

        result = _kernel32.WaitForSingleObject(self._handle, timeout_ms)

        if result == WAIT_OBJECT_0:
            return True

        if result == WAIT_ABANDONED:
            # 前持有者进程崩溃，锁已转交给本进程
            # 临界区状态可能不一致，记录警告但继续执行
            logger.warning(
                f"[跨进程锁] 获取到 abandoned 互斥体 {self._name!r}："
                f"前持有者进程可能崩溃，临界区状态可能不一致"
            )
            return True

        if result == WAIT_TIMEOUT:
            raise TimeoutError(
                f"[跨进程锁] 获取互斥体 {self._name!r} 超时（{timeout_ms}ms）"
            )

        # WAIT_FAILED 或其他未知返回值
        err = _kernel32.GetLastError()
        raise OSError(
            f"WaitForSingleObject({self._name!r}) 失败: "
            f"result={result} error={err}"
        )

    def release(self):
        """释放锁。"""
        if self._handle:
            if not _kernel32.ReleaseMutex(self._handle):
                err = _kernel32.GetLastError()
                logger.error(
                    f"[跨进程锁] ReleaseMutex({self._name!r}) 失败: error={err}"
                )

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()
        return False

    def __del__(self):
        """析构时关闭句柄（仅本进程的句柄，不影响互斥体本身）。"""
        if self._handle:
            _kernel32.CloseHandle(self._handle)
            self._handle = None
