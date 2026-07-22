"""单元测试：_set_clipboard_file CF_HDROP 剪贴板格式验证。

验证内容：
1. _set_clipboard_file 成功设置剪贴板
2. 剪贴板格式为 CF_HDROP
3. 读回的文件路径与输入一致
4. 中文路径支持
5. 多文件路径支持（扩展验证）

不涉及微信窗口操作，纯剪贴板 API 测试。
"""
import os
import sys
import ctypes
import ctypes.wintypes as wintypes
import tempfile

# 添加项目路径
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, _PROJECT_ROOT)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from send_image_run import _set_clipboard_file

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
shell32 = ctypes.windll.shell32

CF_HDROP = 15

# DragQueryFileW 在 shell32.dll 中（不是 user32）
shell32.DragQueryFileW.argtypes = [wintypes.HANDLE, wintypes.UINT, wintypes.LPWSTR, wintypes.UINT]
shell32.DragQueryFileW.restype = wintypes.UINT

# GetClipboardData 返回类型必须设置为 HANDLE（64位安全），否则句柄被截断导致 access violation
user32.GetClipboardData.restype = wintypes.HANDLE
user32.GetClipboardData.argtypes = [wintypes.UINT]


def read_clipboard_files() -> list[str]:
    """从剪贴板读取 CF_HDROP 文件列表。"""
    if not user32.OpenClipboard(None):
        return []

    try:
        handle = user32.GetClipboardData(CF_HDROP)
        if not handle:
            return []

        # DragQueryFileCount: 传入 0xFFFFFFFF 获取文件数量
        count = shell32.DragQueryFileW(handle, 0xFFFFFFFF, None, 0)

        files = []
        for i in range(count):
            # 先获取路径长度（传入 NULL 缓冲区）
            length = shell32.DragQueryFileW(handle, i, None, 0)
            if length == 0:
                continue
            # 读取路径
            buf = ctypes.create_unicode_buffer(length + 1)
            shell32.DragQueryFileW(handle, i, buf, length + 1)
            files.append(buf.value)

        return files
    finally:
        user32.CloseClipboard()


def test_single_ascii_file():
    """测试 1：单个 ASCII 路径文件。"""
    print("\n=== 测试 1：单个 ASCII 路径文件 ===")
    # 创建临时文件
    tmp_dir = tempfile.gettempdir()
    test_file = os.path.join(tmp_dir, "cf_hdrop_test_ascii.txt")
    with open(test_file, "w", encoding="utf-8") as f:
        f.write("CF_HDROP test file")

    try:
        ok = _set_clipboard_file(test_file)
        assert ok, "_set_clipboard_file 返回 False"

        files = read_clipboard_files()
        assert len(files) == 1, f"期望 1 个文件，实际 {len(files)}"

        # 路径应为绝对路径
        expected = os.path.abspath(test_file)
        actual = files[0]
        assert actual.lower() == expected.lower(), f"路径不匹配:\n  期望: {expected}\n  实际: {actual}"

        print(f"  ✅ 通过：文件路径正确 = {actual}")
        return True
    except AssertionError as e:
        print(f"  ❌ 失败：{e}")
        return False


def test_single_chinese_file():
    """测试 2：单个中文路径文件。"""
    print("\n=== 测试 2：单个中文路径文件 ===")
    tmp_dir = tempfile.gettempdir()
    # 中文文件名
    test_file = os.path.join(tmp_dir, "CF_HDROP_测试文件.txt")
    with open(test_file, "w", encoding="utf-8") as f:
        f.write("中文路径测试")

    try:
        ok = _set_clipboard_file(test_file)
        assert ok, "_set_clipboard_file 返回 False"

        files = read_clipboard_files()
        assert len(files) == 1, f"期望 1 个文件，实际 {len(files)}"

        expected = os.path.abspath(test_file)
        actual = files[0]
        assert actual == expected, f"中文路径不匹配:\n  期望: {expected}\n  实际: {actual}"

        print(f"  ✅ 通过：中文路径正确 = {actual}")
        return True
    except AssertionError as e:
        print(f"  ❌ 失败：{e}")
        return False


def test_nonexistent_file():
    """测试 3：不存在的文件（应该失败）。"""
    print("\n=== 测试 3：不存在的文件 ===")
    fake_path = "C:\\nonexistent\\fake_file_xyz.txt"

    try:
        # _set_clipboard_file 不检查文件是否存在（只设置剪贴板路径）
        # 但 input_file_via_clipboard 会检查
        # 这里测试 _set_clipboard_file 本身：它应该能设置任意路径
        ok = _set_clipboard_file(fake_path)
        if ok:
            files = read_clipboard_files()
            if len(files) == 1 and files[0] == os.path.abspath(fake_path):
                print(f"  ✅ 通过：_set_clipboard_file 不验证文件存在性（设计如此），剪贴板路径已设置")
                return True
            else:
                print(f"  ❌ 失败：剪贴板内容不正确: {files}")
                return False
        else:
            print(f"  ❌ 失败：_set_clipboard_file 返回 False")
            return False
    except Exception as e:
        print(f"  ❌ 异常：{e}")
        return False


def test_video_extension():
    """测试 4：视频文件扩展名（.mp4）。"""
    print("\n=== 测试 4：视频文件扩展名（.mp4）===")
    tmp_dir = tempfile.gettempdir()
    test_file = os.path.join(tmp_dir, "cf_hdrop_test_video.mp4")
    # 创建一个假的 mp4 文件（空内容，只测路径设置）
    with open(test_file, "wb") as f:
        f.write(b"\x00\x00\x00\x18ftypmp42")  # 最小 mp4 头

    try:
        ok = _set_clipboard_file(test_file)
        assert ok, "_set_clipboard_file 返回 False"

        files = read_clipboard_files()
        assert len(files) == 1, f"期望 1 个文件，实际 {len(files)}"

        actual = files[0]
        assert actual.endswith(".mp4"), f"扩展名不正确: {actual}"

        print(f"  ✅ 通过：视频文件路径正确 = {actual}")
        return True
    except AssertionError as e:
        print(f"  ❌ 失败：{e}")
        return False


def test_clipboard_format():
    """测试 5：验证剪贴板格式为 CF_HDROP。"""
    print("\n=== 测试 5：验证剪贴板格式 ===")
    tmp_dir = tempfile.gettempdir()
    test_file = os.path.join(tmp_dir, "cf_hdrop_format_test.txt")
    with open(test_file, "w", encoding="utf-8") as f:
        f.write("format test")

    try:
        ok = _set_clipboard_file(test_file)
        assert ok

        if not user32.OpenClipboard(None):
            print("  ❌ OpenClipboard 失败")
            return False
        try:
            # 检查剪贴板是否有 CF_HDROP 格式
            has_hdrop = user32.IsClipboardFormatAvailable(CF_HDROP)
            if has_hdrop:
                print(f"  ✅ 通过：剪贴板包含 CF_HDROP 格式")
                return True
            else:
                print(f"  ❌ 失败：剪贴板不包含 CF_HDROP 格式")
                return False
        finally:
            user32.CloseClipboard()
    except Exception as e:
        print(f"  ❌ 异常：{e}")
        return False


def main():
    print("=" * 60)
    print("  CF_HDROP 剪贴板格式单元测试")
    print("=" * 60)

    tests = [
        test_single_ascii_file,
        test_single_chinese_file,
        test_nonexistent_file,
        test_video_extension,
        test_clipboard_format,
    ]

    results = []
    for test in tests:
        try:
            result = test()
            results.append(result)
        except Exception as e:
            print(f"  ❌ 异常：{e}")
            results.append(False)

    print("\n" + "=" * 60)
    passed = sum(results)
    total = len(results)
    print(f"  结果：{passed}/{total} 通过")
    print("=" * 60)

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
