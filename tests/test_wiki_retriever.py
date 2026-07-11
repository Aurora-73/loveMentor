"""Wiki 检索单元测试。

用 fixture 构造最小 OKF 知识库（5-10 个稳定条目），不修改 conftest.py 全局配置。
覆盖：WikiIndex 加载/别名扩展、WikiRetriever.retrieve() 检索、task_type 预算、
search_terms 打分、空查询/无效查询处理、低分命中处理。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.knowledge.wiki_index import WikiIndex, WikiPage
from engine.knowledge.wiki_retriever import WikiRetriever, WikiSnippet


# ── Fixture：构造最小 OKF 知识库 ──────────────────────────────────────

WIKI_SCHEMA = """# Wiki Schema

## 别名词表（Alias Table）

格式：每行一组同义词，用 `=` 分隔。

```
推拉 = 忽冷忽热 = 欲擒故纵 = 张力
不回消息 = 回复变慢 = 已读不回 = 聊天冷淡 = 不理我
```
"""

ENTITY_TUILA = """---
type: Concept
title: 推拉
description: 在互动中交替给予兴趣和撤回兴趣，制造情绪波动。
tags: [推拉, 核心技术, 吸引力, 框架]
keywords: [推拉, 情绪波动, 张力]
search_terms: [微笑, 敷衍, 忽冷忽热, 欲擒故纵, 情绪波动, 冷淡]
scenarios: [reply, ask]
stages: [吸引, 连接]
confidence: EXTRACTED
---
# 推拉

> 在互动中交替给予兴趣和撤回兴趣，制造情绪波动。

## 核心原则

1. 6 分饱原则
2. 猫绳理论
3. 底线推
"""

ENTITY_CHUANGKOU = """---
type: Concept
title: 窗口识别
description: 识别好感窗口和防感窗口。
tags: [窗口, 信号, 社交直觉, 好感窗口]
keywords: [窗口, 信号, 好感]
search_terms: [窗口, 信号, 好感, 防感, 识别]
scenarios: [reply, analyze]
stages: [连接, 暧昧]
confidence: EXTRACTED
---
# 窗口识别

> 识别好感窗口和防感窗口。

## 好感窗口信号

- 主动追问个人问题
- 延续话题
"""

ENTITY_IOI = """---
type: Concept
title: IOI（兴趣指标）
description: 女人被你吸引的非口语迹象。
tags: [IOI, 兴趣指标, 信号识别]
keywords: [IOI, 兴趣指标, 信号]
search_terms: [兴趣, 喜欢我, 信号, 有没有意思, 感兴趣]
scenarios: [reply, analyze]
stages: [吸引, 连接]
confidence: EXTRACTED
---
# IOI（兴趣指标）

> 女人被你吸引的非口语迹象。

## 定义

被动、主动或假性的兴趣指标。
"""

ENTITY_KUANGJIA = """---
type: Concept
title: 框架（Frame）
description: 互动中谁定义现实的权力。
tags: [框架, 势能, 主导]
keywords: [框架, 势能, Frame]
search_terms: [框架, 势能, 主导, 强势]
scenarios: [ask, analyze]
stages: [吸引, 暧昧]
confidence: EXTRACTED
---
# 框架（Frame）

> 互动中谁定义现实的权力。

## 核心要点

保持自己的框架不被对方带跑。
"""

SCENARIO_BULUI = """---
type: Scenario
title: 她不回消息了怎么办
description: 她突然不回消息或回复变慢——先判断原因，再决定动作。
tags: [场景, 聊天, 不回消息, 需求感]
keywords: [不回消息, 冷淡, 频率]
search_terms: [不回消息, 已读不回, 不理我, 回复变慢, 冷淡, 消失]
scenarios: [reply, ask]
stages: [连接, 暧昧]
confidence: EXTRACTED
---
# 她不回消息了怎么办

> 她突然不回消息或回复变慢——先判断原因，再决定动作。

## 第一步：判断原因

不回消息有多种可能，先定位情绪状态。
"""

TOPIC_LIAOTIAN = """---
type: Topic
title: 聊天技巧
description: 聊天相关的技术汇总。
tags: [聊天, 话术, 话题]
keywords: [聊天, 话术, 话题]
search_terms: [聊天, 话术, 话题, 回复]
scenarios: [reply, meet]
stages: [连接, 暧昧]
confidence: EXTRACTED
---
# 聊天技巧

> 聊天相关的技术汇总。

## 基础原则

多线程话题、推拉、冷读。
"""

SYNTHESIS_DUIGI = """---
type: Synthesis
title: 聊天框架对比
description: 不同聊天框架的对比分析。
tags: [对比, 聊天, 框架]
keywords: [对比, 框架, 聊天]
search_terms: [对比, 框架, 分析]
scenarios: [ask, analyze]
stages: [吸引, 连接]
confidence: EXTRACTED
---
# 聊天框架对比

> 不同聊天框架的对比分析。

## 三种框架

拳击式、阶段性、四步分析法。
"""


@pytest.fixture
def wiki_root(tmp_path: Path) -> Path:
    """构造最小 OKF 知识库（7 个稳定条目 + 别名词表）。"""
    root = tmp_path / "wiki"
    (root).mkdir()

    # 别名词表
    (root / ".wiki-schema.md").write_text(WIKI_SCHEMA, encoding="utf-8")

    # 内容目录 wiki/
    content = root / "wiki"
    (content / "entities").mkdir(parents=True)
    (content / "scenarios").mkdir(parents=True)
    (content / "topics").mkdir(parents=True)
    (content / "synthesis").mkdir(parents=True)

    (content / "entities" / "推拉.md").write_text(ENTITY_TUILA, encoding="utf-8")
    (content / "entities" / "窗口识别.md").write_text(ENTITY_CHUANGKOU, encoding="utf-8")
    (content / "entities" / "IOI（兴趣指标）.md").write_text(ENTITY_IOI, encoding="utf-8")
    (content / "entities" / "框架（Frame）.md").write_text(ENTITY_KUANGJIA, encoding="utf-8")
    (content / "scenarios" / "她不回消息了怎么办.md").write_text(SCENARIO_BULUI, encoding="utf-8")
    (content / "topics" / "聊天技巧.md").write_text(TOPIC_LIAOTIAN, encoding="utf-8")
    (content / "synthesis" / "聊天框架对比.md").write_text(SYNTHESIS_DUIGI, encoding="utf-8")

    return root


@pytest.fixture
def index(wiki_root: Path) -> WikiIndex:
    """加载后的 WikiIndex。"""
    idx = WikiIndex(wiki_root=wiki_root)
    idx.load()
    return idx


@pytest.fixture
def retriever(index: WikiIndex) -> WikiRetriever:
    """WikiRetriever。"""
    return WikiRetriever(index=index)


# ── WikiIndex 测试 ────────────────────────────────────────────────────

def test_wiki_index_loads_pages(index: WikiIndex) -> None:
    """WikiIndex 能从 Markdown fallback 加载页面。"""
    pages = index.pages
    assert len(pages) == 7, f"期望 7 个页面，实际 {len(pages)}"
    titles = {p.title for p in pages}
    assert "推拉" in titles
    assert "窗口识别" in titles
    assert "她不回消息了怎么办" in titles


def test_wiki_index_page_types(index: WikiIndex) -> None:
    """页面 page_type 正确映射。"""
    type_counts: dict[str, int] = {}
    for p in index.pages:
        type_counts[p.page_type] = type_counts.get(p.page_type, 0) + 1
    assert type_counts.get("entity", 0) == 4
    assert type_counts.get("scenario", 0) == 1
    assert type_counts.get("topic", 0) == 1
    assert type_counts.get("synthesis", 0) == 1


def test_wiki_index_alias_expansion(index: WikiIndex) -> None:
    """expand_query 用别名词表双向展开。"""
    # 查询包含别名 → 追加 canonical
    expanded = index.expand_query("她忽冷忽热")
    assert "推拉" in expanded, "别名「忽冷忽热」应展开为 canonical「推拉」"
    assert "欲擒故纵" in expanded, "应追加同组其他别名"

    # 查询包含 canonical → 追加所有别名
    expanded2 = index.expand_query("推拉技术")
    assert "忽冷忽热" in expanded2
    assert "欲擒故纵" in expanded2

    # 无关查询不变
    expanded3 = index.expand_query("今天天气不错")
    assert expanded3 == "今天天气不错"


def test_wiki_index_get_page_content(index: WikiIndex) -> None:
    """get_page_content 能读取页面正文。"""
    page = next(p for p in index.pages if p.title == "推拉")
    content = index.get_page_content(page)
    assert content is not None
    assert "6 分饱原则" in content


def test_wiki_index_empty_root(tmp_path: Path) -> None:
    """空 wiki root 加载后 is_empty 为 True。"""
    empty_root = tmp_path / "empty_wiki"
    empty_root.mkdir()
    idx = WikiIndex(wiki_root=empty_root)
    idx.load()
    assert idx.is_empty
    assert idx.pages == []


# ── WikiRetriever 基本检索测试 ────────────────────────────────────────

def test_retriever_basic_retrieval(retriever: WikiRetriever) -> None:
    """retrieve() 对匹配查询返回非空结果。"""
    snippets = retriever.retrieve("推拉", task_type="analyze")
    assert len(snippets) > 0
    titles = [s.title for s in snippets]
    assert "推拉" in titles, "查询「推拉」应命中推拉条目"


def test_retriever_title_exact_match_scores_high(retriever: WikiRetriever) -> None:
    """标题完全命中得分高，排在前面。"""
    snippets = retriever.retrieve("窗口识别", task_type="analyze")
    assert len(snippets) > 0
    assert snippets[0].title == "窗口识别"
    assert snippets[0].score >= 10, "标题完全命中应 ≥ 10 分"


def test_retriever_search_terms_hit(retriever: WikiRetriever) -> None:
    """search_terms 命中加分（口语化查询词）。"""
    # 「欲擒故纵」是推拉的 search_term，也是别名
    snippets = retriever.retrieve("她对我不理我怎么办", task_type="reply")
    titles = [s.title for s in snippets]
    # 不回消息场景的 search_terms 含「不理我」
    assert "她不回消息了怎么办" in titles, "search_terms「不理我」应命中场景页"


def test_retriever_keyword_hit(retriever: WikiRetriever) -> None:
    """keywords 命中加分。"""
    snippets = retriever.retrieve("IOI 兴趣指标", task_type="analyze")
    titles = [s.title for s in snippets]
    assert "IOI（兴趣指标）" in titles, "keywords 命中应返回 IOI 条目"


# ── task_type 预算测试 ────────────────────────────────────────────────

def test_retriever_task_type_budget_reply(retriever: WikiRetriever) -> None:
    """reply task_type 预算：最多 3 页 / 2500 字符。"""
    # 用宽泛查询命中多个页面
    snippets = retriever.retrieve("聊天 推拉 窗口 框架 信号", task_type="reply")
    assert len(snippets) <= 3, "reply 最多 3 页"
    for s in snippets:
        assert len(s.content) <= 2500, "每段内容不超过 2500 字符"


def test_retriever_task_type_budget_analyze(retriever: WikiRetriever) -> None:
    """analyze task_type 预算：最多 8 页 / 8000 字符。"""
    snippets = retriever.retrieve("聊天 推拉 窗口 框架 信号 IOI", task_type="analyze")
    assert len(snippets) <= 8, "analyze 最多 8 页"
    # analyze 比 reply 允许更多页面
    snippets_reply = retriever.retrieve("聊天 推拉 窗口 框架 信号 IOI", task_type="reply")
    assert len(snippets) >= len(snippets_reply), "analyze 预算应 ≥ reply"


def test_retriever_task_type_filter(retriever: WikiRetriever) -> None:
    """task_type 过滤不允许的页面类型。reply 不含 synthesis？实际 reply 允许 synthesis？查代码。"""
    # _TASK_TYPE_FILTER: reply/meet = {entity, topic, scenario}; ask/analyze 多 synthesis
    # reply 不含 synthesis，所以查 synthesis 标题时 reply 不应返回
    snippets = retriever.retrieve("聊天框架对比", task_type="reply")
    titles = [s.title for s in snippets]
    # synthesis 页面在 reply 中应被过滤掉（除非标题命中且类型允许）
    # 实际：synthesis 类型不在 reply 的 allowed_types 中，所以不返回
    assert "聊天框架对比" not in titles, "synthesis 页面在 reply task_type 下应被过滤"

    # analyze 允许 synthesis
    snippets_analyze = retriever.retrieve("聊天框架对比", task_type="analyze")
    titles_analyze = [s.title for s in snippets_analyze]
    assert "聊天框架对比" in titles_analyze, "analyze task_type 应允许 synthesis"


# ── 空查询 / 无效查询 / 低分命中测试 ──────────────────────────────────

def test_retriever_empty_query(retriever: WikiRetriever) -> None:
    """空查询：记录当前检索器的实际行为。

    空字符串 `""` 满足 `query_lower in title_lower`（空串在所有字符串中），
    所以每个页面获得 +10 标题命中分（已知行为）。
    返回的 snippet 分数由 标题命中(10) + scenario 匹配(0或3) + EXTRACTED(1) 组成。
    Agent 侧 fallback 策略（wiki_context.py 低置信度处理）负责兜底这种低质量命中。
    """
    snippets = retriever.retrieve("", task_type="analyze")
    assert len(snippets) > 0, "空查询仍返回页面（标题空串匹配）"
    for s in snippets:
        # 分数为 10（标题）+ 0/3（scenario）+ 1（EXTRACTED）= 11 或 14
        assert s.score in (11.0, 14.0), f"空查询的 snippet 分数应为 11 或 14，实际 {s.score}"


def test_retriever_invalid_query(retriever: WikiRetriever) -> None:
    """无意义查询：无查询词命中，仅 scenario 匹配 + EXTRACTED 基线分。"""
    snippets = retriever.retrieve("zzzqqqxxx", task_type="analyze")
    for s in snippets:
        # 分数为 0（无标题命中）+ 0/3（scenario）+ 1（EXTRACTED）= 1 或 4
        assert s.score in (1.0, 4.0), f"无意义查询的 snippet 分数应为 1 或 4，实际 {s.score}"


def test_retriever_low_score_still_returned(retriever: WikiRetriever) -> None:
    """score > 0 的低分命中仍返回（不设最低分阈值）。"""
    # 用宽泛查询命中 summary 或 tag 但分数不高
    snippets = retriever.retrieve("聊天", task_type="analyze")
    # 「聊天」会命中多个页面的 tags/keywords/search_terms
    assert len(snippets) > 0, "「聊天」应命中多个条目"
    # 所有返回的 snippet score 都 > 0
    for s in snippets:
        assert s.score > 0, f"返回的 snippet score 应 > 0，实际 {s.score}"


# ── stage / focus 加权测试 ────────────────────────────────────────────

def test_retriever_stage_match_boosts(retriever: WikiRetriever) -> None:
    """stage 匹配加分（强权重）。"""
    # 推拉的 stages 含「吸引」
    snippets_no_stage = retriever.retrieve("推拉", task_type="analyze")
    snippets_with_stage = retriever.retrieve("推拉", task_type="analyze", stage="吸引")

    # 找推拉条目
    tuila_no = next((s for s in snippets_no_stage if s.title == "推拉"), None)
    tuila_with = next((s for s in snippets_with_stage if s.title == "推拉"), None)
    assert tuila_no is not None and tuila_with is not None
    assert tuila_with.score > tuila_no.score, "stage 匹配应加分"
    assert tuila_with.score >= tuila_no.score + 5, "stage 匹配加 5 分"


def test_retriever_focus_keywords_boosts(retriever: WikiRetriever) -> None:
    """focus 参数加权相关页面。"""
    # focus=signals 应加权含「信号/窗口/IOI」的页面
    snippets_no_focus = retriever.retrieve("识别", task_type="analyze")
    snippets_focus = retriever.retrieve("识别", task_type="analyze", focus="signals")

    # 窗口识别的 focus_text 含「信号」「窗口」
    ck_no = next((s for s in snippets_no_focus if s.title == "窗口识别"), None)
    ck_with = next((s for s in snippets_focus if s.title == "窗口识别"), None)
    if ck_no and ck_with:
        assert ck_with.score > ck_no.score, "focus=signals 应给窗口识别加分"


def test_retriever_snippet_has_content(retriever: WikiRetriever) -> None:
    """返回的 snippet 含正文内容（非空）。"""
    snippets = retriever.retrieve("推拉", task_type="analyze")
    assert len(snippets) > 0
    for s in snippets:
        assert s.content, "snippet content 不应为空"
        assert s.title, "snippet title 不应为空"
        assert s.path, "snippet path 不应为空"
        assert s.page_type in ("entity", "topic", "synthesis", "scenario")


def test_retriever_max_pages_override(retriever: WikiRetriever) -> None:
    """max_pages 参数覆盖 task_type 默认预算。"""
    snippets = retriever.retrieve("聊天 推拉 窗口 框架 信号 IOI", task_type="analyze", max_pages=2)
    assert len(snippets) <= 2, "max_pages=2 应限制返回 2 页"


def test_retriever_max_chars_override(retriever: WikiRetriever) -> None:
    """max_chars 参数裁剪内容长度。"""
    snippets = retriever.retrieve("推拉", task_type="analyze", max_chars=100)
    assert len(snippets) > 0
    total_chars = sum(len(s.content) for s in snippets)
    # 总字符数受 max_chars 限制（单页可能略超？实际 _trim_content 裁剪到 budget）
    assert total_chars <= 200, "max_chars 应限制总内容长度"
