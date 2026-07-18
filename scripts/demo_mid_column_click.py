"""演示"点击中间栏激活焦点"的点击位置。

只移动鼠标到中间栏中心 + 截图标注，不实际点击，让用户直观看到点击位置。

用法：
    python -X utf8 scripts/demo_mid_column_click.py
"""
import os
import sys
import time

import ctypes
import ctypes.wintypes as wintypes

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

import cv2
import numpy as np

# 项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
WECHAT_SENDER_DIR = os.path.join(PROJECT_ROOT, "engine", "wechat_sender")
sys.path.insert(0, WECHAT_SENDER_DIR)

from test_current_wechat import screencap_window
from wechat_window_utils import find_wechat_window
from click_search_and_input import safe_set_foreground_window, client_to_screen, get_client_offset
from click_avatar_in_search_window import find_search_bar_in_image
from logger import get_logger

logger = get_logger(__name__)

user32 = ctypes.windll.user32


def main():
    print("=" * 60)
    print("  演示：点击中间栏激活焦点的位置")
    print("=" * 60)

    # 1. 找微信窗口
    window = find_wechat_window()
    if not window:
        print("❌ 未找到微信窗口")
        return
    hwnd_main = window["hwnd"]
    print(f"[1] 微信窗口: hwnd={hwnd_main} size={window['width']}x{window['height']}")

    # 2. 设为前台
    safe_set_foreground_window(hwnd_main)
    time.sleep(1.5)

    # 3. 截图
    pw_image = screencap_window(hwnd_main)
    if pw_image is None:
        print("❌ 截图失败")
        return
    print(f"[2] 截图成功: {pw_image.shape[1]}x{pw_image.shape[0]}")

    # 4. 找搜索栏位置 + 布局检测
    pw_search_x, pw_search_y, nav_right, session_right = find_search_bar_in_image(pw_image)
    print(f"[3] 布局检测:")
    print(f"    导航栏右边界 (nav_right): {nav_right}px")
    print(f"    会话列表右边界 (session_right): {session_right}px")
    print(f"    搜索栏位置: ({pw_search_x}, {pw_search_y})")

    # 5. 计算中间栏中心
    offset_x, offset_y = get_client_offset(hwnd_main)
    h_img, w_img = pw_image.shape[:2]
    mid_x = (nav_right + session_right) // 2
    mid_y = h_img // 2
    mid_screen_x, mid_screen_y = client_to_screen(
        hwnd_main, mid_x - offset_x, mid_y - offset_y
    )
    print(f"\n[4] 中间栏中心点击位置:")
    print(f"    客户区坐标: ({mid_x}, {mid_y})")
    print(f"    偏移: offset=({offset_x}, {offset_y})")
    print(f"    屏幕坐标: ({mid_screen_x}, {mid_screen_y})")

    # 6. 标注截图
    annotated = pw_image.copy()
    # 标注搜索栏
    cv2.circle(annotated, (pw_search_x, pw_search_y), 12, (0, 255, 255), 3)
    cv2.putText(annotated, "Search Bar", (pw_search_x + 20, pw_search_y - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2, cv2.LINE_AA)
    # 标注中间栏中心
    cv2.drawMarker(annotated, (mid_x, mid_y), (0, 0, 255),
                   markerType=cv2.MARKER_CROSS, markerSize=40, thickness=3, line_type=cv2.LINE_AA)
    cv2.circle(annotated, (mid_x, mid_y), 20, (0, 0, 255), 2)
    cv2.putText(annotated, "Mid Column Click",
                (mid_x + 30, mid_y + 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2, cv2.LINE_AA)
    # 画垂直分割线
    cv2.line(annotated, (nav_right, 0), (nav_right, h_img), (255, 0, 0), 2)
    cv2.putText(annotated, f"nav_right={nav_right}", (nav_right + 5, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 1, cv2.LINE_AA)
    cv2.line(annotated, (session_right, 0), (session_right, h_img), (0, 255, 0), 2)
    cv2.putText(annotated, f"session_right={session_right}", (session_right + 5, 60),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1, cv2.LINE_AA)

    out_path = os.path.join(WECHAT_SENDER_DIR, "outputs", "demo_mid_column_click.png")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    cv2.imwrite(out_path, annotated)
    print(f"\n[5] 标注图已保存: {out_path}")
    print(f"    黄色圆圈: 搜索栏位置（即将点击搜索栏）")
    print(f"    红色十字: 中间栏中心点击位置（先点这里激活焦点）")
    print(f"    蓝色竖线: 导航栏右边界 (x={nav_right})")
    print(f"    绿色竖线: 会话列表右边界 (x={session_right})")

    # 7. 移动鼠标到中间栏中心（不点击）
    print(f"\n[6] 移动鼠标到中间栏中心 ({mid_screen_x}, {mid_screen_y})，2秒后移动...")
    time.sleep(2)
    user32.SetCursorPos(mid_screen_x, mid_screen_y)
    print(f"    鼠标已移动，悬停 3 秒...")
    time.sleep(3)

    # 8. 再移动到搜索栏（演示后续会点哪里）
    search_screen_x, search_screen_y = client_to_screen(
        hwnd_main, pw_search_x - offset_x, pw_search_y - offset_y
    )
    print(f"\n[7] 移动鼠标到搜索栏 ({search_screen_x}, {search_screen_y})...")
    user32.SetCursorPos(search_screen_x, search_screen_y)
    time.sleep(2)

    print("\n" + "=" * 60)
    print("  演示完成")
    print("  说明:")
    print("  - 中间栏中心点击是为了在 Ctrl+F 之前把焦点放到微信窗口客户区")
    print("  - 位置在导航栏(蓝色线)和会话列表(绿色线)之间的中点，y取窗口高度一半")
    print("  - 这个位置通常落在会话列表区域中间，点击不会有副作用（不会打开任何聊天）")
    print("  - 之后会按 Ctrl+F 打开搜索栏")
    print("=" * 60)


if __name__ == "__main__":
    main()
