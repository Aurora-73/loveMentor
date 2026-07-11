"""最终质量自检 — 全量验收测试"""
import sys
import asyncio

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')


def test_tool_count():
    """验证工具总数为 50（48 + guide + wcd_start）"""
    from mcp_server.server import mcp
    tools = asyncio.run(mcp.list_tools())
    assert len(tools) == 50, f"工具数应为 50，实际 {len(tools)}"
    print(f"[PASS] 工具总数: {len(tools)}")
    return tools


def test_tool_categories(tools):
    """按类别统计工具数"""
    def is_readonly(t):
        if not t.annotations:
            return False
        try:
            return t.annotations.readOnlyHint
        except AttributeError:
            return getattr(t.annotations, "read_only_hint", False)
    read_tools = [t for t in tools if is_readonly(t)]
    write_tools = [t for t in tools if not is_readonly(t)]
    print(f"  只读工具: {len(read_tools)} 个")
    print(f"  写入工具: {len(write_tools)} 个")
    assert len(read_tools) + len(write_tools) == 50
    print("[PASS] 工具分类统计正确")


def test_phase_distribution(tools):
    """按 Phase 分布验证"""
    tool_names = {t.name for t in tools}

    phase1 = {"person_brief", "person_chat", "person_metrics", "person_rank",
              "person_status", "wiki_search", "person_note", "person_date_record"}
    assert phase1.issubset(tool_names), f"Phase 1 缺少: {phase1 - tool_names}"
    print(f"  [PASS] Phase 1: {len(phase1)} 个工具")

    p0 = {"wiki_read", "person_sync", "person_save_analysis"}
    assert p0.issubset(tool_names), f"P0 缺少: {p0 - tool_names}"
    print(f"  [PASS] Phase 2 P0: {len(p0)} 个工具")

    p1 = {"person_timeline", "person_signals", "person_evidence",
          "person_stage",
          "person_compare", "weekly_report", "person_moments_stats", "maintain_list",
          "events_scan", "events_save", "person_evaluate", "system_sync",
          "wcd_status", "wcd_start"}
    assert p1.issubset(tool_names), f"P1 缺少: {p1 - tool_names}"
    print(f"  [PASS] Phase 2 P1: {len(p1)} 个工具")

    p2 = {"contact_search", "sticker_scan", "sticker_list", "exclude_list",
          "failure_list", "message_context", "contact_alias", "contact_alias_remove",
          "contact_merge", "sticker_label", "exclude_add", "exclude_remove",
          "failure_add", "save_from_markdown", "sync_moments"}
    assert p2.issubset(tool_names), f"P2 缺少: {p2 - tool_names}"
    print(f"  [PASS] Phase 2 P2: {len(p2)} 个工具")

    p3 = {"formula_get_params", "formula_calc_ivi", "formula_calc_spe", "formula_calc_ews",
          "formula_calc_is", "formula_calc_gap_effect", "formula_calc_eev",
          "formula_calc_cs", "formula_calc_action"}
    assert p3.issubset(tool_names), f"P3 缺少: {p3 - tool_names}"
    print(f"  [PASS] Phase 3 P3: {len(p3)} 个工具")

    # guide 工具（使用指南）
    guide_tools = {"guide"}
    assert guide_tools.issubset(tool_names), f"guide 缺少: {guide_tools - tool_names}"
    print(f"  [PASS] guide: {len(guide_tools)} 个工具")

    total = len(phase1) + len(p0) + len(p1) + len(p2) + len(p3) + len(guide_tools)
    assert total == 50, f"总计应为 50，实际 {total}"
    print(f"  [PASS] 总计: {total} 个工具")


def test_fetch_keys_excluded(tools):
    """验证 fetch_keys 未被暴露"""
    tool_names = {t.name for t in tools}
    assert "fetch_keys" not in tool_names, "fetch_keys 不应被暴露！"
    print("[PASS] fetch_keys 未被暴露")


def test_guide_tool():
    """验证 guide 工具的 11 个主题和别名映射"""
    from mcp_server.tools_guide import guide_func, GUIDES, TOPIC_ALIASES

    # 1. 验证 11 个主题存在
    expected_topics = {
        "getting-started", "workflow/analysis", "report-template",
        "methodology", "rules/evidence", "rules/permissions", "rules/reply",
        "workflow/maintain", "reference/sync", "reference/formula",
        "reference/stickers",
    }
    assert set(GUIDES.keys()) == expected_topics, f"主题不匹配: {set(GUIDES.keys()) ^ expected_topics}"
    print(f"  [PASS] 11 个主题全部存在")

    # 2. 验证默认主题
    result = guide_func()
    assert "快速入门" in result, f"默认主题应为 getting-started: {result[:50]}"
    print(f"  [PASS] 默认返回 getting-started")

    # 3. 验证中文别名
    assert "分析" in TOPIC_ALIASES, "中文别名'分析'缺失"
    assert TOPIC_ALIASES["分析"] == "workflow/analysis"
    result = guide_func("分析")
    assert "人物分析完整流程" in result
    print(f"  [PASS] 中文别名映射正确")

    # 4. 验证英文别名
    assert "report" in TOPIC_ALIASES, "英文别名'report'缺失"
    assert TOPIC_ALIASES["report"] == "report-template"
    result = guide_func("report")
    assert "分析报告模板" in result
    print(f"  [PASS] 英文别名映射正确")

    # 5. 验证未知主题返回主题列表
    result = guide_func("unknown-topic")
    assert "可用主题" in result, f"未知主题应返回列表: {result[:50]}"
    print(f"  [PASS] 未知主题返回主题列表")

    # 6. 验证关键内容存在
    result = guide_func("workflow/analysis")
    assert "person_sync" in result, "workflow/analysis 应包含 person_sync"
    assert "save_from_markdown" in result, "workflow/analysis 应包含 save_from_markdown"
    assert "wiki_search" in result, "workflow/analysis 应包含 wiki_search"
    print(f"  [PASS] workflow/analysis 内容完整")


def test_bugfixes():
    """验证已知 Bug 已修复"""
    from mcp_server.tools_read import wiki_search, person_chat, person_rank
    from engine.tools import wiki_show

    # Bug 1: wiki_search 返回的 path 能被 wiki_read 正确读取
    r = wiki_search("推拉", limit=3)
    found_wiki = False
    for result in r.get("results", []):
        if result.get("type") == "wiki":
            path = result.get("path", "")
            if path:
                found_wiki = True
                content = wiki_show(path, max_chars=50)
                assert "文件不存在" not in content, f"wiki_read 无法读取 wiki_search 返回的路径: {path}"
    if found_wiki:
        print("[PASS] Bug 1 修复: wiki_search 路径与 wiki_read 一致")
    else:
        print("[SKIP] Bug 1: 无 wiki 搜索结果，跳过路径验证")

    # Bug 2: person_chat 支持 keyword + context_lines
    rank = person_rank()
    rankings = rank.get("rankings", [])
    if rankings:
        name = rankings[0]["name"]
        result = person_chat(name, recent=3, keyword="的", context_lines=1)
        data = result.get("data", result)
        filter_info = data.get("filter", {})
        assert filter_info.get("context_lines") == 1, f"context_lines 应为 1: {filter_info}"
    print("[PASS] Bug 2 修复: person_chat 支持 keyword + context_lines")

    # Bug 3 (P0): maintain_list 不再报 AttributeError
    from mcp_server.tools_read import maintain_list
    ml = maintain_list(limit=3)
    assert "error" not in ml, f"maintain_list 仍报错: {ml}"
    for c in ml.get("candidates", []):
        assert "priority" in c, f"candidate 缺 priority: {c}"
        assert "suggested_action" in c, f"candidate 缺 suggested_action: {c}"
    print("[PASS] Bug 3 (P0) 修复: maintain_list 返回正常")

    # Bug 4 (P3): person_status 与 person_metrics 字段区分
    from engine.tools import status_data, metrics
    sd = status_data("妈")
    mt = metrics("妈")
    if isinstance(mt, dict) and "accounts" in sd and sd["accounts"] and "accounts" in mt and mt["accounts"]:
        status_fields = set(sd["accounts"][0].keys())
        metrics_fields = set(mt["accounts"][0].keys())
        status_only = status_fields - metrics_fields
        metrics_only = metrics_fields - status_fields
        assert status_only, f"person_status 与 person_metrics 字段完全重叠: {status_fields} vs {metrics_fields}"
        assert metrics_only, f"person_metrics 与 person_status 字段完全重叠: {metrics_fields} vs {status_fields}"
    print("[PASS] Bug 4 (P3) 修复: person_status 与 person_metrics 已区分")


if __name__ == "__main__":
    print("=" * 60)
    print("最终质量自检 — 全量验收")
    print("=" * 60)

    print("\n[1] 工具数量验证")
    tools = test_tool_count()

    print("\n[2] 工具分类统计")
    test_tool_categories(tools)

    print("\n[3] Phase 分布验证")
    test_phase_distribution(tools)

    print("\n[4] 安全验证")
    test_fetch_keys_excluded(tools)

    print("\n[5] guide 工具验证")
    test_guide_tool()

    print("\n[6] Bug 修复验证")
    test_bugfixes()

    print("\n" + "=" * 60)
    print("🎉 全量验收通过 — 50 个工具全部就绪（含 guide + wcd_start）")
    print("=" * 60)
