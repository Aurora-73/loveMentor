"""测试随机点击中间栏50次，观察是否有潜在风险。

执行50次随机点击中间栏60%区域，每次点击间隔 1.5 秒，让用户观察是否有副作用：
- 是否点中了某个聊天切换了会话
- 是否弹出了菜单
- 是否触发了其他不期望的行为

每次点击前会输出位置信息，并截图记录最后一次点击位置。

用法：
    python -X utf8 scripts/test_random_mid_click.py
    python -X utf8 scripts/test_random_mid_click.py --count 20  # 自定义次数
"""
import os
import sys
import time
import random
import argparse

import ctypes
import ctypes.wintypes as wintypes

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

import cv2

# 项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
WECHAT_SENDER_DIR = os.path.join(PROJECT_ROOT, "engine", "wechat_sender")
sys.path.insert(0, WECHAT_SENDER_DIR)

from test_current_wechat import screencap_window
from wechat_window_utils import find_wechat_window
from click_search_and_input import safe_set_foreground_window, client_to_screen, get_client_offset, physical_click
from click_avatar_in_search_window import find_search_bar_in_image
from open_wechat_window import open_wechat_window_robust
from logger import get_logger

logger = get_logger(__name__)


def ensure_wechat_window():
    """确保微信窗口存在（不存在则唤醒）。"""
    window = find_wechat_window()
    if window:
        return window
    print("⚠️ 微信窗口不存在，尝试唤醒...")
    if not open_wechat_window_robust(timeout=10.0):
        print("❌ 微信窗口唤醒失败")
        return None
    time.sleep(0.5)
    return find_wechat_window()


def main():
    parser = argparse.ArgumentParser(description="测试随机点击中间栏 N 次")
    parser.add_argument("--count", type=int, default=50, help="点击次数（默认 50）")
    parser.add_argument("--interval", type=float, default=1.5, help="点击间隔秒数（默认 1.5）")
    parser.add_argument("--no-click", action="store_true",
                        help="只移动鼠标不点击（用于纯位置验证）")
    args = parser.parse_args()

    print("=" * 60)
    print(f"  测试随机点击中间栏 {args.count} 次")
    print(f"  间隔: {args.interval}秒  模式: {'移动' if args.no_click else '点击'}")
    print("=" * 60)

    # 1. 确保微信窗口存在
    window = ensure_wechat_window()
    if not window:
        return
    hwnd_main = window["hwnd"]
    print(f"[1] 微信窗口: hwnd={hwnd_main} size={window['width']}x{window['height']}")

    # 2. 设为前台
    safe_set_foreground_window(hwnd_main)
    time.sleep(1.5)

    # 3. 截图 + 布局检测
    pw_image = screencap_window(hwnd_main)
    if pw_image is None:
        print("❌ 截图失败")
        return
    pw_search_x, pw_search_y, nav_right, session_right = find_search_bar_in_image(pw_image)
    h_img, w_img = pw_image.shape[:2]
    offset_x, offset_y = get_client_offset(hwnd_main)
    mid_col_width = session_right - nav_right
    print(f"\n[2] 布局:")
    print(f"    nav_right={nav_right}, session_right={session_right}, 中间栏宽度={mid_col_width}px")
    print(f"    图片尺寸: {w_img}x{h_img}")
    print(f"    偏移: ({offset_x}, {offset_y})")

    # 中间栏70%区域边界（客户区坐标）
    x_min = nav_right + int(mid_col_width * 0.15)
    x_max = nav_right + int(mid_col_width * 0.85)
    y_min = int(h_img * 0.15)
    y_max = int(h_img * 0.85)
    print(f"\n[3] 70%区域（客户区坐标）:")
    print(f"    x: {x_min} ~ {x_max}  (范围 {x_max - x_min}px)")
    print(f"    y: {y_min} ~ {y_max}  (范围 {y_max - y_min}px)")

    # 4. 随机点击 N 次
    print(f"\n[4] 开始随机{'移动' if args.no_click else '点击'} {args.count} 次:")
    print("-" * 60)
    positions = []
    for i in range(args.count):
        # 随机位置
        mid_x = random.randint(x_min, x_max)
        mid_y = random.randint(y_min, y_max)
        mid_screen_x, mid_screen_y = client_to_screen(
            hwnd_main, mid_x - offset_x, mid_y - offset_y
        )
        positions.append((mid_x, mid_y, mid_screen_x, mid_screen_y))

        # 移动鼠标
        ctypes.windll.user32.SetCursorPos(mid_screen_x, mid_screen_y)
        time.sleep(0.2)

        if not args.no_click:
            physical_click(mid_screen_x, mid_screen_y)

        # 简洁输出
        marker = "🖱️ " if not args.no_click else "📍 "
        print(f"  #{i+1:3d}/{args.count} {marker} 客户区({mid_x:4d},{mid_y:4d}) "
              f"屏幕({mid_screen_x:4d},{mid_screen_y:4d})")

        # 等待用户观察
        if i < args.count - 1:
            time.sleep(args.interval)

    # 5. 标注所有点击位置
    print("-" * 60)
    print(f"\n[5] 标注所有点击位置...")
    annotated = pw_image.copy()
    # 画中间栏边界（蓝色竖线）
    cv2.line(annotated, (nav_right, 0), (nav_right, h_img), (255, 0, 0), 2)
    cv2.line(annotated, (session_right, 0), (session_right, h_img), (255, 0, 0), 2)
    cv2.putText(annotated, f"nav_right={nav_right}", (nav_right + 5, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 1, cv2.LINE_AA)
    cv2.putText(annotated, f"session_right={session_right}", (session_right + 5, 60),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 1, cv2.LINE_AA)
    # 画70%随机区域边界（蓝色框）
    cv2.rectangle(annotated, (x_min, y_min), (x_max, y_max), (255, 0, 0), 2)
    cv2.putText(annotated, "70% Click Region",
                (x_min, y_min - 5),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 1, cv2.LINE_AA)
    # 标注所有点击位置（黄色小点）
    for x, y, _, _ in positions:
        cv2.circle(annotated, (x, y), 4, (0, 255, 255), -1)

    out_path = os.path.join(WECHAT_SENDER_DIR, "outputs", "test_random_mid_click.png")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    cv2.imwrite(out_path, annotated)
    print(f"    标注图: {out_path}")
    print(f"    蓝色竖线: 中间栏边界 (nav_right={nav_right}, session_right={session_right})")
    print(f"    蓝色框: 70%随机点击区域")
    print(f"    黄点: 所有 {args.count} 次点击位置")

    # 6. 统计
    print(f"\n[6] 统计:")
    x_range = (min(p[0] for p in positions), max(p[0] for p in positions))
    y_range = (min(p[1] for p in positions), max(p[1] for p in positions))
    print(f"    x 客户区范围: {x_range[0]} ~ {x_range[1]}")
    print(f"    y 客户区范围: {y_range[0]} ~ {y_range[1]}")
    print(f"    唯一位置数: {len(set((p[0], p[1]) for p in positions))}/{args.count}")

    print("\n" + "=" * 60)
    print(f"  测试完成（{args.count} 次{'移动' if args.no_click else '点击'}）")
    print("  请观察微信界面是否有副作用：")
    print("  - 是否切换到了某个聊天")
    print("  - 是否弹出了菜单")
    print("  - 是否触发了其他不期望的行为")
    print("=" * 60)


if __name__ == "__main__":
    main()
