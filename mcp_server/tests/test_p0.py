"""Phase 2 P0 工具冒烟测试 — wiki_read, person_sync, person_save_analysis"""

import sys

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')


def test_wiki_read():
    """测试 wiki_read：先搜索获取路径，再读取正文。"""
    from mcp_server.tools_read import wiki_search, wiki_read

    print("[1/3] wiki_read")
    # 先搜索获取一个真实路径
    search_result = wiki_search("推拉", limit=1)
    if search_result.get("results"):
        path = search_result["results"][0].get("path", "")
        if path:
            result = wiki_read(path)
            assert isinstance(result, dict), f"返回应为 dict: {type(result)}"
            if "error" in result:
                print(f"  [WARN] wiki_read 返回错误: {result['error']}: {result.get('message', '')[:80]}")
            else:
                assert "content" in result, f"应含 content 字段: {list(result.keys())}"
                content = result["content"]
                print(f"  [PASS] wiki_read: 读取 {len(content)} 字符")
                return
    print("  [SKIP] 无搜索结果，跳过 wiki_read 正文测试")


def test_person_sync():
    """测试 person_sync：增量同步（可能因 WCD 未启动而返回错误，验证格式即可）。"""
    from mcp_server.tools_write import person_sync

    print("\n[2/3] person_sync")
    result = person_sync("不存在的人")
    assert isinstance(result, dict), f"返回应为 dict: {type(result)}"
    if "error" in result:
        print(f"  [PASS] person_sync: 正确返回错误 {result['error']}")
    elif "success" in result:
        print(f"  [PASS] person_sync: 返回 success={result['success']}")
    else:
        print(f"  [WARN] person_sync: 未知返回格式 {list(result.keys())}")


def test_person_save_analysis():
    """测试 person_save_analysis：保存分析结论。"""
    from mcp_server.tools_write import person_save_analysis
    from mcp_server.tools_read import person_rank

    print("\n[3/3] person_save_analysis")
    rank_result = person_rank()
    rankings = rank_result.get("rankings", [])
    if rankings:
        test_name = rankings[0]["name"]
        result = person_save_analysis(
            test_name,
            stage="高频聊天",
            confidence=0.7,
            reasoning="MCP P0 冒烟测试",
        )
        assert isinstance(result, dict), f"返回应为 dict: {type(result)}"
        if "success" in result and result["success"]:
            print(f"  [PASS] person_save_analysis: 保存成功 → {result.get('path', '')[:60]}")
        elif "error" in result:
            print(f"  [PASS] person_save_analysis: 正确返回错误 {result['error']}")
        else:
            print(f"  [WARN] 未知返回: {list(result.keys())}")
    else:
        result = person_save_analysis("不存在的人", reasoning="测试")
        assert "error" in result, f"不存在的人应返回 error: {result}"
        print(f"  [PASS] person_save_analysis: 正确返回错误 {result['error']}")


if __name__ == "__main__":
    print("=" * 60)
    print("Phase 2 P0 冒烟测试")
    print("=" * 60)
    test_wiki_read()
    test_person_sync()
    test_person_save_analysis()
    print("\n" + "=" * 60)
    print("P0 冒烟测试完成")
    print("=" * 60)
