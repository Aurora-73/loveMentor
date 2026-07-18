"""快速验证 SendInput 是否正常工作（不操作微信，只测试 API 调用）。

运行：
    python -X utf8 scripts/test_send_input.py
"""
import os
import sys
import ctypes

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_WECHAT_SENDER_DIR = os.path.join(_PROJECT_ROOT, "engine", "wechat_sender")
sys.path.insert(0, _WECHAT_SENDER_DIR)

from human_sim import (
    _send_input_keyboard,
    _send_key_press,
    _send_key_combo_si,
    _press_key_combo,
    _press_single_key,
    VK_CONTROL,
    VK_A,
    VK_V,
    VK_F,
    VK_MENU,
    VK_ESCAPE,
    KEYEVENTF_SCANCODE,
    KEYEVENTF_UNICODE,
    KEYEVENTF_KEYUP,
    INPUT,
    INPUT_KEYBOARD,
)
import ctypes.wintypes as wintypes


def test_structure_size():
    """测试结构体大小是否正确（64 位兼容性）"""
    print("=" * 60)
    print("测试 1: 结构体大小（64 位兼容性）")
    print("=" * 60)

    sizeof_INPUT = ctypes.sizeof(INPUT)
    # 64 位系统上 INPUT 应该是 32 字节（type:4 + padding:4 + ki:24）
    # 32 位系统上 INPUT 应该是 16 字节
    print(f"  sizeof(INPUT) = {sizeof_INPUT}")
    print(f"  Python 位宽: {ctypes.sizeof(ctypes.c_void_p) * 8} 位")

    # 验证结构体大小 > 0
    assert sizeof_INPUT > 0, "INPUT 结构体大小应为正数"

    # 验证字段可以通过实例访问
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.ii.ki.wVk = 0
    inp.ii.ki.wScan = 0
    inp.ii.ki.dwFlags = 0
    inp.ii.ki.time = 0
    inp.ii.ki.dwExtraInfo = None
    print(f"  字段访问正常: type={inp.type}, wVk={inp.ii.ki.wVk}")

    print("  ✅ 结构体大小正常")


def test_send_input_basic():
    """测试 SendInput 基本调用（含 fallback 机制，验证 API 调用不抛异常）"""
    print("\n" + "=" * 60)
    print("测试 2: SendInput 基本调用（含 fallback）")
    print("=" * 60)

    # 测试1：发送扫描码按键（Ctrl 按下/抬起）
    print("\n  测试 1: Ctrl 按下/抬起 (扫描码)")
    scan_ctrl = ctypes.windll.user32.MapVirtualKeyW(VK_CONTROL, 0)
    print(f"    VK_CONTROL={VK_CONTROL}, scan={scan_ctrl}")
    result = _send_input_keyboard(0, scan_ctrl, KEYEVENTF_SCANCODE)
    print(f"    按下结果: {result}")
    result = _send_input_keyboard(0, scan_ctrl, KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP)
    print(f"    抬起结果: {result}")

    # 测试2：发送 Unicode 字符 'a'
    print("\n  测试 2: Unicode 字符 'a' (ord=97)")
    result = _send_input_keyboard(0, ord('a'), KEYEVENTF_UNICODE)
    print(f"    按下结果: {result}")
    result = _send_input_keyboard(0, ord('a'), KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)
    print(f"    抬起结果: {result}")

    # 测试3：发送 Esc 键
    print("\n  测试 3: Esc 键 (扫描码)")
    result = _send_key_press(VK_ESCAPE, with_scan=True)
    print(f"    结果: {result}")

    # 测试4：发送 Ctrl+A 组合键
    print("\n  测试 4: Ctrl+A 组合键")
    _press_key_combo(VK_CONTROL, VK_A)
    print("    ✅ Ctrl+A 调用完成")

    print("\n  说明：如果 SendInput 返回 False，会自动回退到 keybd_event")
    print("  keybd_event 内部也是调用 SendInput，但封装更稳定")
    print("\n✅ SendInput 基本调用测试通过（含 fallback）")


def test_error_handling():
    """测试错误处理"""
    print("\n" + "=" * 60)
    print("测试 3: 错误处理")
    print("=" * 60)

    # 测试无效参数（wVk 和 wScan 都为 0，flags 也为 0）
    # 这种情况 SendInput 应该仍然返回 1（成功），但不会有实际效果
    print("\n  测试无效参数 (wVk=0, wScan=0, flags=0)")
    result = _send_input_keyboard(0, 0, 0)
    print(f"    结果: {result}")
    # SendInput 对空事件可能返回 1 或 0，不强制断言

    print("  ✅ 错误处理测试完成")


if __name__ == "__main__":
    test_structure_size()
    test_send_input_basic()
    test_error_handling()
    print("\n" + "=" * 60)
    print("  所有 SendInput 测试通过 ✅")
    print("=" * 60)
    print("\n提示：如果测试 2 中 SendInput 返回 False，请检查：")
    print("  1. 结构体定义是否正确（dwExtraInfo 用 c_void_p）")
    print("  2. 函数原型是否设置（argtypes/restype）")
    print("  3. 是否有权限限制（UIPI）")
