"""分析微信托盘图标闪烁录屏，提取闪烁规律。

目的：
1. 确定托盘图标在视频中的位置（右下角区域）
2. 分析闪烁频率（亮→暗→亮的周期）
3. 推荐截屏间隔（确保能截到闪烁状态）

输入：屏幕录制 2026-07-18 233333.mp4
输出：
  - outputs/tray_blink_analysis.png  亮度变化曲线
  - 控制台输出闪烁周期、推荐截屏间隔
"""
import os
import sys
import cv2
import numpy as np

# 项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VIDEO_PATH = os.path.join(PROJECT_ROOT, "屏幕录制 2026-07-18 233333.mp4")
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "outputs")
os.makedirs(OUTPUT_DIR, exist_ok=True)


def analyze_video():
    if not os.path.exists(VIDEO_PATH):
        print(f"❌ 视频不存在: {VIDEO_PATH}")
        return

    cap = cv2.VideoCapture(VIDEO_PATH)
    if not cap.isOpened():
        print("❌ 无法打开视频")
        return

    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"视频信息: {width}x{height} @ {fps:.1f}fps, 共 {frame_count} 帧, 时长 {frame_count/fps:.1f}s")

    # 视频本身就是托盘图标区域的录屏（50x54 这种小尺寸），直接分析整个帧
    # 不再裁剪右下角区域
    tray_left = 0
    tray_right = width
    tray_top = 0
    tray_bottom = height
    print(f"分析区域（整个帧）: x=[{tray_left},{tray_right}] y=[{tray_top},{tray_bottom}]")

    # 逐帧分析亮度
    frame_idx = 0
    brightness_list = []
    green_ratio_list = []  # 微信绿色像素占比

    # 微信绿色 HSV 范围
    lower_green = np.array([60, 80, 80])
    upper_green = np.array([90, 255, 255])

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        # 提取托盘区域
        tray = frame[tray_top:tray_bottom, tray_left:tray_right]
        if tray.size == 0:
            break

        # 计算平均亮度
        gray = cv2.cvtColor(tray, cv2.COLOR_BGR2GRAY)
        brightness = float(np.mean(gray))
        brightness_list.append(brightness)

        # 计算绿色像素占比（微信图标）
        hsv = cv2.cvtColor(tray, cv2.COLOR_BGR2HSV)
        green_mask = cv2.inRange(hsv, lower_green, upper_green)
        green_ratio = float(np.count_nonzero(green_mask)) / green_mask.size
        green_ratio_list.append(green_ratio)

        frame_idx += 1

    cap.release()

    if not brightness_list:
        print("❌ 未提取到任何帧")
        return

    brightness_arr = np.array(brightness_list)
    green_arr = np.array(green_ratio_list)

    # 分析闪烁：检测绿色占比的显著变化点
    # 微信闪烁时，图标会在"正常绿色"和"闪烁亮色/灰色"之间切换
    green_diff = np.abs(np.diff(green_arr))
    significant_changes = np.where(green_diff > 0.01)[0]  # 变化超过 1%

    print(f"\n=== 闪烁分析 ===")
    print(f"绿色占比范围: {green_arr.min():.4f} ~ {green_arr.max():.4f}")
    print(f"绿色占比均值: {green_arr.mean():.4f}")
    print(f"显著变化点数: {len(significant_changes)}")

    if len(significant_changes) > 1:
        # 计算变化间隔（帧数）
        intervals = np.diff(significant_changes)
        interval_seconds = intervals / fps
        print(f"变化间隔(帧): min={intervals.min()} max={intervals.max()} mean={intervals.mean():.1f}")
        print(f"变化间隔(秒): min={interval_seconds.min():.3f} max={interval_seconds.max():.3f} mean={interval_seconds.mean():.3f}")

        # 闪烁周期 = 2 × 平均间隔（亮→暗→亮为一个周期）
        blink_period = 2 * interval_seconds.mean()
        print(f"估算闪烁周期: {blink_period:.3f} 秒")
        print(f"估算闪烁频率: {1/blink_period:.2f} Hz")

        # 推荐截屏间隔：为了确保截到闪烁状态，间隔应 ≤ 闪烁周期的一半
        recommended_interval = blink_period / 2
        print(f"\n>>> 推荐截屏间隔: ≤ {recommended_interval:.3f} 秒")
        print(f">>> 实际建议: 每 0.2~0.3 秒截一次，连续截 5~10 次取最亮帧")
    else:
        print("⚠️ 未检测到显著闪烁，可能视频中没有闪烁或区域不对")

    # 找到最亮和最暗的帧
    brightest_idx = int(np.argmax(green_arr))
    darkest_idx = int(np.argmin(green_arr))
    print(f"\n最亮帧: #{brightest_idx} (绿色占比 {green_arr[brightest_idx]:.4f})")
    print(f"最暗帧: #{darkest_idx} (绿色占比 {green_arr[darkest_idx]:.4f})")

    # 保存最亮帧和最暗帧的托盘区域，用于图标匹配
    cap = cv2.VideoCapture(VIDEO_PATH)
    for target_idx, name in [(brightest_idx, "brightest"), (darkest_idx, "darkest")]:
        cap.set(cv2.CAP_PROP_POS_FRAMES, target_idx)
        ret, frame = cap.read()
        if ret:
            tray = frame[tray_top:tray_bottom, tray_left:tray_right]
            # 放大保存便于查看
            tray_zoom = cv2.resize(tray, (tray.shape[1] * 4, tray.shape[0] * 4), interpolation=cv2.INTER_NEAREST)
            path = os.path.join(OUTPUT_DIR, f"tray_{name}_frame{target_idx}.png")
            cv2.imwrite(path, tray_zoom)
            print(f"保存 {name} 帧托盘区域: {path}")
    cap.release()

    # 绘制亮度变化曲线
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8))
        time_axis = np.arange(len(brightness_arr)) / fps

        ax1.plot(time_axis, brightness_arr, color="blue", linewidth=0.8)
        ax1.set_title("Tray Brightness Over Time")
        ax1.set_xlabel("Time (s)")
        ax1.set_ylabel("Brightness")
        ax1.grid(True, alpha=0.3)

        ax2.plot(time_axis, green_arr, color="green", linewidth=0.8)
        ax2.set_title("WeChat Green Pixel Ratio Over Time")
        ax2.set_xlabel("Time (s)")
        ax2.set_ylabel("Green Ratio")
        ax2.grid(True, alpha=0.3)

        plt.tight_layout()
        chart_path = os.path.join(OUTPUT_DIR, "tray_blink_analysis.png")
        plt.savefig(chart_path, dpi=100)
        plt.close()
        print(f"\n亮度变化曲线已保存: {chart_path}")
    except ImportError:
        print("⚠️ matplotlib 未安装，跳过绘图")


if __name__ == "__main__":
    analyze_video()
