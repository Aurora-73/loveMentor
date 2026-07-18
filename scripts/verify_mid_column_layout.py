"""校验中间栏位置判定。

把 dynamic_detector 原始输出和 find_search_bar_in_image 返回值都画出来，让用户对比哪个正确。

用法：
    python -X utf8 scripts/verify_mid_column_layout.py
"""
import os
import sys
import time

import ctypes
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

import cv2
import numpy as np

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
WECHAT_SENDER_DIR = os.path.join(PROJECT_ROOT, "engine", "wechat_sender")
sys.path.insert(0, WECHAT_SENDER_DIR)

from test_current_wechat import screencap_window
from wechat_window_utils import find_wechat_window
from click_search_and_input import safe_set_foreground_window
from click_avatar_in_search_window import find_search_bar_in_image
from dynamic_detector import WeChatLayoutDetector
from open_wechat_window import open_wechat_window_robust


def ensure_wechat_window():
    window = find_wechat_window()
    if window:
        return window
    print("⚠️ 微信窗口不存在，尝试唤醒...")
    if not open_wechat_window_robust(timeout=10.0):
        return None
    time.sleep(0.5)
    return find_wechat_window()


def main():
    print("=" * 60)
    print("  校验中间栏位置判定")
    print("=" * 60)

    window = ensure_wechat_window()
    if not window:
        print("❌ 未找到微信窗口")
        return
    hwnd_main = window["hwnd"]
    print(f"[1] 微信窗口: hwnd={hwnd_main} size={window['width']}x{window['height']}")

    safe_set_foreground_window(hwnd_main)
    time.sleep(1.5)

    pw_image = screencap_window(hwnd_main)
    if pw_image is None:
        print("❌ 截图失败")
        return
    h_img, w_img = pw_image.shape[:2]
    print(f"[2] 截图: {w_img}x{h_img}")

    # 方法A: dynamic_detector 原始输出
    detector = WeChatLayoutDetector()
    nav_right_a, session_right_a = detector.detect(pw_image)
    print(f"\n[3A] dynamic_detector 原始输出:")
    print(f"     nav_right = {nav_right_a}")
    print(f"     session_right = {session_right_a}")
    print(f"     中间栏范围: {nav_right_a} ~ {session_right_a}  (宽度 {session_right_a - nav_right_a}px)")
    print(f"     中间栏中心: x = {(nav_right_a + session_right_a) // 2}")

    # 方法B: find_search_bar_in_image 返回值
    search_x_b, search_y_b, nav_right_b, session_right_b = find_search_bar_in_image(pw_image)
    print(f"\n[3B] find_search_bar_in_image 返回值:")
    print(f"     nav_right = {nav_right_b}")
    print(f"     session_right = {session_right_b}")
    print(f"     中间栏范围: {nav_right_b} ~ {session_right_b}  (宽度 {session_right_b - nav_right_b}px)")
    print(f"     中间栏中心: x = {(nav_right_b + session_right_b) // 2}")
    print(f"     搜索栏位置: ({search_x_b}, {search_y_b})")

    # 判定差异
    print(f"\n[4] 差异:")
    print(f"     nav_right 差: {nav_right_a - nav_right_b}px")
    print(f"     session_right 差: {session_right_a - session_right_b}px")
    if nav_right_a != nav_right_b or session_right_a != session_right_b:
        print(f"     ⚠️ 两者不一致！可能是 find_search_bar_in_image 的'异常判定'误触发覆盖了正确值")
        print(f"        异常判定条件: nav_right < 100 or session_right < 300 or session_right <= nav_right")
        print(f"        原始值 nav_right={nav_right_a} < 100 → {'是' if nav_right_a < 100 else '否'}，触发覆盖")

    # 画对比图
    annotated = pw_image.copy()
    # 方法A: 蓝色（dynamic_detector 原始）
    cv2.line(annotated, (nav_right_a, 0), (nav_right_a, h_img), (255, 0, 0), 2)
    cv2.line(annotated, (session_right_a, 0), (session_right_a, h_img), (255, 0, 0), 2)
    cv2.putText(annotated, f"A: nav_right={nav_right_a}", (nav_right_a + 5, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 1, cv2.LINE_AA)
    cv2.putText(annotated, f"A: session_right={session_right_a}", (session_right_a + 5, 60),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 1, cv2.LINE_AA)
    # 画A的中心
    mid_x_a = (nav_right_a + session_right_a) // 2
    cv2.line(annotated, (mid_x_a, 0), (mid_x_a, h_img), (255, 0, 0), 1)
    cv2.putText(annotated, f"A: center={mid_x_a}", (mid_x_a + 5, 90),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 1, cv2.LINE_AA)
    # 画A的40%随机区域
    width_a = session_right_a - nav_right_a
    a_x_min = int(nav_right_a + width_a * 0.3)
    a_x_max = int(nav_right_a + width_a * 0.7)
    cv2.rectangle(annotated, (a_x_min, int(h_img * 0.3)), (a_x_max, int(h_img * 0.7)),
                  (255, 0, 0), 2)

    # 方法B: 红色（find_search_bar_in_image 返回值）
    cv2.line(annotated, (nav_right_b, h_img // 2), (nav_right_b, h_img), (0, 0, 255), 2)
    cv2.line(annotated, (session_right_b, h_img // 2), (session_right_b, h_img), (0, 0, 255), 2)
    cv2.putText(annotated, f"B: nav_right={nav_right_b}", (nav_right_b + 5, h_img - 90),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1, cv2.LINE_AA)
    cv2.putText(annotated, f"B: session_right={session_right_b}", (session_right_b + 5, h_img - 60),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1, cv2.LINE_AA)
    mid_x_b = (nav_right_b + session_right_b) // 2
    cv2.line(annotated, (mid_x_b, h_img // 2), (mid_x_b, h_img), (0, 0, 255), 1)
    cv2.putText(annotated, f"B: center={mid_x_b}", (mid_x_b + 5, h_img - 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1, cv2.LINE_AA)
    # 画B的40%随机区域
    width_b = session_right_b - nav_right_b
    b_x_min = int(nav_right_b + width_b * 0.3)
    b_x_max = int(nav_right_b + width_b * 0.7)
    cv2.rectangle(annotated, (b_x_min, int(h_img * 0.3)), (b_x_max, int(h_img * 0.7)),
                  (0, 0, 255), 2)

    # 搜索栏位置
    cv2.circle(annotated, (search_x_b, search_y_b), 12, (0, 255, 255), 3)
    cv2.putText(annotated, "Search Bar", (search_x_b + 20, search_y_b - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2, cv2.LINE_AA)

    out_path = os.path.join(WECHAT_SENDER_DIR, "outputs", "verify_mid_column_layout.png")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    cv2.imwrite(out_path, annotated)
    print(f"\n[5] 对比图已保存: {out_path}")
    print(f"    蓝色: dynamic_detector 原始输出（应该正确）")
    print(f"    红色: find_search_bar_in_image 返回值（可能被覆盖）")
    print(f"    黄色圆圈: 搜索栏位置")
    print(f"    蓝框: A 的40%随机区域")
    print(f"    红框: B 的40%随机区域")

    print("\n" + "=" * 60)
    print("  请查看对比图，确认哪个判定正确（蓝色还是红色）")
    print("=" * 60)


if __name__ == "__main__":
    main()
