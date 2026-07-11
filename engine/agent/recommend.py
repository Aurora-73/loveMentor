"""Wiki/框架推荐 — 根据信号和数据推荐相关 Wiki 页面。"""
from __future__ import annotations

import sqlite3
from engine.config import Config
from engine.identity import IdentityPerson

# 分析框架 Wiki 页面
_FRAMEWORK_WIKI: dict[str, list[tuple[str, str]]] = {
    "always": [
        ("wiki/entities/IOI（兴趣指标）.md", "判断她对你有没有兴趣的核心框架"),
        ("wiki/entities/关系三要素.md", "逻辑联系+良好情绪+肢体升级——三者缺一不可"),
        ("wiki/entities/需求感控制.md", "投入比失衡时的止损框架"),
    ],
    "rejection": [
        ("wiki/scenarios/被发好人卡她说做朋友.md", "被拒后的行动方案和心态调整"),
        ("wiki/entities/供养者vs情人.md", "她把你归类为'好人'还是'情人'的判断框架"),
        ("wiki/scenarios/什么时候该止损.md", "五维度止损判断框架"),
    ],
    "confession": [
        ("wiki/scenarios/她主动找我怎么办.md", "她主动时如何回应——接受但不跪舔"),
        ("wiki/entities/Kino（进挪）.md", "肢体升级的时机和方法"),
    ],
    "invitation": [
        ("wiki/scenarios/从线上到第一次见面.md", "线上到线下的关键一步"),
        ("wiki/scenarios/第一次约会怎么安排.md", "约会设计和推进节奏"),
    ],
    "cold": [
        ("wiki/scenarios/她一直聊但不见面.md", "聊了很久但约不出来的判断和应对"),
        ("wiki/scenarios/什么时候该止损.md", "五维度止损判断框架"),
        ("wiki/entities/70%频率法则.md", "70%的人会冷淡——频率控制的核心法则"),
    ],
    "moments_strong_ioi": [
        ("wiki/entities/IOI（兴趣指标）.md", "朋友圈评论是明确的 IOI——她主动找话题互动"),
        ("wiki/entities/窗口识别.md", "朋友圈互动 vs 聊天态度矛盾时如何判断窗口"),
    ],
    "moments_weak_ioi": [
        ("wiki/entities/IOI（兴趣指标）.md", "点赞是弱 IOI——有关注但不强烈"),
    ],
}


def _build_framework_recommendations(signals: dict[str, list[str]], has_archive: bool) -> list[tuple[str, str]]:
    seen: set[str] = set()
    result: list[tuple[str, str]] = []
    for path, desc in _FRAMEWORK_WIKI["always"]:
        if path not in seen:
            result.append((path, desc))
            seen.add(path)
    for signal_type in ("rejection", "confession", "invitation", "moments_strong_ioi", "moments_weak_ioi"):
        if signal_type in signals:
            for path, desc in _FRAMEWORK_WIKI.get(signal_type, []):
                if path not in seen:
                    result.append((path, desc))
                    seen.add(path)
    if "rejection" not in signals and "confession" not in signals and "moments_strong_ioi" not in signals:
        for path, desc in _FRAMEWORK_WIKI.get("cold", []):
            if path not in seen:
                result.append((path, desc))
                seen.add(path)
    return result


def _recommend_wiki(conn: sqlite3.Connection, config: Config, person: IdentityPerson,
                    ctx, events: list, max_pages: int = 5) -> list[dict]:
    from engine.knowledge.wiki_index import WikiIndex
    from engine.knowledge.wiki_retriever import WikiRetriever
    query_parts = []
    if ctx.recent_messages:
        recent_msgs = ctx.recent_messages[-15:]
        recent_text = " ".join(m.get("content", "")[:80] for m in recent_msgs)
        query_parts.append(recent_text)
    if ctx.fact_archive:
        archive = ctx.fact_archive
        for section_name in ["关键信息", "当前状态", "关系时间线"]:
            idx = archive.find(f"## {section_name}")
            if idx != -1:
                end = archive.find("\n## ", idx + 3)
                section = archive[idx:end] if end != -1 else archive[idx:]
                query_parts.append(section[:300])
    if events:
        event_text = " ".join(e.event_type.value for e in events[:2])
        query_parts.append(event_text)
    query_text = " ".join(query_parts).strip()
    if not query_text:
        return []
    stage = ""
    if ctx.historical_analysis:
        stage = ctx.historical_analysis.get("stage", {}).get("stage", "")
    index = WikiIndex()
    if not index.load() or index.is_empty:
        return []
    retriever = WikiRetriever(index)
    snippets = retriever.retrieve(
        query_text=query_text, task_type="analyze",
        stage=stage, max_chars=5000, max_pages=max_pages,
    )
    return [
        {"type": "wiki", "title": s.title, "path": s.path, "page_type": s.page_type,
         "summary": s.summary, "score": s.score}
        for s in snippets
    ]
