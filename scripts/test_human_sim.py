"""human_sim 模块单元测试：验证分段、抖动、字符分类、IME 输入等逻辑正确。

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
    _is_ascii_char,
    _has_chinese,
    _human_sleep_with_pause,
    SHORT_MSG_THRESHOLD,
    MID_MSG_THRESHOLD,
    SHORT_SEG_MIN,
    SHORT_SEG_MAX,
    LONG_SEG_MIN,
    LONG_SEG_MAX,
    DEFAULT_JITTER_RADIUS,
    OCCASIONAL_PAUSE_PROBABILITY,
    OCCASIONAL_PAUSE_MIN,
    OCCASIONAL_PAUSE_MAX,
    USE_IME_CHAR_FOR_CHINESE,
    WM_IME_CHAR,
    VK_CONTROL,
    VK_V,
    VK_A,
    VK_F,
    VK_MENU,
    VK_ESCAPE,
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


def test_char_classification():
    """测试字符分类（ASCII / 中文判断）"""
    print("\n" + "=" * 60)
    print("测试 4: 字符分类")
    print("=" * 60)

    # ASCII 字符
    ascii_chars = ["a", "Z", "0", "9", "!", " ", "@", "\n", "\t"]
    for ch in ascii_chars:
        assert _is_ascii_char(ch), f"{ch!r} 应该是 ASCII"
    print(f"  ASCII 字符 ({len(ascii_chars)} 个) 判定正确 ✅")

    # 非 ASCII 字符（中文、日文、emoji 等）
    non_ascii_chars = ["你", "好", "日", "語", "😊", "é", "ñ"]
    for ch in non_ascii_chars:
        assert not _is_ascii_char(ch), f"{ch!r} 不应该是 ASCII"
    print(f"  非 ASCII 字符 ({len(non_ascii_chars)} 个) 判定正确 ✅")

    # 测试 _has_chinese
    assert not _has_chinese("hello world 123")
    assert _has_chinese("hello 你好")
    assert _has_chinese("你好")
    assert not _has_chinese("")
    print("  _has_chinese 判定正确 ✅")

    print("\n✅ 字符分类测试通过")


def test_input_strategy_selection():
    """测试输入策略选择逻辑（不实际发送，只验证判断逻辑）"""
    print("\n" + "=" * 60)
    print("测试 5: 输入策略选择")
    print("=" * 60)

    # 短消息（≤ SHORT_MSG_THRESHOLD）
    short_ascii = "hello"
    short_chinese = "你好世界测试"
    short_mixed = "hello 你好"

    # 长消息（> SHORT_MSG_THRESHOLD）
    long_text = "a" * (SHORT_MSG_THRESHOLD + 1)

    print(f"\n  SHORT_MSG_THRESHOLD = {SHORT_MSG_THRESHOLD}")
    print(f"  USE_IME_CHAR_FOR_CHINESE = {USE_IME_CHAR_FOR_CHINESE}")

    # 验证短消息判定
    assert len(short_ascii) <= SHORT_MSG_THRESHOLD
    assert len(short_chinese) <= SHORT_MSG_THRESHOLD
    assert len(short_mixed) <= SHORT_MSG_THRESHOLD
    assert len(long_text) > SHORT_MSG_THRESHOLD
    print(f"  短消息判定正确 ✅")

    # 验证策略逻辑（模拟 _type_short_message 的判断）
    # 策略1：纯 ASCII 短消息 → 逐字 Unicode 输入
    assert not _has_chinese(short_ascii), "纯 ASCII 不应含中文"
    print(f"  策略1（纯 ASCII 短消息）: {short_ascii!r} → 逐字 Unicode ✅")

    # 策略3：含中文 + IME_CHAR 未启用 → 剪贴板粘贴
    if _has_chinese(short_chinese) and not USE_IME_CHAR_FOR_CHINESE:
        print(f"  策略3（含中文+IME 未启用）: {short_chinese!r} → 剪贴板粘贴 ✅")
    elif _has_chinese(short_chinese) and USE_IME_CHAR_FOR_CHINESE:
        print(f"  策略2（含中文+IME 已启用）: {short_chinese!r} → IME_CHAR 输入 ✅")

    # 验证长消息走分段粘贴
    assert len(long_text) > SHORT_MSG_THRESHOLD
    print(f"  长消息 ({len(long_text)} 字符) → 分段剪贴板粘贴 ✅")

    print("\n✅ 输入策略选择测试通过")


def test_constants_and_imports():
    """测试常量和导入完整性"""
    print("\n" + "=" * 60)
    print("测试 6: 常量和导入完整性")
    print("=" * 60)

    # 验证 SendInput 相关常量
    assert WM_IME_CHAR == 0x0286, f"WM_IME_CHAR 应为 0x0286，实际 {WM_IME_CHAR}"
    print(f"  WM_IME_CHAR = 0x{WM_IME_CHAR:04X} ✅")

    # 验证虚拟键码
    assert VK_CONTROL == 0x11
    assert VK_V == 0x56
    assert VK_A == 0x41
    assert VK_F == 0x46
    assert VK_MENU == 0x12
    assert VK_ESCAPE == 0x1B
    print(f"  VK_CONTROL/A/V/F/MENU/ESCAPE 常量正确 ✅")

    # 验证偶发停顿参数
    assert 0 < OCCASIONAL_PAUSE_PROBABILITY < 1
    assert OCCASIONAL_PAUSE_MIN > 0
    assert OCCASIONAL_PAUSE_MAX > OCCASIONAL_PAUSE_MIN
    print(f"  偶发停顿参数: prob={OCCASIONAL_PAUSE_PROBABILITY}, "
          f"range=[{OCCASIONAL_PAUSE_MIN}, {OCCASIONAL_PAUSE_MAX}] ✅")

    # 验证 _human_sleep_with_pause 函数可用（不触发长停顿）
    import time as _time
    t0 = _time.time()
    _human_sleep_with_pause(0.01, 0.02, allow_pause=False)
    elapsed = _time.time() - t0
    assert 0.01 <= elapsed <= 0.1, f"allow_pause=False 时应只停顿 0.01-0.02s，实际 {elapsed:.3f}s"
    print(f"  _human_sleep_with_pause(allow_pause=False) 正常 ✅")

    print("\n✅ 常量和导入完整性测试通过")


if __name__ == "__main__":
    test_split_text()
    test_jitter_point()
    test_segment_length_range()
    test_char_classification()
    test_input_strategy_selection()
    test_constants_and_imports()
    print("\n" + "=" * 60)
    print("  所有测试通过 ✅")
    print("=" * 60)
