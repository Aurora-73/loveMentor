"""用户图片搜索 MCP 工具。

设计原则（2026-07-24 用户明确要求）：
  - 代码不替 agent 做决策，agent 是 LLM 大脑，自行决定用什么
  - 工具只提供数据 + 模糊搜索能力
  - 不按 stage 过滤（stage 是 agent 的决策维度，不是工具的过滤维度）
  - 不设隐私级别，如某张图片需谨慎使用，在 README 描述中标注

数据来源：
  - data/user_pictures/README.md — 主目录说明（分类列表 + 独立文件）
  - data/user_pictures/{子文件夹}/README.md — 子文件夹详细描述
  - 扫描子文件夹获取实际图片文件列表

Agent 看不到图片内容，通过本工具搜索 README 描述，返回匹配图片的绝对路径。
Agent 拿到描述后自行决定用哪张，拿到绝对路径后通过 wechat_send_image 发送。
"""

import os
import re
import sys
import logging
from typing import Optional

logger = logging.getLogger(__name__)

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

PICTURES_DIR = os.path.join(_PROJECT_ROOT, "data", "user_pictures")
MAIN_README = os.path.join(PICTURES_DIR, "README.md")

# 支持的图片/视频扩展名
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".gif"}
_VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".flv", ".wmv", ".m4v", ".3gp"}
# 忽略的文件
_IGNORE_EXTS = {".trashed", ".txt", ".md", ".py"}


def _parse_main_readme() -> tuple[list[dict], list[dict]]:
    """解析主 README.md，返回 (子文件夹分类列表, 独立文件列表)。

    子文件夹分类: [{"name": "<category-a>", "description": "<category description>"}]
    独立文件: [{"name": "体检-身高体重.jpg", "description": "体检报告..."}]
    """
    if not os.path.exists(MAIN_README):
        return [], []

    try:
        with open(MAIN_README, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        logger.warning(f"主 README 读取失败: {e}")
        return [], []

    categories = []
    standalone_files = []

    # 解析"目录结构"表格
    in_dir_section = False
    in_file_section = False

    for line in content.splitlines():
        line = line.strip()

        if "## 目录结构" in line:
            in_dir_section = True
            in_file_section = False
            continue
        if "## 独立文件" in line:
            in_file_section = True
            in_dir_section = False
            continue
        if line.startswith("## ") and "目录结构" not in line and "独立文件" not in line:
            in_dir_section = False
            in_file_section = False
            continue

        # 解析表格行 | 目录/文件 | 描述 |
        if (in_dir_section or in_file_section) and line.startswith("|") and not line.startswith("|--") and not line.startswith("|-"):
            parts = [p.strip() for p in line.split("|")]
            # parts[0] 是空（| 前缀），parts[-1] 是空（| 后缀）
            parts = [p for p in parts if p]
            if len(parts) >= 2 and parts[0] not in ("目录", "文件"):
                name = parts[0].rstrip("/")
                description = parts[1]
                if in_dir_section:
                    categories.append({"name": name, "description": description})
                elif in_file_section:
                    standalone_files.append({"name": name, "description": description})

    return categories, standalone_files


def _parse_subfolder_readme(subfolder_path: str) -> dict:
    """解析子文件夹 README.md，返回详细描述信息。

    返回: {
        "description": "...",
        "keywords": [...],
        "suitable_when": "...",
        "usage_tips": "...",
        "file_descriptions": {"文件名": "描述", ...},  # 来自"## 单文件描述"section
    }
    """
    readme_path = os.path.join(subfolder_path, "README.md")
    result = {
        "description": "",
        "keywords": [],
        "suitable_when": "",
        "usage_tips": "",
        "file_descriptions": {},
    }

    if not os.path.exists(readme_path):
        return result

    try:
        with open(readme_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        logger.warning(f"子文件夹 README 读取失败 {readme_path}: {e}")
        return result

    # 按 section 解析
    current_section = None
    section_content = []

    for line in content.splitlines():
        # 检测 section 标题
        section_match = re.match(r"^##\s+(.+)", line)
        if section_match:
            # 保存前一个 section
            if current_section:
                if current_section == "file_descriptions":
                    # 单文件描述 section 特殊处理：解析 - `file`: desc 格式
                    result["file_descriptions"] = _parse_file_descriptions(section_content)
                else:
                    result[current_section] = "\n".join(section_content).strip()

            current_section_raw = section_match.group(1).strip()
            # 映射 section 名到字段
            if "单文件描述" in current_section_raw:
                current_section = "file_descriptions"
            elif "描述" in current_section_raw:
                current_section = "description"
            elif "适用场景" in current_section_raw:
                current_section = "suitable_when"
            elif "关键词" in current_section_raw:
                current_section = "keywords"
            elif "使用建议" in current_section_raw:
                current_section = "usage_tips"
            else:
                current_section = None
            section_content = []
        elif current_section:
            section_content.append(line)

    # 保存最后一个 section
    if current_section:
        if current_section == "file_descriptions":
            result["file_descriptions"] = _parse_file_descriptions(section_content)
        else:
            result[current_section] = "\n".join(section_content).strip()

    # keywords 从逗号/顿号分隔的文本转为列表
    if isinstance(result["keywords"], str) and result["keywords"]:
        # 按顿号、逗号、空格分隔
        kws = re.split(r"[、,\s]+", result["keywords"])
        result["keywords"] = [kw.strip() for kw in kws if kw.strip()]
    else:
        result["keywords"] = []

    return result


def _parse_file_descriptions(lines: list[str]) -> dict[str, str]:
    """解析"## 单文件描述"section 的内容，返回 {文件名: 描述} 映射。

    支持格式：
        - `文件名.jpg`: 描述文本
        - `文件名.jpg`: （空描述，待补充）
    """
    result = {}
    for line in lines:
        # 匹配 - `文件名`: 描述
        m = re.match(r"^-\s+`([^`]+)`\s*:\s*(.*)$", line.strip())
        if m:
            filename = m.group(1).strip()
            desc = m.group(2).strip()
            if filename:
                result[filename] = desc
    return result


def _scan_directory(subfolder_path: str) -> list[dict]:
    """扫描子文件夹，返回图片/视频文件列表。"""
    files = []
    if not os.path.isdir(subfolder_path):
        return files

    try:
        for name in sorted(os.listdir(subfolder_path)):
            if name.startswith(".") or name == "README.md":
                continue
            ext = os.path.splitext(name)[1].lower()
            if ext in _IGNORE_EXTS:
                continue
            file_type = "image" if ext in _IMAGE_EXTS else ("video" if ext in _VIDEO_EXTS else None)
            if file_type is None:
                continue
            files.append({
                "name": name,
                "type": file_type,
            })
    except Exception as e:
        logger.warning(f"目录扫描失败 {subfolder_path}: {e}")

    return files


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


def search_user_pictures(
    keywords: Optional[list[str]] = None,
    category: Optional[str] = None,
    limit: int = 20,
) -> dict:
    """搜索用户图片库，返回匹配图片的描述和绝对路径。

    设计原则：工具只提供数据，不替 agent 做决策。
    - 不按 stage 过滤（agent 自行判断哪些图片适合当前阶段）
    - 不设隐私级别过滤，agent 读取描述中的标注自行判断

    数据来源：data/user_pictures/README.md + 子文件夹 README.md + 目录扫描

    Args:
        keywords: 关键词列表（模糊匹配，任一匹配即可）
                  支持子串匹配：搜 "猫" 可匹配 "三花猫"/"猫咖"/"流浪猫"
                  也搜索 description/suitable_when 等文本字段
        category: 分类精确过滤（子文件夹名，如 "<category-a>"/"<category-b>"/"<category-c>"）
                  不传则返回所有分类
        limit: 最多返回结果数（默认 20，让 agent 看到更多选项）

    Returns:
        {
            "total_found": int,
            "categories_summary": [...],  # 所有分类概览（供 agent 浏览）
            "results": [
                {
                    "absolute_path": "e:\\Code\\loveMentor\\data\\user_pictures\\<category-a>\\1000144894.jpg",
                    "relative_path": "<category-a>/1000144894.jpg",
                    "category": "<category-a>",
                    "description": "...",  # 文件夹级别的描述
                    "file_description": "...",  # 该文件的具体描述（来自"## 单文件描述"section，可能为空）
                    "keywords": ["猫", "三花猫", ...],
                    "suitable_when": "聊到猫/宠物/流浪猫/校园生活时",
                    "usage_tips": "...",  # 使用建议
                    "file_type": "image" / "video",
                },
                ...
            ],
            "search_criteria": {
                "keywords": [...],
                "category": "..."
            }
        }

    单文件描述机制：
        - 子文件夹 README.md 中的"## 单文件描述"section 列出每个文件的具体描述
        - 用户手动填写每个文件的描述（用途/场景/特点）
        - 工具解析该 section，把描述合并到对应文件的结果中
        - 搜索时也会匹配单文件描述中的关键词
        - 留空的文件描述返回空字符串，agent 使用文件夹级别的通用描述
    """
    # 1. 解析主 README 获取分类列表
    categories, standalone_files = _parse_main_readme()

    if not categories and not standalone_files:
        return {
            "total_found": 0,
            "categories_summary": [],
            "results": [],
            "error": "主 README.md 不存在或为空",
            "readme_path": MAIN_README,
        }

    # 2. 对每个分类，解析子文件夹 README + 扫描目录
    enriched_categories = []
    for cat in categories:
        cat_name = cat["name"]
        cat_path = os.path.join(PICTURES_DIR, cat_name)

        # 解析子文件夹 README
        readme_data = _parse_subfolder_readme(cat_path)

        # 扫描目录获取实际文件
        actual_files = _scan_directory(cat_path)

        # 合并描述：优先用子文件夹 README 的描述，fallback 到主 README 的描述
        description = readme_data.get("description", "") or cat["description"]

        # 单文件描述映射
        file_descs = readme_data.get("file_descriptions", {})

        # 把单文件描述合并到每个文件对象中
        for f in actual_files:
            f["file_description"] = file_descs.get(f["name"], "")

        enriched_cat = {
            "name": cat_name,
            "description": description,
            "keywords": readme_data.get("keywords", []),
            "suitable_when": readme_data.get("suitable_when", ""),
            "usage_tips": readme_data.get("usage_tips", ""),
            "file_descriptions": file_descs,  # 保留完整映射供 agent 参考
            "files": actual_files,
            "file_count": len(actual_files),
        }
        enriched_categories.append(enriched_cat)

    # 3. 处理独立文件（不在子文件夹中的）
    standalone_enriched = []
    for sf in standalone_files:
        sf_path = os.path.join(PICTURES_DIR, sf["name"])
        if os.path.exists(sf_path):
            ext = os.path.splitext(sf["name"])[1].lower()
            file_type = "image" if ext in _IMAGE_EXTS else ("video" if ext in _VIDEO_EXTS else None)
            if file_type:
                standalone_enriched.append({
                    "name": sf["name"],
                    "description": sf["description"],
                    "files": [{"name": sf["name"], "type": file_type}],
                    "keywords": re.split(r"[、,\s/]+", sf["description"]),
                    "suitable_when": "",
                    "usage_tips": "",
                })

    # 4. 构建分类概览（供 agent 浏览）
    categories_summary = []
    for cat in enriched_categories:
        categories_summary.append({
            "category": cat["name"],
            "description": cat["description"],
            "file_count": cat["file_count"],
            "suitable_when": cat["suitable_when"],
            "keywords": cat["keywords"],
        })
    for sf in standalone_enriched:
        categories_summary.append({
            "category": sf["name"],
            "description": sf["description"],
            "file_count": 1,
            "suitable_when": sf["suitable_when"],
            "keywords": sf["keywords"],
        })

    # 5. 关键词匹配 + 收集结果
    results = []

    # 匹配子文件夹分类
    for cat in enriched_categories:
        # 分类精确过滤
        if category and cat["name"] != category:
            continue

        # 构建搜索文本（包含文件夹描述 + 单文件描述，让搜索单文件描述中的关键词也能命中）
        file_descs_text = " ".join(cat.get("file_descriptions", {}).values())
        search_text = f"{cat['description']} {cat['suitable_when']} {cat['usage_tips']} {file_descs_text}"

        # 关键词模糊匹配
        if not _fuzzy_match(keywords or [], cat["keywords"], search_text):
            continue

        # 收集该分类下的文件
        for f in cat["files"]:
            abs_path = os.path.join(PICTURES_DIR, cat["name"], f["name"])
            rel_path = f"{cat['name']}/{f['name']}"
            results.append({
                "absolute_path": abs_path,
                "relative_path": rel_path,
                "category": cat["name"],
                "description": cat["description"],
                "file_description": f.get("file_description", ""),  # 该文件的具体描述
                "keywords": cat["keywords"],
                "suitable_when": cat["suitable_when"],
                "usage_tips": cat["usage_tips"],
                "file_type": f["type"],
            })

        if len(results) >= limit:
            break

    # 匹配独立文件
    if len(results) < limit:
        for sf in standalone_enriched:
            if category and sf["name"] != category:
                continue

            search_text = f"{sf['description']} {sf['suitable_when']}"
            if not _fuzzy_match(keywords or [], sf["keywords"], search_text):
                continue

            for f in sf["files"]:
                abs_path = os.path.join(PICTURES_DIR, f["name"])
                rel_path = f["name"]
                results.append({
                    "absolute_path": abs_path,
                    "relative_path": rel_path,
                    "category": sf["name"],
                    "description": sf["description"],
                    "keywords": sf["keywords"],
                    "suitable_when": sf["suitable_when"],
                    "usage_tips": sf["usage_tips"],
                    "file_type": f["type"],
                })

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
        },
    }
