"""用户表达风格前置批处理脚本（v4 7.2.4 节）。

本脚本不是 MCP 工具，而是启动前/定期执行一次的批处理，从数据库读取用户历史消息，
分析用户的表达风格，生成 data/user_style_profile.yaml 供 Agent 读取。

定位：弱辅助（smoothing），只用于降低突兀感，不能主导策略。

时间衰减机制（v4 7.2.7 节）：
  - base 层半衰期 90 天（跨联系人稳定的固有习惯）
  - per_contact 层半衰期 30 天（联系人特化层，本脚本不生成，由 user_profile_manage 管理）
  - 距今越近的消息权重越大

输出文件：data/user_style_profile.yaml
结构（v4 7.2.4 节）：
  vocabulary:
    top_words: [...]         # 高频词
    unique_phrases: [...]    # 独特短语
    avoid_words: []          # 用户避免的词（暂不提取）
  sentence_style:
    avg_length: 12           # 平均句长
    length_distribution: "偏短"  # 偏短/适中/偏长
    punctuation_habits: "..."    # 标点习惯
  emoji_usage:
    top_emojis: [...]
    emoji_frequency: "中等"      # 低/中/高
  response_pattern:
    avg_response_delay_min: 5
    delay_distribution: "..."
    initiative_ratio: 0.4
  tone_features:
    playfulness: 0.5         # 0-1
    directness: 0.6
    warmth: 0.5

用法：
  python -m scripts.user_style_profile
  或
  python scripts/user_style_profile.py
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

OUTPUT_FILE = os.path.join(_PROJECT_ROOT, "data", "user_style_profile.yaml")

# 时间衰减半衰期（天）— v4 7.2.7 节
BASE_HALF_LIFE_DAYS = 90

# 采样窗口（只分析最近 N 天的消息，避免数据量过大）
SAMPLE_WINDOW_DAYS = 180

# 最小样本数（少于则不生成画像）
MIN_SAMPLE_SIZE = 100

# 中文常用停用词（用于 top_words 提取）
_STOP_WORDS = {
    "的", "了", "是", "在", "我", "你", "他", "她", "我们", "你们", "他们",
    "这", "那", "这个", "那个", "这些", "那些", "什么", "怎么", "为什么",
    "不", "没", "没有", "也", "都", "还", "就", "只", "才", "又", "再",
    "和", "与", "但", "但是", "因为", "所以", "如果", "虽然", "虽然如此",
    "一个", "一些", "一下", "可以", "能", "会", "要", "想", "觉得",
    "啊", "吧", "哦", "嗯", "呢", "哈", "哈哈", "嘿嘿", "呵呵",
    "很", "太", "真", "非常", "特别", "超级", "超",
}


def main() -> int:
    """主入口：分析用户消息并生成画像。"""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    logger.info("开始生成用户表达风格画像...")

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

        # 4. 分析各维度
        profile = {
            "vocabulary": _analyze_vocabulary(weighted_messages),
            "sentence_style": _analyze_sentence_style(weighted_messages),
            "emoji_usage": _analyze_emoji_usage(weighted_messages),
            "response_pattern": _analyze_response_pattern(conn, config.my_wxid, weighted_messages),
            "tone_features": _analyze_tone_features(weighted_messages),
            "meta": {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "sample_size": len(messages),
                "sample_window_days": SAMPLE_WINDOW_DAYS,
                "half_life_days": BASE_HALF_LIFE_DAYS,
                "my_wxid": config.my_wxid,
            },
        }

        # 5. 写入文件
        _save_profile(profile)
        logger.info(f"画像已生成: {OUTPUT_FILE}")

        # 打印摘要
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
    """对消息应用时间衰减权重（半衰期 90 天）。

    返回 [(message, weight), ...]，weight ∈ (0, 1]。
    """
    now_ts = datetime.now().timestamp()
    half_life_sec = BASE_HALF_LIFE_DAYS * 86400
    result = []
    for msg in messages:
        age_sec = max(0, now_ts - msg["timestamp"])
        # 指数衰减：weight = 0.5^(age / half_life)
        weight = 0.5 ** (age_sec / half_life_sec)
        result.append((msg, weight))
    return result


# ── 维度分析 ────────────────────────────────────────────────────


def _analyze_vocabulary(weighted_messages: list[tuple[dict, float]]) -> dict:
    """分析词汇使用（top_words + unique_phrases）。"""
    word_counter = Counter()
    total_weight = 0.0

    for msg, weight in weighted_messages:
        content = msg["content"]
        if not content:
            continue
        total_weight += weight
        # 提取词（这里用简单分词：2-4 字滑动窗口 + 停用词过滤）
        words = _extract_words(content)
        for w in words:
            word_counter[w] += weight

    # top_words: 权重前 10
    top_words = [
        {"word": w, "weight": round(c / max(total_weight, 1), 4)}
        for w, c in word_counter.most_common(10)
    ]

    # unique_phrases: 出现频次 2-10 次且不在停用词中的特殊短语
    unique_phrases = []
    for w, c in word_counter.most_common(50):
        if 2 <= c <= 10 and w not in _STOP_WORDS and len(w) >= 2:
            unique_phrases.append(w)
        if len(unique_phrases) >= 5:
            break

    return {
        "top_words": [item["word"] for item in top_words],
        "top_words_with_weight": top_words,
        "unique_phrases": unique_phrases,
        "avoid_words": [],  # 暂不提取（需语义分析）
    }


def _analyze_sentence_style(weighted_messages: list[tuple[dict, float]]) -> dict:
    """分析句子风格（句长 + 标点习惯）。"""
    lengths = []
    punctuation_counter = Counter()
    total_weight = 0.0

    for msg, weight in weighted_messages:
        content = msg["content"].strip()
        if not content:
            continue
        total_weight += weight
        lengths.append((len(content), weight))

        # 统计标点
        for ch in content:
            if ch in "。，！？、；：""''…—！？":
                punctuation_counter[ch] += weight

    if not lengths:
        return {"avg_length": 0, "length_distribution": "未知", "punctuation_habits": "未知"}

    # 加权平均句长
    total_len = sum(l * w for l, w in lengths)
    avg_length = round(total_len / max(sum(w for _, w in lengths), 1))

    # 长度分布
    if avg_length < 8:
        distribution = "偏短"
    elif avg_length < 20:
        distribution = "适中"
    else:
        distribution = "偏长"

    # 标点习惯
    top_punct = punctuation_counter.most_common(3)
    if not top_punct:
        punct_habits = "少用标点"
    else:
        parts = []
        for ch, _ in top_punct:
            if ch == "。":
                parts.append("常用句号")
            elif ch == "，":
                parts.append("常用逗号")
            elif ch == "！":
                parts.append("常用感叹号")
            elif ch == "？":
                parts.append("常用问号")
            elif ch == "…":
                parts.append("常用省略号")
        punct_habits = "、".join(parts) if parts else "少用标点"

    return {
        "avg_length": avg_length,
        "length_distribution": distribution,
        "punctuation_habits": punct_habits,
    }


def _analyze_emoji_usage(weighted_messages: list[tuple[dict, float]]) -> dict:
    """分析表情使用（top_emojis + 频率）。"""
    emoji_counter = Counter()
    total_msgs = 0
    msgs_with_emoji = 0

    # 表情符号正则（Unicode emoji 范围）
    # 注意：不能用 \U000024C2-\U0001F251 这种过宽的范围，会包含 CJK 汉字
    emoji_pattern = re.compile(
        "["
        "\U0001F600-\U0001F64F"  # 表情符号
        "\U0001F300-\U0001F5FF"  # 符号 & 象形文字
        "\U0001F680-\U0001F6FF"  # 交通和地图符号
        "\U0001F1E0-\U0001F1FF"  # 旗帜
        "\U00002600-\U000026FF"  # 杂项符号（太阳/月亮/星星等）
        "\U00002700-\U000027BF"  # 装饰符号（剪刀/雪花等）
        "\U0001F900-\U0001F9FF"  # 补充表情符号
        "\U0001FA70-\U0001FAFF"  # 符号和象形文字扩展 A
        "]+",
        flags=re.UNICODE,
    )

    for msg, weight in weighted_messages:
        content = msg["content"]
        if not content:
            continue
        total_msgs += 1
        emojis = emoji_pattern.findall(content)
        if emojis:
            msgs_with_emoji += 1
            for e in emojis:
                emoji_counter[e] += weight

    # 频率分级
    if total_msgs == 0:
        frequency = "未知"
    else:
        ratio = msgs_with_emoji / total_msgs
        if ratio < 0.1:
            frequency = "低"
        elif ratio < 0.4:
            frequency = "中"
        else:
            frequency = "高"

    top_emojis = [e for e, _ in emoji_counter.most_common(10)]

    return {
        "top_emojis": top_emojis,
        "emoji_frequency": frequency,
        "emoji_message_ratio": round(msgs_with_emoji / max(total_msgs, 1), 3),
    }


def _analyze_response_pattern(
    conn: sqlite3.Connection,
    my_wxid: str,
    weighted_messages: list[tuple[dict, float]],
) -> dict:
    """分析回复模式（平均延迟 + 主动率）。

    主动率 = 用户主动发起对话的次数 / 总对话次数
    （通过 4 小时无消息作为会话分割）
    """
    # 按 conversation_id 分组，计算回复延迟
    if not weighted_messages:
        return {"avg_response_delay_min": 0, "delay_distribution": "未知", "initiative_ratio": 0.0}

    # 取所有相关会话的消息（包括对方发的，用于计算回复延迟）
    conversation_ids = list({msg["conversation_id"] for msg, _ in weighted_messages})
    if not conversation_ids:
        return {"avg_response_delay_min": 0, "delay_distribution": "未知", "initiative_ratio": 0.0}

    placeholders = ",".join("?" for _ in conversation_ids)
    cutoff_ts = int((datetime.now() - timedelta(days=SAMPLE_WINDOW_DAYS)).timestamp())
    rows = conn.execute(
        f"""
        SELECT id, conversation_id, sender_id, timestamp
        FROM messages
        WHERE conversation_id IN ({placeholders})
          AND timestamp >= ?
          AND type = 1
        ORDER BY conversation_id, timestamp
        """,
        (*conversation_ids, cutoff_ts),
    ).fetchall()

    # 按会话分组
    sessions = {}
    for r in rows:
        cid = r["conversation_id"]
        if cid not in sessions:
            sessions[cid] = []
        sessions[cid].append({
            "sender_id": r["sender_id"],
            "timestamp": r["timestamp"],
        })

    # 计算回复延迟（对方发 → 我回，间隔 <= 1 小时算作回复）
    reply_delays = []
    my_initiatives = 0
    total_sessions = 0
    session_gap_sec = 4 * 3600  # 4 小时无消息视为新会话

    for cid, msgs in sessions.items():
        if not msgs:
            continue
        # 分割会话
        current_session = [msgs[0]]
        for i in range(1, len(msgs)):
            if msgs[i]["timestamp"] - msgs[i - 1]["timestamp"] > session_gap_sec:
                # 处理当前会话
                total_sessions += 1
                if current_session[0]["sender_id"] == my_wxid:
                    my_initiatives += 1
                # 计算回复延迟
                _compute_reply_delays(current_session, my_wxid, reply_delays)
                current_session = [msgs[i]]
            else:
                current_session.append(msgs[i])
        # 处理最后一个会话
        if current_session:
            total_sessions += 1
            if current_session[0]["sender_id"] == my_wxid:
                my_initiatives += 1
            _compute_reply_delays(current_session, my_wxid, reply_delays)

    # 平均回复延迟（分钟）
    if reply_delays:
        avg_delay_sec = sum(reply_delays) / len(reply_delays)
        avg_delay_min = round(avg_delay_sec / 60, 1)
        # 延迟分布
        if avg_delay_min < 1:
            distribution = "秒回"
        elif avg_delay_min < 10:
            distribution = "较快"
        elif avg_delay_min < 60:
            distribution = "适中"
        else:
            distribution = "较慢"
    else:
        avg_delay_min = 0
        distribution = "未知"

    # 主动率
    initiative_ratio = round(my_initiatives / max(total_sessions, 1), 2)

    return {
        "avg_response_delay_min": avg_delay_min,
        "delay_distribution": distribution,
        "initiative_ratio": initiative_ratio,
        "sample_replies": len(reply_delays),
        "sample_sessions": total_sessions,
    }


def _compute_reply_delays(session: list[dict], my_wxid: str, out_delays: list[float]) -> None:
    """计算单个会话内对方→我的回复延迟（秒）。"""
    for i in range(1, len(session)):
        prev = session[i - 1]
        curr = session[i]
        # 对方发 → 我回（且间隔 <= 1 小时）
        if (prev["sender_id"] != my_wxid
                and curr["sender_id"] == my_wxid
                and 0 < curr["timestamp"] - prev["timestamp"] <= 3600):
            out_delays.append(curr["timestamp"] - prev["timestamp"])


def _analyze_tone_features(weighted_messages: list[tuple[dict, float]]) -> dict:
    """分析语气特征（playfulness / directness / warmth）。

    基于启发式规则估算（非 LLM 语义分析）：
    - playfulness：表情/笑声/调侃词频率
    - directness：疑问句/命令式比例 vs 长解释
    - warmth：关心词/称呼词频率
    """
    total_weight = 0.0
    playful_score = 0.0
    direct_score = 0.0
    warm_score = 0.0

    playful_markers = ["哈哈", "嘿嘿", "呵呵", "嘻嘻", "～", "~", "😄", "😂", "🤣", "😆", "😜"]
    warm_markers = ["关心", "注意", "照顾", "加油", "辛苦", "早点睡", "注意安全", "想你", "喜欢"]
    direct_markers = ["？", "?", "吧", "呢", "嘛"]

    for msg, weight in weighted_messages:
        content = msg["content"]
        if not content:
            continue
        total_weight += weight

        if any(m in content for m in playful_markers):
            playful_score += weight
        if any(m in content for m in warm_markers):
            warm_score += weight
        if any(m in content for m in direct_markers):
            direct_score += weight

    if total_weight == 0:
        return {"playfulness": 0.5, "directness": 0.5, "warmth": 0.5}

    return {
        "playfulness": round(min(1.0, playful_score / total_weight * 3), 2),
        "directness": round(min(1.0, direct_score / total_weight * 2), 2),
        "warmth": round(min(1.0, warm_score / total_weight * 5), 2),
    }


# ── 工具函数 ────────────────────────────────────────────────────


def _extract_words(text: str) -> list[str]:
    """简单中文分词（2-4 字滑动窗口 + 停用词过滤）。

    这不是真正的分词，而是基于 n-gram 的近似。
    对于风格画像的 top_words 来说足够使用。
    """
    text = text.strip()
    if not text:
        return []

    words = []
    # 单字（过滤停用词和标点）
    for ch in text:
        if "\u4e00" <= ch <= "\u9fff" and ch not in _STOP_WORDS:
            words.append(ch)

    # 2-3 字组合
    for n in (2, 3):
        for i in range(len(text) - n + 1):
            piece = text[i:i + n]
            # 全中文才算
            if all("\u4e00" <= c <= "\u9fff" for c in piece) and piece not in _STOP_WORDS:
                words.append(piece)

    return words


def _save_profile(profile: dict) -> None:
    """保存画像到 YAML。"""
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        yaml.dump(profile, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def _print_summary(profile: dict) -> None:
    """打印画像摘要。"""
    try:
        print("\n" + "=" * 60)
        print("用户表达风格画像摘要")
        print("=" * 60)
        print(f"样本量: {profile['meta']['sample_size']} 条消息")
        print(f"采样窗口: {profile['meta']['sample_window_days']} 天")
        print(f"半衰期: {profile['meta']['half_life_days']} 天")
        print()
        print(f"[词汇] top_words: {profile['vocabulary']['top_words'][:5]}")
        print(f"[句子] 平均长度: {profile['sentence_style']['avg_length']} 字（{profile['sentence_style']['length_distribution']}）")
        print(f"[表情] 频率: {profile['emoji_usage']['emoji_frequency']}, top: {profile['emoji_usage']['top_emojis'][:3]}")
        print(f"[回复] 平均延迟: {profile['response_pattern']['avg_response_delay_min']} 分钟（{profile['response_pattern']['delay_distribution']}）")
        print(f"[回复] 主动率: {profile['response_pattern']['initiative_ratio']}")
        print(f"[语气] 俏皮={profile['tone_features']['playfulness']} 直接={profile['tone_features']['directness']} 温暖={profile['tone_features']['warmth']}")
        print("=" * 60 + "\n")
    except Exception:
        pass  # 在某些环境下 print 可能失败


if __name__ == "__main__":
    sys.exit(main())
