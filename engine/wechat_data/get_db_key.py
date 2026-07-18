"""用 wx_key.dll 获取微信数据库解密 key。

基于 WeFlow keyService.ts 的 Python 复现。
需要管理员权限（InitializeHook 会注入微信进程）。

流程：
1. 找到微信 PID
2. InitializeHook(pid) 注入
3. PollKeyData() 轮询获取 key（64字符 hex）
4. CleanupHook() 清理
"""
import ctypes
import ctypes.wintypes as wintypes
import os
import sys
import time

# DLL 路径（本目录下的 dll 子目录）
DLL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dll")
WX_KEY_DLL_PATH = os.path.join(DLL_DIR, "wx_key.dll")

if not os.path.exists(WX_KEY_DLL_PATH):
    print(f"❌ wx_key.dll 不存在: {WX_KEY_DLL_PATH}")
    sys.exit(1)


def find_wechat_pid():
    """找到所有微信进程 PID，返回列表"""
    import psutil
    candidates = []
    for p in psutil.process_iter(['pid', 'name']):
        if p.info['name'] in ('Weixin.exe', 'WeChat.exe'):
            candidates.append((p.info['pid'], p.info['name']))

    if not candidates:
        return []
    # 按 PID 排序
    candidates.sort(key=lambda x: x[0])
    return candidates


def get_db_key(max_wait=60):
    """用 wx_key.dll 获取微信数据库 key。

    Args:
        max_wait: 最大等待秒数

    Returns:
        str: 64 字符 hex key，或 None
    """
    print(f"加载 wx_key.dll: {WX_KEY_DLL_PATH}")

    # 加载 DLL
    try:
        dll = ctypes.WinDLL(WX_KEY_DLL_PATH)
    except Exception as e:
        print(f"❌ 加载 DLL 失败: {e}")
        return None

    # 设置函数原型
    dll.InitializeHook.argtypes = [wintypes.UINT]
    dll.InitializeHook.restype = ctypes.c_bool

    dll.PollKeyData.argtypes = [ctypes.c_char_p, ctypes.c_int]
    dll.PollKeyData.restype = ctypes.c_bool

    dll.GetStatusMessage.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.POINTER(ctypes.c_int)]
    dll.GetStatusMessage.restype = ctypes.c_bool

    dll.CleanupHook.argtypes = []
    dll.CleanupHook.restype = ctypes.c_bool

    dll.GetLastErrorMsg.argtypes = []
    dll.GetLastErrorMsg.restype = ctypes.c_char_p

    # 1. 找所有微信 PID
    candidates = find_wechat_pid()
    if not candidates:
        print("❌ 未找到微信进程，请确保微信已启动并登录")
        return None

    print(f"✅ 找到 {len(candidates)} 个微信进程:")
    for pid, name in candidates:
        print(f"   PID={pid} Name={name}")

    # 2. 依次尝试每个 PID，直到成功
    for pid, name in candidates:
        print(f"\n--- 尝试 PID={pid} ---")
        print(f"InitializeHook({pid}) ...")
        success = dll.InitializeHook(pid)
        if not success:
            err = dll.GetLastErrorMsg().decode('utf-8', errors='ignore')
            print(f"❌ InitializeHook 失败: {err}")
            if '0xC0000022' in err or 'ACCESS_DENIED' in err:
                print("   原因：权限不足，请以管理员身份运行")
            continue

        print("✅ Hook 注入成功，开始轮询 key...")

        # 3. 轮询 key
        key = None
        key_buffer = ctypes.create_string_buffer(128)
        deadline = time.time() + max_wait

        try:
            while time.time() < deadline:
                # 检查微信进程是否还在
                import psutil
                if not psutil.pid_exists(pid):
                    print("❌ 微信进程已退出")
                    break

                # 轮询 key
                if dll.PollKeyData(key_buffer, 128):
                    key_str = key_buffer.value.decode('utf-8', errors='ignore').strip()
                    if len(key_str) == 64:
                        key = key_str
                        print(f"✅ 获取到 key: {key}")
                        break

                # 读状态消息
                status_buffer = ctypes.create_string_buffer(256)
                level = ctypes.c_int(0)
                for _ in range(5):
                    if not dll.GetStatusMessage(status_buffer, 256, ctypes.byref(level)):
                        break
                    msg = status_buffer.value.decode('utf-8', errors='ignore').strip()
                    if msg:
                        print(f"   [DLL] {msg}")

                time.sleep(0.12)

        finally:
            # 4. 清理
            print("CleanupHook() ...")
            dll.CleanupHook()

        if key:
            return key

    print(f"❌ 所有 PID 都未能获取到 key")
    return None


if __name__ == "__main__":
    # 重定向 stdout 到文件（管理员权限运行时无法直接捕获输出）
    output_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_get_key_output.txt")
    original_stdout = sys.stdout
    with open(output_file, 'w', encoding='utf-8') as f:
        sys.stdout = f

        # 检查管理员权限
        try:
            is_admin = ctypes.windll.shell32.IsUserAnAdmin()
        except Exception:
            is_admin = False

        if not is_admin:
            print("⚠️ 当前不是管理员权限，wx_key.dll 的 InitializeHook 可能失败")
            print("   建议以管理员身份运行 PowerShell 后执行此脚本")
            print()

        key = get_db_key(max_wait=30)
        if key:
            print(f"\n=== 成功获取数据库 key ===")
            print(f"Key: {key}")
            # 保存到临时文件（不提交到 git）
            key_file = os.path.join(os.path.dirname(__file__), "_db_key.tmp")
            with open(key_file, 'w') as kf:
                kf.write(key)
            print(f"已保存到: {key_file}")
        else:
            print("\n❌ 获取 key 失败")

    sys.stdout = original_stdout
    print(f"输出已写入: {output_file}")
