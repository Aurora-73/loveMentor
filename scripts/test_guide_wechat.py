"""验证 guide 工具的 reference/wechat 主题正确注册。

运行：
    python -X utf8 scripts/test_guide_wechat.py
"""
import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)

from mcp_server.tools_guide import guide_func, GUIDES, TOPIC_ALIASES, _list_topics


def test_wechat_topic_exists():
    """验证 reference/wechat 主题存在"""
    assert "reference/wechat" in GUIDES, "reference/wechat 主题未在 GUIDES 中"
    content = GUIDES["reference/wechat"]
    assert "会抢鼠标" in content, "缺少抢鼠标提醒"
    assert "wechat_send" in content, "缺少 wechat_send 说明"
    assert "open_wechat_window" in content, "缺少 open_wechat_window 说明"
    assert "防封号" in content, "缺少防封号机制说明"
    print("✅ reference/wechat 主题内容完整")


def test_guide_func_returns_wechat():
    """验证 guide_func('reference/wechat') 能返回内容"""
    result = guide_func("reference/wechat")
    assert "微信发消息工具" in result, "guide_func 返回内容不正确"
    assert "会抢鼠标" in result, "缺少抢鼠标提醒"
    print("✅ guide_func('reference/wechat') 返回正确")


def test_chinese_alias():
    """验证中文别名"""
    aliases = ["微信", "发消息", "wechat", "微信发消息"]
    for alias in aliases:
        assert alias in TOPIC_ALIASES, f"中文别名 {alias!r} 未注册"
        assert TOPIC_ALIASES[alias] == "reference/wechat", f"别名 {alias!r} 映射错误"
    print(f"✅ 中文别名注册正确：{aliases}")


def test_list_topics_includes_wechat():
    """验证 _list_topics 包含 reference/wechat"""
    result = _list_topics()
    assert "reference/wechat" in result, "_list_topics 未包含 reference/wechat"
    print("✅ _list_topics 包含 reference/wechat")


def test_guide_func_with_alias():
    """验证通过中文别名调用"""
    result = guide_func("微信")
    assert "微信发消息工具" in result, "通过别名'微信'调用失败"
    print("✅ 通过别名 guide('微信') 调用成功")


if __name__ == "__main__":
    print("=" * 60)
    print("测试 guide 工具的 reference/wechat 主题")
    print("=" * 60)
    test_wechat_topic_exists()
    test_guide_func_returns_wechat()
    test_chinese_alias()
    test_list_topics_includes_wechat()
    test_guide_func_with_alias()
    print("\n" + "=" * 60)
    print("  所有测试通过 ✅")
    print("=" * 60)
