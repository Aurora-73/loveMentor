"""中文编码专项测试。

测试 3 个场景：
1. 返回中文内容（工具返回的 dict 中中文不乱码）
2. 接收中文参数（工具能正确接收中文 name/query）
3. 错误信息中文（错误返回中中文不乱码）
"""

import sys
import json

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')


def test_return_chinese():
    """场景 1：返回中文内容不乱码。"""
    from mcp_server.tools_read import person_rank
    result = person_rank()
    if "error" in result:
        assert "请检查" in result.get("suggestion", ""), f"错误建议应含中文: {result}"
        print("[PASS] 场景1-返回中文: 错误路径中文正常")
    else:
        assert "week" in result, f"rank_data 应返回 week 字段: {list(result.keys())}"
        if result.get("rankings"):
            name = result["rankings"][0].get("name", "")
            assert isinstance(name, str), f"name 应为 str: {type(name)}"
            print(f"[PASS] 场景1-返回中文: 排名含中文名 '{name}'")
        else:
            print("[PASS] 场景1-返回中文: 排名为空（无数据），结构正常")


def test_receive_chinese_param():
    """场景 2：接收中文参数不乱码。"""
    from mcp_server.tools_read import person_brief
    result = person_brief("不存在的中文人名")
    assert "error" in result, f"不存在的人应返回 error: {result}"
    assert result["error"] == "PERSON_NOT_FOUND", f"错误码应为 PERSON_NOT_FOUND: {result['error']}"
    assert "不存在的中文人名" in result["message"], f"message 应含原始中文参数: {result['message']}"
    print(f"[PASS] 场景2-接收中文参数: '{result['message']}'")


def test_error_message_chinese():
    """场景 3：错误信息中文不乱码。"""
    from mcp_server.tools_read import person_metrics
    result = person_metrics("测试人名")
    assert "error" in result, f"不存在的人应返回 error: {result}"
    suggestion = result.get("suggestion", "")
    assert isinstance(suggestion, str) and len(suggestion) > 0, f"suggestion 应为非空中文: {suggestion}"
    for ch in suggestion:
        assert ord(ch) != 0xFFFD, f"发现乱码字符 U+FFFD: {suggestion}"
    print(f"[PASS] 场景3-错误信息中文: '{suggestion}'")


def test_json_serialization_chinese():
    """附加场景：dict 能正确 JSON 序列化中文。"""
    from mcp_server.tools_read import person_brief
    result = person_brief("测试")
    json_str = json.dumps(result, ensure_ascii=False)
    assert "测试" in json_str or "未找到" in json_str, f"JSON 序列化应保留中文: {json_str[:100]}"
    decoded = json.loads(json_str)
    assert isinstance(decoded, dict), "JSON 反序列化应为 dict"
    print(f"[PASS] 附加场景-JSON序列化: 中文正常保留")


if __name__ == "__main__":
    print("=" * 60)
    print("中文编码专项测试")
    print("=" * 60)
    test_return_chinese()
    test_receive_chinese_param()
    test_error_message_chinese()
    test_json_serialization_chinese()
    print("=" * 60)
    print("全部测试通过")
    print("=" * 60)
