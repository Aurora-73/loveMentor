"""冒烟测试 — 验证 8 个工具都能正常调用并返回正确格式。

使用数据库中的真实联系人进行测试。
"""

import sys
import json

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')


def _unwrap(result):
    """如果返回是 ToolEnvelope 格式 ({status, data, meta})，解包出 data。"""
    if isinstance(result, dict) and result.get("status") == "ok" and "data" in result:
        return result["data"]
    return result


def _check(result, label, expected_keys=None, expect_error=False):
    """通用检查器。"""
    assert isinstance(result, dict), f"[{label}] 返回应为 dict，实际: {type(result)}"
    if expect_error:
        assert "error" in result, f"[{label}] 期望 error 但未包含: {list(result.keys())}"
        assert "message" in result, f"[{label}] error 返回应含 message"
        print(f"  [PASS] {label}: 正确返回错误 {result['error']}")
    else:
        assert "error" not in result, f"[{label}] 不期望 error 但返回: {result.get('error')}: {result.get('message', '')}"
        if expected_keys:
            unwrapped = _unwrap(result)
            for k in expected_keys:
                assert k in unwrapped, f"[{label}] 缺少字段 '{k}': {list(unwrapped.keys())}"
        print(f"  [PASS] {label}: 返回字段 {list(result.keys())}")


def test_all_tools():
    """测试全部 8 个工具。"""
    from mcp_server.tools_read import (
        person_brief, person_chat, person_metrics,
        person_rank, person_status, wiki_search,
    )
    from mcp_server.tools_write import person_note, person_date_record

    print("=" * 60)
    print("冒烟测试 — 8 个工具")
    print("=" * 60)

    # ── 1. person_rank (无参数，先获取可用联系人) ──
    print("\n[1/8] person_rank()")
    rank_result = person_rank()
    _check(rank_result, "person_rank", expected_keys=["week", "rankings"])
    rankings = rank_result.get("rankings", [])
    test_name = rankings[0]["name"] if rankings else None
    print(f"        排名第1: {test_name} (共 {len(rankings)} 人)")

    # ── 2. person_brief ──
    print("\n[2/8] person_brief(name)")
    if test_name:
        result = person_brief(test_name)
        _check(result, "person_brief", expected_keys=["identity"])
    else:
        result = person_brief("不存在的人")
        _check(result, "person_brief", expect_error=True)

    # ── 3. person_chat ──
    print("\n[3/8] person_chat(name, recent=5)")
    if test_name:
        result = person_chat(test_name, recent=5)
        _check(result, "person_chat", expected_keys=["messages"])
        unwrapped = _unwrap(result)
        msgs = unwrapped.get("messages", [])
        print(f"        返回 {len(msgs)} 条消息")
        assert len(msgs) <= 5, f"recent=5 但返回 {len(msgs)} 条"
    else:
        result = person_chat("不存在的人", recent=5)
        _check(result, "person_chat", expect_error=True)

    # ── 4. person_metrics ──
    print("\n[4/8] person_metrics(name)")
    if test_name:
        result = person_metrics(test_name)
        _check(result, "person_metrics", expected_keys=["person_id", "accounts"])
    else:
        result = person_metrics("不存在的人")
        _check(result, "person_metrics", expect_error=True)

    # ── 5. person_status ──
    print("\n[5/8] person_status(name)")
    if test_name:
        result = person_status(test_name)
        _check(result, "person_status", expected_keys=["person_id", "accounts"])
    else:
        result = person_status("不存在的人")
        _check(result, "person_status", expect_error=True)

    # ── 6. wiki_search ──
    print("\n[6/8] wiki_search(query, limit=3)")
    result = wiki_search("推拉", limit=3)
    _check(result, "wiki_search", expected_keys=["query", "results"])
    results_list = result.get("results", [])
    print(f"        返回 {len(results_list)} 条结果（limit=3）")
    assert len(results_list) <= 3, f"limit=3 但返回 {len(results_list)} 条"

    # ── 7. wiki_search limit 参数验证 ──
    print("\n[7/8] wiki_search limit 参数验证 (limit=1)")
    result1 = wiki_search("聊天", limit=1)
    _check(result1, "wiki_search(limit=1)", expected_keys=["results"])
    results1 = result1.get("results", [])
    print(f"        返回 {len(results1)} 条结果（limit=1）")
    assert len(results1) <= 1, f"limit=1 但返回 {len(results1)} 条"

    # ── 8. person_note (写入工具) ──
    print("\n[8/8] person_note(name, content) — 写入测试")
    if test_name:
        result = person_note(test_name, "MCP冒烟测试备注")
        _check(result, "person_note", expected_keys=["success"])
        assert result["success"] is True, f"写入应成功: {result}"
        print(f"        写入成功: {result.get('message', '')[:60]}")
    else:
        result = person_note("不存在的人", "测试")
        _check(result, "person_note", expect_error=True)

    # ── 附加: person_date_record ──
    print("\n[附加] person_date_record(name, ...) — 写入测试")
    if test_name:
        result = person_date_record(test_name, "2026-07-01", "测试地点", 3)
        _check(result, "person_date_record", expected_keys=["success"])
        assert result["success"] is True, f"写入应成功: {result}"
        print(f"        写入成功: {result.get('message', '')[:60]}")
    else:
        result = person_date_record("不存在的人", "2026-07-01")
        _check(result, "person_date_record", expect_error=True)

    # ── 附加: 错误处理 ──
    print("\n[附加] 错误处理 — 不存在的联系人")
    result = person_brief("绝对不存在的人名XYZ123")
    _check(result, "error_handling", expect_error=True)
    assert result["error"] == "PERSON_NOT_FOUND", f"错误码应为 PERSON_NOT_FOUND: {result['error']}"

    print("\n" + "=" * 60)
    print("全部冒烟测试通过")
    print("=" * 60)


if __name__ == "__main__":
    test_all_tools()
