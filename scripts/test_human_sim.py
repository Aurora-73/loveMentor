"""human_sim 模块单元测试：验证分段、抖动等逻辑正确。

运行：
    python -X utf8 scripts/test_human_sim.py
"""
import os
import sys

# 加入 wechat_sender 目录
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_WECHAT_SENDER_DIR = os.path.join(_PROJECT_ROOT, "engine", "wechat_sender")
sys.path.insert(0, _WECHAT_SENDER_DIR)

from human_sim import (
    _split_text,
    _jitter_point,
    SHORT_MSG_THRESHOLD,
    MID_MSG_THRESHOLD,
    SHORT_SEG_MIN,
    SHORT_SEG_MAX,
    LONG_SEG_MIN,
    LONG_SEG_MAX,
    DEFAULT_JITTER_RADIUS,
)


def test_split_text():
    """测试分段逻辑"""
    print("=" * 60)
    print("测试 1: 文本分段")
    print("=" * 60)

    cases = [
        ("晚上好", "短消息（不分段）"),
        ("你好", "极短消息"),
        ("你好，今天天气不错，我们一起出去玩吧", "中等消息（20-100 字符）"),
        ("这是一段很长的消息，" * 10, "长消息（>100 字符）"),
    ]

    for text, desc in cases:
        segments = _split_text(text)
        print(f"\n[{desc}]")
        print(f"  原文: {text!r}（{len(text)} 字符）")
        print(f"  分段数: {len(segments)}")
        for i, seg in enumerate(segments, 1):
            print(f"    第 {i} 段: {seg!r}（{len(seg)} 字符）")
        # 验证拼接后与原文一致
        assert "".join(segments) == text, f"拼接不一致: {''.join(segments)} != {text}"

    # 验证短消息不分段
    assert len(_split_text("a" * SHORT_MSG_THRESHOLD)) == 1
    assert len(_split_text("a" * (SHORT_MSG_THRESHOLD + 1))) > 1
    print("\n✅ 分段测试通过")


def test_jitter_point():
    """测试位置抖动"""
    print("\n" + "=" * 60)
    print("测试 2: 位置抖动")
    print("=" * 60)

    cx, cy = 500, 500
    radius = DEFAULT_JITTER_RADIUS
    print(f"\n中心点: ({cx}, {cy}), 抖动半径: {radius}")

    points = []
    for i in range(10):
        px, py = _jitter_point(cx, cy, radius)
        points.append((px, py))
        dx = px - cx
        dy = py - cy
        dist = (dx * dx + dy * dy) ** 0.5
        print(f"  #{i+1}: ({px}, {py})  偏移=({dx:+d}, {dy:+d})  距离={dist:.2f}")
        # 验证抖动在半径内
        assert dist <= radius + 0.5, f"抖动超出半径: {dist} > {radius}"

    # 验证 radius=0 时返回原点
    px, py = _jitter_point(cx, cy, 0)
    assert (px, py) == (cx, cy), f"radius=0 应返回原点: ({px}, {py}) != ({cx}, {cy})"
    print(f"\n  radius=0 时返回原点: ({px}, {py}) ✅")

    # 验证多次抖动有随机性（不会全部相同）
    unique_points = set(points)
    print(f"  10 次抖动得到 {len(unique_points)} 个不同点")
    assert len(unique_points) > 1, "抖动应该有随机性"
    print("\n✅ 抖动测试通过")


def test_segment_length_range():
    """测试段长在规定范围内"""
    print("\n" + "=" * 60)
    print("测试 3: 段长范围")
    print("=" * 60)

    # 中等消息：段长应在 SHORT_SEG_MIN ~ SHORT_SEG_MAX 之间（最后一段可能更短）
    mid_text = "a" * 50  # 50 字符
    segments = _split_text(mid_text)
    print(f"\n中等消息 ({len(mid_text)} 字符) 分段: {len(segments)} 段")
    for i, seg in enumerate(segments):
        print(f"  第 {i+1} 段长度: {len(seg)}")
        if i < len(segments) - 1:
            assert SHORT_SEG_MIN <= len(seg) <= SHORT_SEG_MAX, \
                f"中等消息段长 {len(seg)} 不在 [{SHORT_SEG_MIN}, {SHORT_SEG_MAX}]"

    # 长消息：段长应在 LONG_SEG_MIN ~ LONG_SEG_MAX 之间（最后一段可能更短）
    long_text = "b" * 200
    segments = _split_text(long_text)
    print(f"\n长消息 ({len(long_text)} 字符) 分段: {len(segments)} 段")
    for i, seg in enumerate(segments):
        print(f"  第 {i+1} 段长度: {len(seg)}")
        if i < len(segments) - 1:
            assert LONG_SEG_MIN <= len(seg) <= LONG_SEG_MAX, \
                f"长消息段长 {len(seg)} 不在 [{LONG_SEG_MIN}, {LONG_SEG_MAX}]"

    print("\n✅ 段长范围测试通过")


if __name__ == "__main__":
    test_split_text()
    test_jitter_point()
    test_segment_length_range()
    print("\n" + "=" * 60)
    print("  所有测试通过 ✅")
    print("=" * 60)
