"""
实时截图微信窗口，使用动态检测算法分析布局，标注分界线，保存结果供用户效验。
"""
import ctypes
import ctypes.wintypes as wintypes

# 设置 DPI 感知，让 GetWindowRect 等返回物理像素而非逻辑像素
# 必须在导入其他模块前调用，且只能调用一次
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_AWARE
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

import cv2
import numpy as np
from PIL import Image, ImageGrab

from dynamic_detector import WeChatLayoutDetector

user32 = ctypes.windll.user32


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


def find_wechat_window():
    candidates = []

    def enum_proc(hwnd, lparam):
        nonlocal candidates
        if not user32.IsWindowVisible(hwnd):
            return True

        length = user32.GetWindowTextLengthW(hwnd) + 1
        if length <= 1:
            title = ""
        else:
            buf = ctypes.create_unicode_buffer(length)
            user32.GetWindowTextW(hwnd, buf, length)
            title = buf.value

        cls_buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls_buf, 256)
        cls_name = cls_buf.value

        if "微信" in title or "WeChat" in cls_name or "WeChatMainWnd" in cls_name:
            rect = RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            w = rect.right - rect.left
            h = rect.bottom - rect.top
            candidates.append({
                "hwnd": hwnd,
                "title": title,
                "class": cls_name,
                "width": w,
                "height": h,
                "left": rect.left,
                "top": rect.top,
            })
        return True

    callback = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)(enum_proc)
    user32.EnumWindows(callback, 0)

    if not candidates:
        return None

    print(f"找到 {len(candidates)} 个微信窗口候选:")
    for i, c in enumerate(candidates):
        print(f"  {i+1}. 标题: '{c['title']}', 类名: '{c['class']}', "
              f"尺寸: {c['width']}x{c['height']}")

    # 过滤掉小窗口（托盘图标等），与 find_largest_wechat_window 的阈值一致
    MIN_WIDTH = 500
    MIN_HEIGHT = 400
    big_candidates = [c for c in candidates
                      if c["width"] >= MIN_WIDTH and c["height"] >= MIN_HEIGHT]

    if not big_candidates:
        print(f"   ⚠️ 所有候选窗口都小于 {MIN_WIDTH}x{MIN_HEIGHT}，可能不是主窗口")
        # 回退：选面积最大的
        big_candidates = sorted(candidates,
                                key=lambda c: c["width"] * c["height"], reverse=True)

    # 优先选标题精确为"微信"的窗口，其次按面积最大
    best_candidate = big_candidates[0]
    for c in big_candidates:
        if c["title"] == "微信":
            best_candidate = c
            break

    return {
        "hwnd": best_candidate["hwnd"],
        "left": best_candidate["left"],
        "top": best_candidate["top"],
        "width": best_candidate["width"],
        "height": best_candidate["height"],
        "title": best_candidate["title"],
    }


def activate_window(hwnd):
    """不再激活窗口，避免改变窗口状态导致截图不全"""
    pass


def screencap_window(hwnd):
    """重写截图代码：优先用窗口尺寸截取完整微信窗口（含标题栏和边框）"""
    import win32gui
    import win32ui
    import win32con

    # 获取窗口客户区尺寸
    client_rect = win32gui.GetClientRect(hwnd)
    client_w = client_rect[2] - client_rect[0]
    client_h = client_rect[3] - client_rect[1]

    # 获取窗口尺寸（含标题栏和边框）
    window_rect = win32gui.GetWindowRect(hwnd)
    window_w = window_rect[2] - window_rect[0]
    window_h = window_rect[3] - window_rect[1]

    print(f"   窗口尺寸: {window_w}x{window_h}, 客户区: {client_w}x{client_h}")

    def _try_printwindow(width, height, flag, label):
        """用指定尺寸和 flag 尝试 PrintWindow"""
        try:
            hwnd_dc = win32gui.GetWindowDC(hwnd)
            mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
            save_dc = mfc_dc.CreateCompatibleDC()

            save_bitmap = win32ui.CreateBitmap()
            save_bitmap.CreateCompatibleBitmap(mfc_dc, width, height)
            save_dc.SelectObject(save_bitmap)

            ctypes.windll.user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), flag)

            bmp_info = save_bitmap.GetInfo()
            bmp_str = save_bitmap.GetBitmapBits(True)
            image = np.frombuffer(bmp_str, dtype=np.uint8).reshape(
                (bmp_info["bmHeight"], bmp_info["bmWidth"], 4))
            image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)

            win32gui.DeleteObject(save_bitmap.GetHandle())
            save_dc.DeleteDC()
            mfc_dc.DeleteDC()
            win32gui.ReleaseDC(hwnd, hwnd_dc)

            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            mean_val = float(np.mean(gray))
            std_val = float(np.std(gray))
            # 有效性：标准差>10 且非全白
            if std_val > 10 and mean_val < 250:
                print(f"   截图成功 ({label}, 尺寸: {image.shape[1]}x{image.shape[0]})")
                return image
            else:
                print(f"   {label} 截图无效 (亮度: {mean_val:.1f}, 标准差: {std_val:.1f})")
                return None
        except Exception as e:
            print(f"   {label} 失败: {e}")
            return None

    # 优先级1：窗口尺寸 + flag=2 (PW_RENDERFULLCONTENT) - 截整个窗口含渲染内容
    # 优先级2：窗口尺寸 + flag=0 (默认) - 截整个窗口
    # 优先级3：客户区尺寸 + flag=3 (PW_CLIENTONLY|PW_RENDERFULLCONTENT) - 仅客户区但内容完整
    # 优先级4：客户区尺寸 + flag=1 (PW_CLIENTONLY) - 仅客户区
    for width, height, flag, label in [
        (window_w, window_h, 2, "PrintWindow 窗口 flag=2"),
        (window_w, window_h, 0, "PrintWindow 窗口 flag=0"),
        (client_w, client_h, 3, "PrintWindow 客户区 flag=3"),
        (client_w, client_h, 1, "PrintWindow 客户区 flag=1"),
    ]:
        img = _try_printwindow(width, height, flag, label)
        if img is not None:
            return img

    # 方法5：BitBlt 从窗口DC（用窗口尺寸）
    try:
        hwnd_dc = win32gui.GetWindowDC(hwnd)
        mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
        save_dc = mfc_dc.CreateCompatibleDC()

        save_bitmap = win32ui.CreateBitmap()
        save_bitmap.CreateCompatibleBitmap(mfc_dc, window_w, window_h)
        save_dc.SelectObject(save_bitmap)

        save_dc.BitBlt((0, 0), (window_w, window_h), mfc_dc, (0, 0), win32con.SRCCOPY)

        bmp_info = save_bitmap.GetInfo()
        bmp_str = save_bitmap.GetBitmapBits(True)
        image = np.frombuffer(bmp_str, dtype=np.uint8).reshape(
            (bmp_info["bmHeight"], bmp_info["bmWidth"], 4))
        image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)

        win32gui.DeleteObject(save_bitmap.GetHandle())
        save_dc.DeleteDC()
        mfc_dc.DeleteDC()
        win32gui.ReleaseDC(hwnd, hwnd_dc)

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        if np.std(gray) > 10:
            print(f"   截图成功 (BitBlt, 尺寸: {image.shape[1]}x{image.shape[0]})")
            return image
        else:
            print(f"   BitBlt 截图无效")
    except Exception as e:
        print(f"   BitBlt 失败: {e}")

    # 方法6：屏幕区域截图（需要窗口可见且在前台）
    try:
        from PIL import ImageGrab
        left, top, right, bottom = window_rect
        img = ImageGrab.grab(bbox=(left, top, right, bottom))
        image = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        if np.std(gray) > 10:
            print(f"   截图成功 (屏幕截图, 尺寸: {image.shape[1]}x{image.shape[0]})")
            return image
        else:
            print(f"   屏幕截图无效")
    except Exception as e:
        print(f"   屏幕截图失败: {e}")

    print("   ❌ 所有截图方法均失败")
    return None


def main():
    print("=" * 60)
    print("        实时微信窗口布局检测")
    print("=" * 60)

    window = find_wechat_window()
    if not window:
        print("❌ 未找到微信窗口")
        return

    print(f"找到微信窗口: {window['width']}x{window['height']}")
    print(f"窗口位置: ({window['left']}, {window['top']})")
    print(f"窗口标题: '{window['title']}'")

    print("正在截取微信窗口（不激活窗口）...")

    image = screencap_window(window["hwnd"])
    if image is None:
        print("❌ 截图失败")
        return

    cv2.imwrite("screenshots/raw_screenshot.png", image)
    print(f"📸 原始截图已保存: screenshots/raw_screenshot.png")

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    print(f"\n截图亮度统计:")
    print(f"   平均亮度: {np.mean(gray):.1f}")
    print(f"   标准差: {np.std(gray):.1f}")

    if np.mean(gray) > 240:
        print("\n⚠️ 警告: 截图可能是空白/白色")

    detector = WeChatLayoutDetector()
    detector.detect(image)

    print(f"\n✅ 分析完成，结果已保存至 screenshots/layout_analysis.png")


if __name__ == "__main__":
    main()








