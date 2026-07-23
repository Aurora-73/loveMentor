"""用户图片搜索 MCP 工具。

设计原则（2026-07-24 用户明确要求）：
  - 代码不替 agent 做决策，agent 是 LLM 大脑，自行决定用什么
  - 工具只提供数据 + 模糊搜索能力
  - 不按 stage 过滤（stage 是 agent 的决策维度，不是工具的过滤维度）
  - suitable_stages 作为信息返回给 agent 参考，不用于过滤
  - 隐私级别是安全控制（防止误发隐私图片），不是决策

Agent 看不到图片内容，通过本工具搜索图片索引，返回匹配图片的描述和绝对路径。
Agent 拿到描述后自行决定用哪张，拿到绝对路径后通过 wechat_send_image 发送。

索引文件：data/user_pictures_index.yaml
图片目录：data/user_pictures/
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
INDEX_FILE = os.path.join(_DATA_DIR, "user_pictures_index.yaml")
PICTURES_DIR = os.path.join(_DATA_DIR, "user_pictures")


def _load_index() -> dict:
    """加载图片索引文件。"""
    if not os.path.exists(INDEX_FILE):
        return {}
    try:
        with open(INDEX_FILE, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        logger.warning(f"图片索引加载失败: {e}")
        return {}


def _fuzzy_match(keywords: list[str], target_keywords: list[str], search_text: str = "") -> bool:
    """模糊关键词匹配：子串双向匹配 + 全文搜索。

    匹配规则：
    1. 关键词是目标关键词的子串（如 "猫" 匹配 "三花猫"、"猫咖"）
    2. 目标关键词是关键词的子串（如 "小猫" 匹配 "猫"）
    3. 关键词出现在搜索文本中（description/suitable_when 等字段）
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


def _match_privacy(max_privacy_level: str, file_privacy: str) -> bool:
    """检查隐私级别是否在允许范围内（安全控制，非决策）。

    隐私级别：safe < internal < private
    max_privacy_level=safe → 只返回 safe
    max_privacy_level=internal → 返回 safe + internal
    max_privacy_level=private → 返回所有
    """
    levels = {"safe": 0, "internal": 1, "private": 2}
    max_level = levels.get(max_privacy_level, 0)
    file_level = levels.get(file_privacy, 0)
    return file_level <= max_level


def _build_absolute_path(relative_path: str) -> str:
    """将相对路径转为绝对路径（规范化分隔符）。"""
    normalized_relative = relative_path.replace("/", os.sep)
    return os.path.join(PICTURES_DIR, normalized_relative)


def _filter_existing_files(files: list[dict]) -> list[dict]:
    """过滤掉不存在的文件（如 .trashed 或已删除的文件）。"""
    result = []
    for f in files:
        path = f.get("path", "")
        if not path:
            continue
        abs_path = _build_absolute_path(path)
        if os.path.exists(abs_path):
            result.append(f)
    return result


def _collect_files(category_data: dict) -> list[dict]:
    """收集分类下的所有文件（兼容 files 和 representative_files 字段）。"""
    files = category_data.get("files", [])
    if not files:
        files = category_data.get("representative_files", [])
    return _filter_existing_files(files)


def search_user_pictures(
    keywords: Optional[list[str]] = None,
    category: Optional[str] = None,
    max_privacy_level: str = "safe",
    limit: int = 20,
) -> dict:
    """搜索用户图片库，返回匹配图片的描述和绝对路径。

    设计原则：工具只提供数据，不替 agent 做决策。
    - 不按 stage 过滤（agent 自行判断哪些图片适合当前阶段）
    - suitable_stages 作为信息返回，供 agent 参考
    - 隐私级别是安全控制，防止误发隐私图片

    Args:
        keywords: 关键词列表（模糊匹配，任一匹配即可）
                  支持子串匹配：搜 "猫" 可匹配 "三花猫"/"猫咖"/"流浪猫"
                  也搜索 description/suitable_when 等文本字段
        category: 分类精确过滤，如 "猫" / "旅行" / "游戏" / "美食" / "户外活动"
                  不传则返回所有分类
        max_privacy_level: 最大隐私级别（安全控制），safe/internal/private（默认 safe）
                          safe=只返回可随时发的 / internal=+特定话题 / private=+谨慎发
        limit: 最多返回结果数（默认 20，让 agent 看到更多选项）

    Returns:
        {
            "total_found": int,
            "categories_summary": [...],  # 所有分类概览（供 agent 浏览）
            "results": [
                {
                    "absolute_path": "e:\\Code\\loveMentor\\data\\user_pictures\\<category-a>\\1000144894.jpg",
                    "relative_path": "<category-a>/1000144894.jpg",
                    "category": "猫",
                    "subcategory": "顺拐（三花猫）",
                    "description": "...",  # 图片描述（可能为空，需用户补充）
                    "category_description": "...",  # 分类描述
                    "suitable_stages": ["stage_1", "stage_2", ...],  # 供 agent 参考，不用于过滤
                    "keywords": ["猫", "三花猫", ...],
                    "privacy_level": "safe",
                    "suitable_when": "聊到猫/宠物/流浪猫/校园生活时",
                    "can_relate_to_user": "用户真实经历，展示爱心和责任感"
                },
                ...
            ],
            "search_criteria": {
                "keywords": [...],
                "category": "...",
                "max_privacy_level": "..."
            }
        }
    """
    index = _load_index()
    if not index:
        return {
            "total_found": 0,
            "categories_summary": [],
            "results": [],
            "error": "图片索引文件不存在或为空",
            "index_path": INDEX_FILE,
        }

    # 构建分类概览（供 agent 浏览所有可用分类）
    categories_summary = []
    for category_key, category_data in index.items():
        if category_key == "meta":
            continue
        if not isinstance(category_data, dict):
            continue
        files_count = len(_collect_files(category_data))
        if files_count > 0:
            categories_summary.append({
                "category": category_data.get("category", ""),
                "subcategory": category_data.get("subcategory", ""),
                "description": category_data.get("description", ""),
                "file_count": files_count,
                "privacy_level": category_data.get("privacy_level", "safe"),
                "suitable_when": category_data.get("suitable_when", ""),
                "keywords": category_data.get("keywords", []),
            })

    results = []

    # 遍历索引中的每个分类
    for category_key, category_data in index.items():
        if category_key == "meta":
            continue
        if not isinstance(category_data, dict):
            continue

        # 分类精确过滤
        if category and category_data.get("category", "") != category:
            continue

        # 隐私安全控制（非决策，是安全防护）
        file_privacy = category_data.get("privacy_level", "safe")
        if not _match_privacy(max_privacy_level, file_privacy):
            continue

        # 构建搜索文本（用于模糊匹配）
        category_desc = category_data.get("description", "")
        suitable_when = category_data.get("suitable_when", "")
        can_relate = category_data.get("can_relate_to_user", "")
        search_text = f"{category_desc} {suitable_when} {can_relate}"

        # 关键词模糊匹配
        target_keywords = category_data.get("keywords", [])
        if not _fuzzy_match(keywords or [], target_keywords, search_text):
            continue

        # 收集该分类下的文件
        files = _collect_files(category_data)

        for f in files:
            abs_path = _build_absolute_path(f["path"])
            file_desc = f.get("description", "")
            results.append({
                "absolute_path": abs_path,
                "relative_path": f["path"],
                "category": category_data.get("category", ""),
                "subcategory": category_data.get("subcategory", ""),
                "description": file_desc or category_desc,  # 优先用文件描述，无则用分类描述
                "category_description": category_desc,
                "suitable_stages": category_data.get("suitable_stages", []),  # 信息，供 agent 参考
                "keywords": target_keywords,
                "privacy_level": file_privacy,
                "suitable_when": suitable_when,
                "can_relate_to_user": can_relate,
            })

        # 限制总结果数
        if len(results) >= limit:
            break

    # 截断到 limit
    results = results[:limit]

    return {
        "total_found": len(results),
        "categories_summary": categories_summary,
        "results": results,
        "search_criteria": {
            "keywords": keywords or [],
            "category": category,
            "max_privacy_level": max_privacy_level,
        },
    }
