"""测试微信编辑框是否响应 WM_IME_CHAR 消息。

验证流程：
1. 提示用户手动打开微信，进入任意联系人聊天界面，点击输入框
2. 倒计时 5 秒（用户准备时间）
3. 用 WM_IME_CHAR 发送测试字符（如 "测试"）
4. 等待 1 秒
5. 截图 + OCR 识别输入框区域，验证是否包含测试字符
6. 输出结果，指导是否可以开启 USE_IME_CHAR_FOR_CHINESE

用法：
    python -X utf8 scripts/test_ime_char.py
    python -X utf8 scripts/test_ime_char.py --text "你好世界"
    python -X utf8 scripts/test_ime_char.py --skip-ocr  # 跳过 OCR 验证，只发送

判定标准：
- OCR 识别到测试字符 → 微信响应 WM_IME_CHAR，可开启 USE_IME_CHAR_FOR_CHINESE = True
- OCR 未识别到      → 微信不响应，保持 USE_IME_CHAR_FOR_CHINESE = False
"""
import os
import sys
import time
import ctypes
import ctypes.wintypes as wintypes
import argparse

# 项目根目录
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "engine", "wechat_sender"))

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

from human_sim import (  # noqa: E402
    _type_ime_char,
    _type_char_unicode,
    WM_IME_CHAR,
    VK_ESCAPE,
    _press_single_key,
)
from wechat_window_utils import find_wechat_window  # noqa: E402


def countdown(seconds, message):
    """倒计时提示。"""
    for i in range(seconds, 0, -1):
        print(f"\r{message} {i} 秒...", end="", flush=True)
        time.sleep(1)
    print(f"\r{' ' * 40}\r", end="", flush=True)


def send_ime_chars(hwnd, text):
    """用 WM_IME_CHAR 逐字发送中文字符。"""
    print(f"发送 WM_IME_CHAR: {text!r}")
    for ch in text:
        code = ord(ch)
        # lParam 高字=扫描码（0），低字=重复次数（1）
        result = ctypes.windll.user32.PostMessageW(hwnd, WM_IME_CHAR, code, 1)
        print(f"  字符 {ch!r} (U+{code:04X}) → PostMessageW 返回 {result}")
        time.sleep(0.15)


def send_unicode_chars(text):
    """用 SendInput + KEYEVENTF_UNICODE 逐字发送字符（作为对比）。"""
    print(f"发送 Unicode (SendInput): {text!r}")
    for ch in text:
        _type_char_unicode(ch)
        time.sleep(0.1)


def ocr_verify(hwnd, expected_text):
    """截图 + OCR 验证输入框是否包含预期文本。

    Returns:
        tuple (found: bool, ocr_text: str)
    """
    try:
        from test_current_wechat import screencap_window
        import cv2

        img = screencap_window(hwnd)
        if img is None:
            return False, "截图失败"

        # 保存截图
        shot_dir = os.path.join(_PROJECT_ROOT, "engine", "wechat_sender", "outputs")
        os.makedirs(shot_dir, exist_ok=True)
        shot_path = os.path.join(shot_dir, "test_ime_char.png")
        cv2.imwrite(shot_path, img)
        print(f"截图保存: {shot_path}")

        # 裁剪底部 1/3 区域（输入框通常在底部）
        h, w = img.shape[:2]
        bottom = img[h * 2 // 3:, :]
        bottom_path = os.path.join(shot_dir, "test_ime_char_bottom.png")
        cv2.imwrite(bottom_path, bottom)
        print(f"底部区域截图: {bottom_path}")

        # OCR 识别
        try:
            import pytesseract
            text = pytesseract.image_to_string(bottom, lang="chi_sim+eng")
            print(f"OCR 识别结果: {text!r}")
            # 检查是否包含预期字符
            found = any(ch in text for ch in expected_text)
            return found, text
        except ImportError:
            print("⚠️ 未安装 pytesseract，无法自动 OCR 验证")
            print("   请手动查看截图，确认输入框是否包含测试字符")
            print(f"   预期字符: {expected_text}")
            return False, "pytesseract 未安装"
    except Exception as e:
        print(f"OCR 验证异常: {e}")
        return False, str(e)


def main():
    parser = argparse.ArgumentParser(description="测试微信编辑框是否响应 WM_IME_CHAR")
    parser.add_argument("--text", default="测试", help="测试文本（默认 '测试'）")
    parser.add_argument("--skip-ocr", action="store_true", help="跳过 OCR 验证，只发送")
    parser.add_argument("--use-unicode", action="store_true", help="用 SendInput Unicode 发送（对比测试）")
    args = parser.parse_args()

    test_text = args.text

    print("=" * 60)
    print("  WM_IME_CHAR 测试")
    print("=" * 60)
    print()
    print("测试目的：验证微信编辑框是否响应 WM_IME_CHAR 消息")
    print(f"测试文本: {test_text!r}")
    print(f"发送方式: {'SendInput Unicode' if args.use_unicode else 'WM_IME_CHAR'}")
    print()
    print("⚠️ 请按以下步骤准备：")
    print("  1. 打开微信 PC 客户端")
    print("  2. 进入任意联系人聊天界面")
    print("  3. 点击底部输入框，确保光标在输入框内")
    print("  4. 不要在输入框输入任何内容（保持空白）")
    print()

    # 查找微信窗口
    wx_win = find_wechat_window()
    if not wx_win:
        print("❌ 未找到微信窗口，请先打开微信")
        return 1

    hwnd = wx_win["hwnd"]
    print(f"✅ 找到微信窗口: hwnd={hwnd} title={wx_win['title']!r}")

    # 倒计时
    countdown(5, "5 秒后开始发送，请确保光标在输入框内")

    # 清空输入框（按 Esc 然后 Ctrl+A）
    print("清空输入框...")
    _press_single_key(VK_ESCAPE)
    time.sleep(0.3)

    # 发送测试字符
    if args.use_unicode:
        send_unicode_chars(test_text)
    else:
        send_ime_chars(hwnd, test_text)

    # 等待消息处理
    print("等待 1.5 秒让微信处理...")
    time.sleep(1.5)

    if args.skip_ocr:
        print()
        print("=" * 60)
        print("  发送完成（跳过 OCR 验证）")
        print("=" * 60)
        print("请手动查看微信输入框，确认是否出现测试字符：")
        print(f"  预期字符: {test_text!r}")
        print()
        print("判定：")
        print("  - 输入框出现测试字符 → 可在 human_sim.py 中设置 USE_IME_CHAR_FOR_CHINESE = True")
        print("  - 输入框为空或乱码   → 保持 USE_IME_CHAR_FOR_CHINESE = False")
        return 0

    # OCR 验证
    print()
    print("开始 OCR 验证...")
    found, ocr_text = ocr_verify(hwnd, test_text)

    print()
    print("=" * 60)
    print("  测试结果")
    print("=" * 60)
    if found:
        print(f"✅ 成功：OCR 识别到测试字符 {test_text!r}")
        print(f"   OCR 结果: {ocr_text!r}")
        print()
        print("📌 结论：微信编辑框响应 WM_IME_CHAR")
        print("   建议在 human_sim.py 中设置：USE_IME_CHAR_FOR_CHINESE = True")
    else:
        print(f"❌ 失败：OCR 未识别到测试字符 {test_text!r}")
        print(f"   OCR 结果: {ocr_text!r}")
        print()
        print("📌 结论：微信编辑框不响应 WM_IME_CHAR（或 OCR 识别失败）")
        print("   建议：")
        print("   1. 手动查看截图确认输入框内容")
        print("   2. 如确认输入框为空，保持 USE_IME_CHAR_FOR_CHINESE = False")
        print("   3. 如确认输入框有内容但 OCR 没识别出来，可手动开启")

    print()
    print("提示：可用 --use-unicode 参数对比测试 SendInput Unicode 方式")
    print("提示：可用 --skip-ocr 参数跳过自动验证，手动查看")

    return 0 if found else 2


if __name__ == "__main__":
    sys.exit(main())
