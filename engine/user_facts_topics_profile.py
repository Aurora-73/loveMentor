"""用户事实与话题画像前置批处理脚本（v4 7.2.4 节，架构调整后）。

本脚本不是 MCP 工具，而是启动前/定期执行一次的批处理，从数据库读取用户历史消息，
提取用户常聊的话题偏好和软事实，生成 data/user_facts_topics_profile.yaml 供 Agent 读取。

定位：话题选择层，帮助 Agent 选择合适的话题。
与 user_profile_fact.yaml 的区别：
  - user_profile_fact.yaml: 硬事实（手动填写，grounding 层，防止编造）
  - user_facts_topics_profile.yaml: 软事实+话题偏好（自动提取，话题选择层）

架构调整（2026-07-24）：
  - 旧脚本 user_style_profile.py 已删除（不分析对话风格，Agent 不模仿用户语言习惯）
  - 替换为 user_facts_topics_profile.py（提取事实+可谈论话题）
  - 策略优先级：Wiki > 上下文 > 事实 > 阶段（风格层已删除）

时间衰减机制（v4 7.2.7 节）：
  - 半衰期 90 天（距今越近的消息权重越大）

输出文件：data/user_facts_topics_profile.yaml
结构：
  topics:
    frequent_topics: [...]    # 高频话题（按权重排序）
    recent_topics: [...]      # 近期话题（最近30天）
    avoid_topics: [...]       # 避免话题（通用雷区 + user_profile_fact 情感雷区）
  soft_facts:
    frequent_places: [...]    # 常提的地点
    frequent_people: [...]    # 常提的人
    attitudes: [...]          # 态度/观点

用法：
  python -m engine.user_facts_topics_profile
  或
  python engine/user_facts_topics_profile.py
"""

from __future__ import annotations

import os
import re
import sys
import logging
import sqlite3
import yaml
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

OUTPUT_FILE = os.path.join(_PROJECT_ROOT, "data", "user_facts_topics_profile.yaml")

# 时间衰减半衰期（天）— v4 7.2.7 节
BASE_HALF_LIFE_DAYS = 90

# 采样窗口（只分析最近 N 天的消息）
SAMPLE_WINDOW_DAYS = 180

# 近期话题窗口（最近 N 天视为"近期"）
RECENT_TOPIC_WINDOW_DAYS = 30

# 最小样本数
MIN_SAMPLE_SIZE = 100

# ── 话题关键词词典 ──────────────────────────────────────────────
# 每个话题对应一组关键词，消息中出现任一关键词即视为涉及该话题
TOPIC_KEYWORDS: dict[str, list[str]] = {
    "猫猫": ["猫", "猫咪", "猫猫", "流浪猫", "三花", "猫咖", "顺拐", "喵"],
    "代码/编程": ["代码", "编程", "写代码", "vibe coding", "vibe", "python", "java", "cpp", "c++", "脚本", "bug", "debug"],
    "AI工具": ["claude", "codex", "deepseek", "trae", "ai", "gpt", "chatgpt", "llm", "大模型", "人工智能"],
    "论文/学术": ["论文", "学术", "会议", "dac", "iccad", "导师", "研究", "投稿", "中稿", "审稿"],
    "求职/秋招": ["求职", "秋招", "春招", "面试", "岗位", "招聘", "offer", "工作", "找工作", "简历"],
    "美食": ["吃", "好吃", "美食", "胡辣汤", "火锅", "奶茶", "咖啡", "餐厅", "外卖", "做饭"],
    "游戏（明日方舟）": ["明日方舟", "方舟", "游戏", "挂机", "抽卡", "干员", "源石"],
    "轻音乐": ["坂本龙一", "久石让", "三轮学", "市川淳", "轻音乐", "钢琴", "纯音乐"],
    "动漫": ["动漫", "动画", "番剧", "追番", "b站", "哔哩哔哩", "up主"],
    "剧本杀": ["剧本杀", "剧本", "杀本", "dm"],
    "爬虫": ["爬虫", "爬数据", "爬取", "scrapy", "spider", "requests"],
    "城市生活": ["长沙", "重庆", "长沙天气", "地铁", "校区", "宿舍"],
    "美国/旅行": ["美国", "长滩", "san jose", "加州", "签证", "飞机", "开会", "出差"],
}

# 地点关键词
PLACE_KEYWORDS: dict[str, list[str]] = {
    "长沙": ["长沙", "湖大", "<city_or_school>"],
    "重庆": ["重庆", "重邮", "重庆邮电"],
    "美国（长滩/San Jose）": ["美国", "长滩", "san jose", "加州"],
    "河南<hometown><hometown>": ["<hometown>", "<hometown>", "河南"],
}

# 态度/观点关键词
ATTITUDE_KEYWORDS: dict[str, list[str]] = {
    "务实求职观：哪儿工资高去哪儿": ["工资", "薪资", "待遇", "钱多"],
    "喜欢开源": ["开源", "github", "open source"],
    "对AI工具热情高": ["claude", "codex", "deepseek", "ai", "gpt"],
    "乐于助人：主动帮朋友写爬虫": ["帮你", "帮你爬", "帮你看", "我帮你"],
    "重视效率：善用工具": ["效率", "自动化", "工具", "批量"],
}


def main() -> int:
    """主入口：分析用户消息并生成话题画像。"""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    logger.info("开始生成用户事实与话题画像...")

    # 1. 加载配置和数据库
    try:
        from engine.config import load_config
        from engine.importers.db_init import get_db
        config = load_config()
        conn = get_db(config.db_path)
    except Exception as e:
        logger.error(f"数据库连接失败: {e}")
        return 1

    if not config.my_wxid:
        logger.error("config.my_wxid 未配置，无法识别用户消息")
        return 1

    try:
        # 2. 采样用户发送的消息
        messages = _fetch_user_messages(conn, config.my_wxid)
        if len(messages) < MIN_SAMPLE_SIZE:
            logger.warning(
                f"用户消息样本不足（{len(messages)}/{MIN_SAMPLE_SIZE}），"
                f"画像质量可能较低"
            )
            if not messages:
                logger.error("无用户消息，无法生成画像")
                return 1

        logger.info(f"采样到 {len(messages)} 条用户消息")

        # 3. 计算时间衰减权重
        weighted_messages = _apply_time_decay(messages)

        # 4. 分析话题偏好
        frequent_topics = _analyze_frequent_topics(weighted_messages)
        recent_topics = _analyze_recent_topics(messages)

        # 5. 分析软事实
        frequent_places = _analyze_frequent_places(weighted_messages)
        attitudes = _analyze_attitudes(weighted_messages)

        # 6. 加载避免话题（通用雷区 + user_profile_fact 情感雷区）
        avoid_topics = _load_avoid_topics()

        # 7. 组装画像
        profile = {
            "topics": {
                "frequent_topics": frequent_topics,
                "recent_topics": recent_topics,
                "avoid_topics": avoid_topics,
            },
            "soft_facts": {
                "frequent_places": frequent_places,
                "frequent_people": [],  # TODO: 需要联系人识别
                "attitudes": attitudes,
            },
            "meta": {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "sample_size": len(messages),
                "sample_window_days": SAMPLE_WINDOW_DAYS,
                "half_life_days": BASE_HALF_LIFE_DAYS,
                "my_wxid": config.my_wxid,
                "note": "由 engine/user_facts_topics_profile.py 自动生成",
            },
        }

        # 8. 写入文件
        _save_profile(profile)
        logger.info(f"画像已生成: {OUTPUT_FILE}")

        _print_summary(profile)
        return 0

    finally:
        conn.close()


def _fetch_user_messages(conn: sqlite3.Connection, my_wxid: str) -> list[dict]:
    """从数据库采样用户发送的消息（最近 SAMPLE_WINDOW_DAYS 天）。"""
    cutoff_ts = int((datetime.now() - timedelta(days=SAMPLE_WINDOW_DAYS)).timestamp())
    rows = conn.execute(
        """
        SELECT id, conversation_id, sender_id, content, timestamp, type
        FROM messages
        WHERE sender_id = ?
          AND timestamp >= ?
          AND type = 1
          AND content IS NOT NULL
          AND length(content) > 0
        ORDER BY timestamp DESC
        LIMIT 5000
        """,
        (my_wxid, cutoff_ts),
    ).fetchall()

    return [
        {
            "id": r["id"],
            "conversation_id": r["conversation_id"],
            "content": r["content"] or "",
            "timestamp": r["timestamp"],
        }
        for r in rows
    ]


def _apply_time_decay(messages: list[dict]) -> list[tuple[dict, float]]:
    """对消息应用时间衰减权重（半衰期 90 天）。"""
    now_ts = datetime.now().timestamp()
    half_life_sec = BASE_HALF_LIFE_DAYS * 86400
    result = []
    for msg in messages:
        age_sec = max(0, now_ts - msg["timestamp"])
        weight = 0.5 ** (age_sec / half_life_sec)
        result.append((msg, weight))
    return result


# ── 话题分析 ────────────────────────────────────────────────────


def _analyze_frequent_topics(weighted_messages: list[tuple[dict, float]]) -> list[dict]:
    """分析高频话题（基于关键词匹配 + 时间衰减权重）。"""
    topic_weights: dict[str, float] = {topic: 0.0 for topic in TOPIC_KEYWORDS}
    total_weight = 0.0

    for msg, weight in weighted_messages:
        content = msg["content"].lower()
        if not content:
            continue
        total_weight += weight
        for topic, keywords in TOPIC_KEYWORDS.items():
            for kw in keywords:
                if kw.lower() in content:
                    topic_weights[topic] += weight
                    break  # 每条消息每个话题只计一次

    # 归一化为 0-1 权重
    max_weight = max(topic_weights.values()) if topic_weights else 1.0
    if max_weight == 0:
        return []

    # 按权重排序
    sorted_topics = sorted(topic_weights.items(), key=lambda x: x[1], reverse=True)

    result = []
    for topic, weight in sorted_topics:
        if weight <= 0:
            continue
        normalized_weight = round(weight / max_weight, 2)
        result.append({
            "topic": topic,
            "weight": normalized_weight,
            "context": _get_topic_context(topic),
            "good_for_stages": _get_topic_stages(topic),
        })

    return result


def _analyze_recent_topics(messages: list[dict]) -> list[str]:
    """分析近期话题（最近 RECENT_TOPIC_WINDOW_DAYS 天）。"""
    cutoff_ts = int((datetime.now() - timedelta(days=RECENT_TOPIC_WINDOW_DAYS)).timestamp())
    recent_topic_set: set[str] = set()

    for msg in messages:
        if msg["timestamp"] < cutoff_ts:
            continue
        content = msg["content"].lower()
        for topic, keywords in TOPIC_KEYWORDS.items():
            for kw in keywords:
                if kw.lower() in content:
                    recent_topic_set.add(topic)
                    break

    return sorted(recent_topic_set)


def _analyze_frequent_places(weighted_messages: list[tuple[dict, float]]) -> list[dict]:
    """分析常提的地点。"""
    place_weights: dict[str, float] = {place: 0.0 for place in PLACE_KEYWORDS}

    for msg, weight in weighted_messages:
        content = msg["content"].lower()
        for place, keywords in PLACE_KEYWORDS.items():
            for kw in keywords:
                if kw.lower() in content:
                    place_weights[place] += weight
                    break

    sorted_places = sorted(place_weights.items(), key=lambda x: x[1], reverse=True)
    result = []
    for place, weight in sorted_places:
        if weight <= 0:
            continue
        result.append({
            "place": place,
            "context": _get_place_context(place),
        })

    return result


def _analyze_attitudes(weighted_messages: list[tuple[dict, float]]) -> list[str]:
    """分析用户的态度/观点。"""
    attitude_scores: dict[str, float] = {att: 0.0 for att in ATTITUDE_KEYWORDS}

    for msg, weight in weighted_messages:
        content = msg["content"].lower()
        for attitude, keywords in ATTITUDE_KEYWORDS.items():
            for kw in keywords:
                if kw.lower() in content:
                    attitude_scores[attitude] += weight
                    break

    # 只返回出现过的态度（权重 > 0）
    return [att for att, score in sorted(attitude_scores.items(), key=lambda x: x[1], reverse=True) if score > 0]


def _load_avoid_topics() -> list[dict]:
    """加载避免话题（通用雷区 + user_profile_fact 情感雷区）。"""
    avoid_topics = [
        {"topic": "政治敏感话题", "reason": "通用避免"},
        {"topic": "宗教/极端观点", "reason": "通用避免"},
    ]

    # 从 user_profile_fact.yaml 加载情感雷区（如果有）
    fact_file = os.path.join(_PROJECT_ROOT, "data", "user_profile_fact.yaml")
    if os.path.isfile(fact_file):
        try:
            with open(fact_file, "r", encoding="utf-8") as f:
                fact = yaml.safe_load(f) or {}
            for exp in fact.get("experiences", []):
                details = exp.get("details", "")
                if "分手" in details or "删除" in details:
                    event = exp.get("event", "")
                    avoid_topics.append({
                        "topic": f"前任相关（{event}）",
                        "reason": "情感雷区，除非对方主动问",
                        "exception": "对方主动询问时可简短提及，不主动展开",
                    })
        except Exception:
            pass

    return avoid_topics


# ── 上下文/阶段映射（静态配置）──────────────────────────────────


def _get_topic_context(topic: str) -> str:
    """获取话题的上下文说明。"""
    contexts = {
        "猫猫": "大学时喂流浪猫（400多只），最常喂三花猫'顺拐'",
        "代码/编程": "vibe coding，写爬虫帮朋友",
        "AI工具": "claude, codex, DeepSeek, trae",
        "论文/学术": "DAC, ICCAD 论文中稿，半年两篇",
        "求职/秋招": "2026秋招，务实求职观",
        "美食": "各地美食，胡辣汤等",
        "游戏（明日方舟）": "主要用自动化工具挂机",
        "轻音乐": "坂本龙一、久石让、三轮学、市川淳",
        "动漫": "大学时常看，现在没时间看了",
        "剧本杀": "曾与朋友一起玩过",
        "爬虫": "写招聘网站爬虫，批量爬数据给AI分析",
        "城市生活": "长沙、重庆生活对比",
        "美国/旅行": "参加学术会议，可谈论旅行经历",
    }
    return contexts.get(topic, "")


def _get_topic_stages(topic: str) -> list[str]:
    """获取话题适合的关系阶段。"""
    stage_map = {
        "猫猫": ["stage_1", "stage_2", "stage_3", "stage_4"],
        "代码/编程": ["stage_1", "stage_2", "stage_3"],
        "AI工具": ["stage_1", "stage_2", "stage_3"],
        "论文/学术": ["stage_2", "stage_3", "stage_4"],
        "求职/秋招": ["stage_2", "stage_3", "stage_4"],
        "美食": ["stage_1", "stage_2", "stage_3", "stage_4"],
        "游戏（明日方舟）": ["stage_1", "stage_2", "stage_3"],
        "轻音乐": ["stage_2", "stage_3", "stage_4"],
        "动漫": ["stage_1", "stage_2"],
        "剧本杀": ["stage_2", "stage_3"],
        "爬虫": ["stage_1", "stage_2", "stage_3"],
        "城市生活": ["stage_1", "stage_2", "stage_3"],
        "美国/旅行": ["stage_2", "stage_3", "stage_4"],
    }
    return stage_map.get(topic, ["stage_1", "stage_2"])


def _get_place_context(place: str) -> str:
    """获取地点的上下文说明。"""
    contexts = {
        "长沙": "当前所在地，研究生生活",
        "重庆": "本科回忆，重庆邮电大学，喂猫经历",
        "美国（长滩/San Jose）": "即将参加学术会议，可谈论旅行",
        "河南<hometown><hometown>": "老家",
    }
    return contexts.get(place, "")


# ── 工具函数 ────────────────────────────────────────────────────


def _save_profile(profile: dict) -> None:
    """保存画像到 YAML。"""
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        yaml.dump(profile, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def _print_summary(profile: dict) -> None:
    """打印画像摘要。"""
    try:
        print("\n" + "=" * 60)
        print("用户事实与话题画像摘要")
        print("=" * 60)
        print(f"样本量: {profile['meta']['sample_size']} 条消息")
        print(f"采样窗口: {profile['meta']['sample_window_days']} 天")
        print()
        print("[高频话题]")
        for t in profile["topics"]["frequent_topics"][:5]:
            print(f"  - {t['topic']}: weight={t['weight']}")
        print(f"\n[近期话题] {profile['topics']['recent_topics']}")
        print(f"\n[常提地点] {[p['place'] for p in profile['soft_facts']['frequent_places'][:3]]}")
        print(f"\n[态度] {profile['soft_facts']['attitudes'][:3]}")
        print("=" * 60 + "\n")
    except Exception:
        pass


if __name__ == "__main__":
    sys.exit(main())
