"""Bug 修复验证测试"""
import sys
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

def test_wiki_path():
    """验证 wiki_search 返回的 path 能被 wiki_read 正确读取。"""
    from mcp_server.tools_read import wiki_search
    from engine.tools import wiki_show
    r = wiki_search("推拉", limit=3)
    results = r.get("results", [])
    wiki_results = [x for x in results if x.get("type") == "wiki"]
    if wiki_results:
        for x in wiki_results:
            path = x.get("path", "")
            content = wiki_show(path, max_chars=50)
            assert "文件不存在" not in content, f"wiki_read 无法读取 wiki_search 返回的路径: {path}"
            print(f"  [PASS] wiki path 可读: {path}")
    else:
        print("  [SKIP] 无 wiki 搜索结果")

def test_context_lines():
    """验证 person_chat 支持 keyword + context_lines 参数"""
    from mcp_server.tools_read import person_chat, person_rank
    rank = person_rank()
    rankings = rank.get("rankings", [])
    if rankings:
        name = rankings[0]["name"]
        result = person_chat(name, recent=5, keyword="的", context_lines=2)
        assert isinstance(result, dict), f"返回应为 dict: {type(result)}"
        data = result.get("data", result)
        filter_info = data.get("filter", {})
        assert filter_info.get("context_lines") == 2, f"context_lines 应为 2: {filter_info}"
        print(f"  [PASS] context_lines=2 已正确传递，filter: {filter_info}")
    else:
        print("  [SKIP] 无联系人数据")

if __name__ == "__main__":
    print("=" * 60)
    print("Bug 修复验证")
    print("=" * 60)
    test_wiki_path()
    test_context_lines()
    print("=" * 60)
    print("验证完成")
    print("=" * 60)
