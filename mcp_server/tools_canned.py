"""罐装素材搜索 MCP 工具。

设计原则（2026-07-24 用户明确要求）：
  - 代码不替 agent 做决策，agent 是 LLM 大脑，自行决定用什么
  - 工具只提供数据 + 模糊搜索能力
  - 不按 stage 过滤（stage 是 agent 的决策维度，不是工具的过滤维度）
  - stage 作为信息返回给 agent 参考，不用于过滤

素材文件：data/canned_materials.yaml
包含：破冰素材、熟悉期素材、暧昧期素材、自我提升参考
素材类型：brain_teasers / fun_facts / cold_jokes / movie_quotes / romantic_movie_quotes /
          body_language / eye_contact_training / voice_training / life_wisdom 等
"""

import os
import sys
import logging
import yaml
from typing import Optional

logger = logging.getLogger(__name__)

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

_DATA_DIR = os.path.join(_PROJECT_ROOT, "data")
CANNED_FILE = os.path.join(_DATA_DIR, "canned_materials.yaml")

# 分类元信息映射（补充 YAML 中缺失的统一字段，便于 agent 浏览）
# key = 子分类名（YAML 中的字段名），value = 元信息
_CATEGORY_META = {
    # stage_1_icebreakers
    "brain_teasers": {
        "display_name": "脑筋急转弯",
        "stage": "stage_1",
        "usage": "互动游戏素材，适合破冰/无聊时开场",
        "content_fields": ["question", "answer", "suitable_when"],
    },
    "fun_facts": {
        "display_name": "趣味冷知识",
        "stage": "stage_1",
        "usage": "展示有趣一面，适合聊到相关话题时自然带出",
        "content_fields": ["fact", "suitable_when", "can_relate_to_user"],
    },
    "cold_jokes": {
        "display_name": "冷笑话谜语",
        "stage": "stage_1",
        "usage": "轻松破冰，制造笑点",
        "content_fields": ["joke", "punchline"],
    },
    # stage_2_familiar
    "movie_quotes": {
        "display_name": "电影台词（熟悉期）",
        "stage": "stage_2",
        "usage": "展示文化品味，适合聊到理想/人生/奋斗话题",
        "content_fields": ["quote", "movie", "suitable_when"],
    },
    "self_deprecating_humor": {
        "display_name": "自嘲式幽默",
        "stage": "stage_2",
        "usage": "化解尴尬/调侃自己，保持轻松氛围",
        "content_fields": ["content", "suitable_when"],
    },
    # stage_3_flirtatious
    "romantic_movie_quotes": {
        "display_name": "浪漫电影台词",
        "stage": "stage_3",
        "usage": "暧昧期试探/表达心意，需结合语境谨慎使用",
        "content_fields": ["quote", "movie", "suitable_when"],
    },
    # self_improvement（非对话素材，用户自我学习/约会参考）
    "body_language": {
        "display_name": "身体语言解读",
        "stage": "self_improvement",
        "usage": "帮助读懂对方兴趣信号，约会参考（非对话素材）",
        "content_fields": ["signal", "meaning", "action"],
    },
    "eye_contact_training": {
        "display_name": "眼神训练方法",
        "stage": "self_improvement",
        "usage": "用户自我提升参考，非对话素材",
        "content_fields": ["method", "description"],
    },
    "voice_training": {
        "display_name": "声音训练方法",
        "stage": "self_improvement",
        "usage": "用户自我提升参考，非对话素材",
        "content_fields": ["method", "description"],
    },
    "life_wisdom": {
        "display_name": "人生感悟",
        "stage": "self_improvement",
        "usage": "用户自我提升参考，可作为长期关系经营的理念",
        "content_fields": ["wisdom", "relevant_to_user"],
    },
}


def _load_canned() -> dict:
    """加载罐装素材文件。"""
    if not os.path.exists(CANNED_FILE):
        return {}
    try:
        with open(CANNED_FILE, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        logger.warning(f"罐装素材加载失败: {e}")
        return {}


def _fuzzy_match(keywords: list[str], target_keywords: list[str], search_text: str = "") -> bool:
    """模糊关键词匹配：子串双向匹配 + 全文搜索。

    匹配规则：
    1. 关键词是目标关键词的子串（如 "电影" 匹配 "电影台词"）
    2. 目标关键词是关键词的子串（如 "电影台词" 匹配 "电影"）
    3. 关键词出现在搜索文本中（quote/suitable_when 等字段拼接的全文）
    """
    if not keywords:
        return True  # 无关键词限制 = 匹配所有

    search_text_lower = search_text.lower()

    for kw in keywords:
        kw_lower = kw.lower()
        # 规则 1+2：子串双向匹配
        for target in target_keywords:
            target_lower = target.lower()
            if kw_lower in target_lower or target_lower in kw_lower:
                return True
        # 规则 3：全文搜索
        if search_text_lower and kw_lower in search_text_lower:
            return True

    return False


def _build_search_text(item: dict, content_fields: list[str]) -> str:
    """将素材项的所有文本字段拼接成搜索文本。"""
    parts = []
    for field in content_fields:
        val = item.get(field, "")
        if isinstance(val, str):
            parts.append(val)
    return " ".join(parts)


def _iter_items(data: dict):
    """遍历所有素材项，yield (section_key, subsection_key, item, meta)。

    data 结构示例：
      stage_1_icebreakers:
        brain_teasers: [ {...}, {...} ]
        fun_facts: [ {...} ]
      stage_2_familiar: ...
      self_improvement: ...
    """
    for section_key, section_data in data.items():
        if section_key == "meta":
            continue
        if not isinstance(section_data, dict):
            continue
        for subsection_key, items in section_data.items():
            if not isinstance(items, list):
                continue
            meta = _CATEGORY_META.get(subsection_key, {
                "display_name": subsection_key,
                "stage": section_key,
                "usage": "",
                "content_fields": [],
            })
            for item in items:
                if not isinstance(item, dict):
                    continue
                yield section_key, subsection_key, item, meta


def search_canned_materials(
    keywords: Optional[list[str]] = None,
    category: Optional[str] = None,
    stage: Optional[str] = None,
    limit: int = 20,
) -> dict:
    """搜索罐装素材库，返回匹配素材的完整内容。

    设计原则：工具只提供数据，不替 agent 做决策。
    - 不按 stage 过滤（stage 是 agent 的决策维度）
    - stage 参数仅作为信息筛选提示，agent 可不传
    - category 精确匹配子分类名（如 brain_teasers / fun_facts）
    - 关键词模糊匹配所有文本字段

    Args:
        keywords: 关键词列表（模糊匹配，任一匹配即可）
                  支持子串匹配：搜 "电影" 可匹配 "电影台词"/"浪漫电影台词"
                  也搜索 quote/suitable_when/fact 等所有文本字段
        category: 子分类精确过滤，可选值：
                  brain_teasers(脑筋急转弯) / fun_facts(冷知识) / cold_jokes(冷笑话) /
                  movie_quotes(电影台词) / self_deprecating_humor(自嘲幽默) /
                  romantic_movie_quotes(浪漫台词) /
                  body_language(身体语言) / eye_contact_training(眼神训练) /
                  voice_training(声音训练) / life_wisdom(人生感悟)
        stage: 可选，仅作为信息筛选提示（非过滤决策）
               stage_1(初识) / stage_2(熟悉) / stage_3(暧昧) / self_improvement(自我提升)
               不传则返回所有阶段
        limit: 最多返回结果数（默认 20）

    Returns:
        {
            "total_found": int,
            "categories_summary": [...],  # 所有子分类概览（供 agent 浏览）
            "results": [
                {
                    "category": "brain_teasers",  # 子分类 key
                    "category_display": "脑筋急转弯",
                    "stage": "stage_1",  # 信息，供 agent 参考
                    "usage": "互动游戏素材，适合破冰/无聊时开场",
                    "content": {  # 原始素材字段
                        "question": "...",
                        "answer": "...",
                        "suitable_when": "..."
                    },
                },
                ...
            ],
            "search_criteria": {
                "keywords": [...],
                "category": "...",
                "stage": "..."
            }
        }
    """
    data = _load_canned()
    if not data:
        return {
            "total_found": 0,
            "categories_summary": [],
            "results": [],
            "error": "罐装素材文件不存在或为空",
            "file_path": CANNED_FILE,
        }

    # 构建分类概览（供 agent 浏览所有可用分类）
    categories_summary = []
    for section_key, section_data in data.items():
        if section_key == "meta" or not isinstance(section_data, dict):
            continue
        for subsection_key, items in section_data.items():
            if not isinstance(items, list):
                continue
            meta = _CATEGORY_META.get(subsection_key, {
                "display_name": subsection_key,
                "stage": section_key,
                "usage": "",
            })
            categories_summary.append({
                "category": subsection_key,
                "category_display": meta["display_name"],
                "stage": meta["stage"],
                "usage": meta["usage"],
                "item_count": len(items),
            })

    results = []

    for section_key, subsection_key, item, meta in _iter_items(data):
        # category 精确过滤
        if category and subsection_key != category:
            continue

        # stage 信息筛选（非决策，只是缩小范围提示）
        if stage and meta["stage"] != stage:
            continue

        # 构建搜索文本
        content_fields = meta["content_fields"]
        search_text = _build_search_text(item, content_fields)

        # 关键词模糊匹配
        # target_keywords 用 category_display + subsection_key 作为目标关键词
        target_keywords = [meta["display_name"], subsection_key]
        if not _fuzzy_match(keywords or [], target_keywords, search_text):
            continue

        results.append({
            "category": subsection_key,
            "category_display": meta["display_name"],
            "stage": meta["stage"],  # 信息，供 agent 参考
            "usage": meta["usage"],
            "content": item,  # 原始素材字段
        })

        if len(results) >= limit:
            break

    results = results[:limit]

    return {
        "total_found": len(results),
        "categories_summary": categories_summary,
        "results": results,
        "search_criteria": {
            "keywords": keywords or [],
            "category": category,
            "stage": stage,
        },
    }
