"""指标计算引擎（辅助指标，结构化数字摘要）。

从 SQLite 读取消息数据，计算 15 个辅助指标（结构化数字摘要）+ signal_flags（动态信号）+ media_engagement（媒体互动）+ neediness_penalty（需求感惩罚）+ interaction_pattern（互动模式标签）。
base_score 不含 trend，trend = base_score 周变化，composite = base_score + trend 权重。

本质：把非结构化聊天记录压缩成 Agent 好消化的结构化数字，不是评分系统。
来源：Wiki 知识库总结 + GitHub 参考 + 案例反馈共同产生的结构化数字。
Agent 参考这些指标但不机械套用阈值，最终判断依据是 Wiki 知识 + 事实档案。
"""

import math
import sqlite3
import time
from datetime import datetime, timedelta
from typing import Optional

from engine.config import Config, WeightsConfig, MetricsConfig
from engine.models.metrics import Metrics, MetricValue


SIGNAL_LEVELS = ["强窗口", "中窗口", "弱窗口", "冷淡", "无信号"]

SIGNAL_ORDER = {level: len(SIGNAL_LEVELS) - 1 - i for i, level in enumerate(SIGNAL_LEVELS)}

SIGNAL_THRESHOLDS = [
    (0.45, "强窗口"),
    (0.35, "中窗口"),
    (0.25, "弱窗口"),
    (0.10, "冷淡"),
    (0.00, "无信号"),
]


def _confidence(sample_size: int) -> float:
    if sample_size >= 100:
        return 0.8 + min(0.2, (sample_size - 100) / 4900)
    if sample_size >= 20:
        return 0.5 + 0.3 * (sample_size - 20) / 80
    if sample_size > 0:
        return 0.1 + 0.4 * sample_size / 20
    return 0.0


def _normalize_ratio(raw: float) -> float:
    return raw / (1.0 + raw) if raw >= 0 else 0.0


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def compute_fback(conn: sqlite3.Connection, my_wxid: str, contact_wxid: str, window_days: int = 30, ref_date: Optional[datetime] = None) -> MetricValue:
    now = ref_date or datetime.now()
    cutoff = int((now - timedelta(days=window_days)).timestamp())
    rows = conn.execute(
        "SELECT sender_id, LENGTH(COALESCE(content, '')) AS chars "
        "FROM messages WHERE conversation_id = ? AND timestamp >= ? AND type = 1",
        (contact_wxid, cutoff),
    ).fetchall()

    my_chars = sum(r["chars"] for r in rows if r["sender_id"] == my_wxid)
    her_chars = sum(r["chars"] for r in rows if r["sender_id"] != my_wxid)

    if my_chars == 0:
        return MetricValue(raw=0.0, normalized=0.0, confidence=0.0, sample_size=len(rows))

    raw = her_chars / my_chars
    return MetricValue(
        raw=round(raw, 4),
        normalized=round(_normalize_ratio(raw), 4),
        confidence=round(_confidence(len(rows)), 2),
        sample_size=len(rows),
    )


def compute_rlatency(conn: sqlite3.Connection, my_wxid: str, contact_wxid: str, session_gap_hours: int = 4, to_ts: Optional[int] = None) -> MetricValue:
    if to_ts is not None:
        rows = conn.execute(
            "SELECT sender_id, timestamp FROM messages "
            "WHERE conversation_id = ? AND type = 1 AND timestamp <= ? ORDER BY timestamp",
            (contact_wxid, to_ts),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT sender_id, timestamp FROM messages "
            "WHERE conversation_id = ? AND type = 1 ORDER BY timestamp",
            (contact_wxid,),
        ).fetchall()

    if len(rows) < 2:
        return MetricValue(raw=0.0, normalized=0.0, confidence=0.0, sample_size=len(rows))

    gap_seconds = session_gap_hours * 3600
    my_intervals = []
    her_intervals = []

    for i in range(1, len(rows)):
        prev = rows[i - 1]
        curr = rows[i]
        dt = curr["timestamp"] - prev["timestamp"]
        if dt <= 0 or dt > gap_seconds:
            continue
        if prev["sender_id"] != curr["sender_id"]:
            if curr["sender_id"] == my_wxid:
                my_intervals.append(dt)
            else:
                her_intervals.append(dt)

    if not my_intervals or not her_intervals:
        return MetricValue(raw=0.0, normalized=0.0, confidence=0.0,
                           sample_size=len(my_intervals) + len(her_intervals))

    avg_my = sum(my_intervals) / len(my_intervals)
    avg_her = sum(her_intervals) / len(her_intervals)

    if avg_her == 0:
        return MetricValue(raw=0.0, normalized=0.0, confidence=0.0,
                           sample_size=len(my_intervals) + len(her_intervals),
                           extra={"avg_my_seconds": 0.0, "avg_her_seconds": 0.0})

    raw = avg_my / avg_her
    sample = len(my_intervals) + len(her_intervals)
    return MetricValue(
        raw=round(raw, 4),
        normalized=round(_normalize_ratio(raw), 4),
        confidence=round(_confidence(sample), 2),
        sample_size=sample,
        extra={"avg_my_seconds": round(avg_my, 2), "avg_her_seconds": round(avg_her, 2)},
    )


def _compute_her_ratio(conn: sqlite3.Connection, contact_wxid: str, char: str, window_days: int, ref_date: Optional[datetime] = None) -> MetricValue:
    """计算她的消息中含指定字符的比例（用于 qscore）。"""
    now = ref_date or datetime.now()
    cutoff = int((now - timedelta(days=window_days)).timestamp())
    rows = conn.execute(
        "SELECT content FROM messages "
        "WHERE conversation_id = ? AND sender_id = ? AND timestamp >= ? AND type = 1 "
        "AND content IS NOT NULL",
        (contact_wxid, contact_wxid, cutoff),
    ).fetchall()

    if not rows:
        return MetricValue(raw=0.0, normalized=0.0, confidence=0.0, sample_size=0)

    contains = sum(1 for r in rows if char in (r["content"] or ""))
    raw = contains / len(rows)
    normalized = _clamp(raw * 3.0) if char == "?" else _clamp(raw * 1.5)

    return MetricValue(
        raw=round(raw, 4),
        normalized=round(normalized, 4),
        confidence=round(_confidence(len(rows)), 2),
        sample_size=len(rows),
    )


def _compute_emotion_ratio(conn: sqlite3.Connection, my_wxid: str, contact_wxid: str, window_days: int, ref_date: Optional[datetime] = None) -> MetricValue:
    emotion_words = ["哈哈", "嘻嘻", "呜呜", "嗯嗯", "好的", "好吧", "嘿嘿", "噗",
                     "哇", "嗯", "呵", "emmm", "hhh", "233",
                     "宝宝", "爱你", "想你", "可爱", "抱抱", "亲亲", "么么", "宝贝",
                     "笨蛋", "傻瓜", "讨厌", "哼", "委屈", "难过", "开心", "好喜欢"]

    # 微信 [xxx] 格式表情 → 情绪强度（1.0=高情绪，0.5=中性，0.2=低情绪）
    _WECHAT_EMOJI = {
        # 高情绪（正面/负面强烈）
        "破涕为笑": 1.0, "笑哭": 1.0, "捂脸": 0.9, "偷笑": 0.9, "憨笑": 0.9,
        "旺柴": 0.8, "奸笑": 0.8, "耶": 0.9, "加油": 0.8, "庆祝": 0.9,
        "爱心": 1.0, "玫瑰": 0.8, "飞吻": 1.0, "抱抱": 0.9, "亲亲": 1.0,
        "大哭": 1.0, "流泪": 0.9, "委屈": 0.9, "苦涩": 0.8, "裂开": 0.8,
        "发怒": 0.9, "咒骂": 0.8, "打脸": 0.8, "白眼": 0.7,
        # 中情绪
        "吃瓜": 0.6, "尴尬": 0.6, "皱眉": 0.6, "叹气": 0.6,
        "666": 0.7, "握手": 0.6, "抱拳": 0.5,
        "让我看看": 0.6, "天啊": 0.7,
        # 低情绪（附和型）
        "微笑": 0.3, "再见": 0.3, "ok": 0.3, "好的": 0.3,
    }

    def _has_unicode_emoji(content: str) -> bool:
        """检测 Unicode emoji（扩展范围）。"""
        for c in content:
            cp = ord(c)
            # 常见 emoji 范围
            if 0x1F600 <= cp <= 0x1F64F:  # 表情
                return True
            if 0x1F300 <= cp <= 0x1F5FF:  # 符号和象形文字
                return True
            if 0x1F680 <= cp <= 0x1F6FF:  # 交通和地图
                return True
            if 0x1F900 <= cp <= 0x1F9FF:  # 补充符号
                return True
            if 0x1FA00 <= cp <= 0x1FA6F:  # 棋子
                return True
            if 0x1FA70 <= cp <= 0x1FAFF:  # 扩展A
                return True
            if 0x2600 <= cp <= 0x26FF:    # 杂项符号
                return True
            if 0x2700 <= cp <= 0x27BF:    # 装饰符号
                return True
            if 0xFE00 <= cp <= 0xFE0F:    # 变体选择符
                return True
            if 0x200D <= cp <= 0x200D:    # 零宽连接符
                return True
            if 0x2764 <= cp <= 0x2764:    # ❤
                return True
            if 0x1F0A0 <= cp <= 0x1F0FF:  # 扑克牌等
                return True
        return False

    now = ref_date or datetime.now()
    cutoff = int((now - timedelta(days=window_days)).timestamp())

    # 1. 文本消息 (type=1)
    rows = conn.execute(
        "SELECT content FROM messages "
        "WHERE conversation_id = ? AND sender_id = ? AND timestamp >= ? AND type = 1 "
        "AND content IS NOT NULL",
        (contact_wxid, contact_wxid, cutoff),
    ).fetchall()

    # 2. 已标注贴纸 (type=47)
    from engine.stickers import ensure_stickers_table, get_labeled_emotions
    import re as _re
    _md5_pattern = _re.compile(r'md5="([a-f0-9]{32})"')
    labeled = get_labeled_emotions(conn)

    sticker_rows = conn.execute(
        "SELECT raw_content FROM messages "
        "WHERE conversation_id = ? AND sender_id != ? AND timestamp >= ? AND type = 47 "
        "AND raw_content IS NOT NULL",
        (contact_wxid, my_wxid, cutoff),
    ).fetchall()

    sticker_emotional = 0
    sticker_total = 0
    for r in sticker_rows:
        m = _md5_pattern.search(r["raw_content"] or "")
        if not m:
            continue
        md5 = m.group(1)
        emotion = labeled.get(md5, "")
        if not emotion:
            continue  # 未标注的不计入
        sticker_total += 1
        if emotion in ("positive", "negative"):
            sticker_emotional += 1

    total = len(rows) + sticker_total
    if total == 0:
        return MetricValue(raw=0.0, normalized=0.0, confidence=0.0, sample_size=0)

    _wechat_emoji_pattern = _re.compile(r'\[([^\]]{1,10})\]')

    contains = sticker_emotional  # 已标注贴纸中的情绪贴纸
    for r in rows:
        content = r["content"] or ""
        # 1. Unicode emoji
        if _has_unicode_emoji(content):
            contains += 1
        # 2. 微信 [xxx] 格式表情
        elif _wechat_emoji_pattern.search(content):
            matches = _wechat_emoji_pattern.findall(content)
            if any(m in _WECHAT_EMOJI for m in matches):
                contains += 1
        # 3. 文本情绪词
        elif any(w in content for w in emotion_words):
            contains += 1

    raw = contains / total
    normalized = _clamp(raw * 1.5)

    return MetricValue(
        raw=round(raw, 4),
        normalized=round(normalized, 4),
        confidence=round(_confidence(total), 2),
        sample_size=total,
    )


def compute_moments(conn: sqlite3.Connection, contact_wxid: str, to_ts: Optional[int] = None) -> MetricValue:
    if to_ts is not None:
        rows = conn.execute(
            "SELECT COUNT(*) AS cnt FROM moment_interactions WHERE user_id = ? AND timestamp <= ?",
            (contact_wxid, to_ts),
        ).fetchone()
    else:
        rows = conn.execute(
            "SELECT COUNT(*) AS cnt FROM moment_interactions WHERE user_id = ?",
            (contact_wxid,),
        ).fetchone()
    raw = rows["cnt"] if rows else 0
    max_val = 200
    normalized = math.log(1 + raw) / math.log(1 + max_val) if raw > 0 else 0.0

    return MetricValue(
        raw=raw,
        normalized=round(_clamp(normalized), 4),
        confidence=round(_confidence(raw), 2),
        sample_size=raw,
    )


def compute_msg_count(conn: sqlite3.Connection, contact_wxid: str, to_ts: Optional[int] = None) -> MetricValue:
    if to_ts is not None:
        rows = conn.execute(
            "SELECT COUNT(*) AS cnt FROM messages WHERE conversation_id = ? AND timestamp <= ?",
            (contact_wxid, to_ts),
        ).fetchone()
    else:
        rows = conn.execute(
            "SELECT COUNT(*) AS cnt FROM messages WHERE conversation_id = ?",
            (contact_wxid,),
        ).fetchone()
    raw = rows["cnt"] if rows else 0
    cap = 500
    # 对数归一化：高消息量边际递减（100条→0.74, 500条→1.0, 1000条→1.07→cap）
    normalized = _clamp(math.log(1 + raw) / math.log(1 + cap))

    return MetricValue(
        raw=raw,
        normalized=round(normalized, 4),
        confidence=round(_confidence(raw), 2),
        sample_size=raw,
    )


def compute_active_days(conn: sqlite3.Connection, contact_wxid: str, window_days: int = 30, ref_date: Optional[datetime] = None) -> MetricValue:
    now = ref_date or datetime.now()
    cutoff = int((now - timedelta(days=window_days)).timestamp())
    rows = conn.execute(
        "SELECT COUNT(DISTINCT DATE(timestamp, 'unixepoch', 'localtime')) AS cnt "
        "FROM messages WHERE conversation_id = ? AND timestamp >= ?",
        (contact_wxid, cutoff),
    ).fetchone()
    raw = rows["cnt"] if rows else 0
    # 对数归一化：活跃天数边际递减
    normalized = _clamp(math.log(1 + raw) / math.log(1 + window_days))

    return MetricValue(
        raw=raw,
        normalized=round(normalized, 4),
        confidence=round(_confidence(raw), 2),
        sample_size=raw,
    )


def compute_recent(conn: sqlite3.Connection, contact_wxid: str, recency_decay: int = 90, ref_date: Optional[datetime] = None) -> MetricValue:
    now_ts = int((ref_date or datetime.now()).timestamp())
    rows = conn.execute(
        "SELECT MAX(timestamp) AS last_ts FROM messages WHERE conversation_id = ?",
        (contact_wxid,),
    ).fetchone()

    if not rows or not rows["last_ts"]:
        return MetricValue(raw=999, normalized=0.0, confidence=0.0, sample_size=0)

    days_ago = (now_ts - rows["last_ts"]) / 86400
    normalized = _clamp(1.0 - days_ago / recency_decay)

    return MetricValue(
        raw=round(days_ago, 1),
        normalized=round(normalized, 4),
        confidence=1.0,
        sample_size=1,
    )


def compute_base_score(metrics: Metrics, weights: WeightsConfig, top_target: bool = False) -> float:
    """计算 base_score（不含 trend）。"""
    w = weights.as_dict()
    score = 0.0
    for name, mv in metrics.all_metrics().items():
        if name == "trend":
            continue
        weight = w.get(name, 0.0)
        score += mv.normalized * weight

    if top_target:
        score += 0.10

    return round(_clamp(score), 4)


def compute_signal_level(composite: float) -> str:
    for threshold, label in SIGNAL_THRESHOLDS:
        if composite >= threshold:
            return label
    return "无信号"


# ---------------------------------------------------------------------------
# 新增指标计算函数
# ---------------------------------------------------------------------------

# 正向情绪词（投入型回复）
_QUALITY_POSITIVE = [
    "哈哈哈", "笑死", "真的吗", "然后呢", "你怎么", "你觉得", "你是不是",
    "好可爱", "好好", "天哪", "厉害", "牛", "太有意思", "好搞笑",
    "讨厌", "哼", "切", "嘿嘿", "嘻嘻",
    "宝宝", "爱你", "想你", "抱抱", "亲亲", "么么", "宝贝", "好喜欢",
]
# 敷衍附和（精确匹配整条消息）
_QUALITY_NEGATIVE_EXACT = {"嗯", "哦", "好的", "是的", "嗯嗯", "确实", "好吧", "ok"}


def compute_fback_quality(conn: sqlite3.Connection, my_wxid: str, contact_wxid: str, window_days: int = 30, ref_date: Optional[datetime] = None) -> MetricValue:
    """回复质量 = 正向情绪词 + 追问比例 - 敷衍附和比例。"""
    now = ref_date or datetime.now()
    cutoff = int((now - timedelta(days=window_days)).timestamp())
    rows = conn.execute(
        "SELECT content FROM messages "
        "WHERE conversation_id = ? AND sender_id != ? AND timestamp >= ? AND type = 1 "
        "AND content IS NOT NULL",
        (contact_wxid, my_wxid, cutoff),
    ).fetchall()

    # 已标注贴纸
    import re as _re
    from engine.stickers import get_labeled_emotions
    labeled = get_labeled_emotions(conn)
    _md5_pattern = _re.compile(r'md5="([a-f0-9]{32})"')
    sticker_rows = conn.execute(
        "SELECT raw_content FROM messages "
        "WHERE conversation_id = ? AND sender_id != ? AND timestamp >= ? AND type = 47 "
        "AND raw_content IS NOT NULL",
        (contact_wxid, my_wxid, cutoff),
    ).fetchall()

    positive = 0
    engagement = 0
    negative = 0

    for r in rows:
        content = (r["content"] or "").strip()
        if any(kw in content for kw in _QUALITY_POSITIVE):
            positive += 1
        if "?" in content or "？" in content:
            engagement += 1
        if content in _QUALITY_NEGATIVE_EXACT:
            negative += 1

    # 贴纸情绪计入 positive/negative
    sticker_count = 0
    for r in sticker_rows:
        m = _md5_pattern.search(r["raw_content"] or "")
        if not m:
            continue
        md5 = m.group(1)
        emotion = labeled.get(md5, "")
        if not emotion:
            continue
        sticker_count += 1
        if emotion == "positive":
            positive += 1
        elif emotion == "negative":
            negative += 1

    total = len(rows) + sticker_count
    if total == 0:
        return MetricValue(raw=0.0, normalized=0.0, confidence=0.0, sample_size=0)

    raw = (positive * 2 + engagement - negative) / (total * 2)
    normalized = _clamp(raw)

    return MetricValue(
        raw=round(raw, 4),
        normalized=round(normalized, 4),
        confidence=round(_confidence(total), 2),
        sample_size=total,
    )


# 单条消息情绪评分
_EMOTION_HIGH = ["哈哈哈", "笑死", "嘻嘻", "好可爱", "讨厌", "哼", "嘿嘿", "噗",
                 "宝宝", "爱你", "想你", "抱抱", "亲亲", "么么", "宝贝", "笨蛋",
                 "傻瓜", "委屈", "难过", "开心", "好喜欢", "呜呜", "哇"]
_EMOTION_MID = ["呢", "吧", "嘛", "~", "！", "呀", "啊"]
_EMOTION_LOW = ["嗯嗯", "好的", "好吧", "确实", "嗯", "哦"]


def _score_message_emotion(content: str) -> float:
    """单条消息情绪得分（0.0-1.0）。"""
    content = (content or "").strip()
    if any(kw in content for kw in _EMOTION_HIGH):
        return 1.0
    if any(kw in content for kw in _EMOTION_MID):
        return 0.7
    if content in _EMOTION_LOW:
        return 0.3
    return 0.5


def compute_escore_volatility(conn: sqlite3.Connection, my_wxid: str, contact_wxid: str, window_days: int = 30, session_gap_hours: int = 4, ref_date: Optional[datetime] = None) -> MetricValue:
    """情绪波动 = 会话间情绪均值的标准差。波动大 = 有情绪投入。"""
    now = ref_date or datetime.now()
    cutoff = int((now - timedelta(days=window_days)).timestamp())
    rows = conn.execute(
        "SELECT sender_id, content, timestamp FROM messages "
        "WHERE conversation_id = ? AND timestamp >= ? AND type = 1 "
        "AND content IS NOT NULL ORDER BY timestamp",
        (contact_wxid, cutoff),
    ).fetchall()

    if len(rows) < 2:
        return MetricValue(raw=0.0, normalized=0.0, confidence=0.0, sample_size=len(rows))

    gap_seconds = session_gap_hours * 3600
    session_scores = []
    current_session = []

    for r in rows:
        if current_session and r["timestamp"] - current_session[-1]["timestamp"] > gap_seconds:
            session_scores.append(current_session)
            current_session = []
        current_session.append(r)
    if current_session:
        session_scores.append(current_session)

    session_means = []
    for session in session_scores:
        her_msgs = [m for m in session if m["sender_id"] != my_wxid]
        if len(her_msgs) < 2:
            continue
        scores = [_score_message_emotion(m["content"]) for m in her_msgs]
        session_means.append(sum(scores) / len(scores))

    if len(session_means) < 2:
        return MetricValue(raw=0.0, normalized=0.0, confidence=0.0, sample_size=len(session_means))

    mean = sum(session_means) / len(session_means)
    variance = sum((s - mean) ** 2 for s in session_means) / len(session_means)
    std = variance ** 0.5
    normalized = _clamp(std / 0.3)

    return MetricValue(
        raw=round(std, 4),
        normalized=round(normalized, 4),
        confidence=round(_confidence(len(session_means)), 2),
        sample_size=len(session_means),
    )


# 个人化问题关键词
_PERSONAL_Q_KEYWORDS = [
    "你觉得", "你喜欢", "你有没有", "你在干嘛", "你在哪", "你去哪",
    "你多大", "你哪里人", "你有女朋友", "你有对象", "你周末",
]
# 工具化问题关键词
_FUNCTIONAL_Q_KEYWORDS = ["怎么", "帮我", "能不能", "可以吗", "教我", "看看", "怎么办"]


def compute_qscore_detailed(conn: sqlite3.Connection, contact_wxid: str, window_days: int = 30, ref_date: Optional[datetime] = None) -> tuple[MetricValue, MetricValue]:
    """细分问题类型：个人化（IOI）和工具化（供养者信号）。"""
    now = ref_date or datetime.now()
    cutoff = int((now - timedelta(days=window_days)).timestamp())
    rows = conn.execute(
        "SELECT content FROM messages "
        "WHERE conversation_id = ? AND sender_id = ? AND timestamp >= ? AND type = 1 "
        "AND content IS NOT NULL",
        (contact_wxid, contact_wxid, cutoff),
    ).fetchall()

    if not rows:
        return MetricValue(raw=0.0, normalized=0.0, confidence=0.0, sample_size=0), \
               MetricValue(raw=0.0, normalized=0.0, confidence=0.0, sample_size=0)

    all_questions = 0
    personal = 0
    functional = 0

    for r in rows:
        content = r["content"] or ""
        is_question = "?" in content or "？" in content
        if not is_question:
            continue
        all_questions += 1
        is_functional = any(kw in content for kw in _FUNCTIONAL_Q_KEYWORDS)
        is_personal = any(kw in content for kw in _PERSONAL_Q_KEYWORDS)
        if is_functional:
            functional += 1
        elif is_personal:
            personal += 1

    total = len(rows)
    personal_raw = personal * 3.0 / total if total > 0 else 0
    functional_raw = functional * 3.0 / total if total > 0 else 0

    personal_mv = MetricValue(
        raw=round(personal_raw, 4),
        normalized=round(_clamp(personal_raw), 4),
        confidence=round(_confidence(total), 2),
        sample_size=personal,
    )
    functional_mv = MetricValue(
        raw=round(functional_raw, 4),
        normalized=round(_clamp(functional_raw), 4),
        confidence=round(_confidence(total), 2),
        sample_size=functional,
    )
    return personal_mv, functional_mv


_EXPLANATION_KEYWORDS = ["刚才", "刚刚", "在开会", "在忙", "不好意思", "抱歉", "没看到", "在上课", "在睡觉"]


def compute_rlatency_context(conn: sqlite3.Connection, my_wxid: str, contact_wxid: str, window_days: int = 30, session_gap_hours: int = 4, ref_date: Optional[datetime] = None) -> MetricValue:
    """慢回时有解释的比例。有解释 = 正向信号。"""
    now = ref_date or datetime.now()
    cutoff = int((now - timedelta(days=window_days)).timestamp())
    rows = conn.execute(
        "SELECT sender_id, content, timestamp FROM messages "
        "WHERE conversation_id = ? AND timestamp >= ? AND type = 1 "
        "AND content IS NOT NULL ORDER BY timestamp",
        (contact_wxid, cutoff),
    ).fetchall()

    if len(rows) < 2:
        return MetricValue(raw=0.5, normalized=0.5, confidence=0.0, sample_size=0)

    gap_seconds = session_gap_hours * 3600
    slow_her_msgs = []

    for i in range(1, len(rows)):
        prev = rows[i - 1]
        curr = rows[i]
        dt = curr["timestamp"] - prev["timestamp"]
        if dt <= 0 or dt > gap_seconds:
            continue
        # 她回复慢（> 1小时）且上一条是我发的
        if curr["sender_id"] != my_wxid and prev["sender_id"] == my_wxid and dt > 3600:
            slow_her_msgs.append(curr)

    if not slow_her_msgs:
        return MetricValue(raw=0.5, normalized=0.5, confidence=0.0, sample_size=0)

    explained = sum(
        1 for m in slow_her_msgs
        if any(kw in (m["content"] or "") for kw in _EXPLANATION_KEYWORDS)
    )
    raw = explained / len(slow_her_msgs)

    return MetricValue(
        raw=round(raw, 4),
        normalized=round(_clamp(raw), 4),
        confidence=round(_confidence(len(slow_her_msgs)), 2),
        sample_size=len(slow_her_msgs),
    )


def compute_neediness_penalty(conn: sqlite3.Connection, my_wxid: str, contact_wxid: str, session_gap_hours: int = 4, to_ts: Optional[int] = None) -> tuple[float, float, float]:
    """需求感惩罚系数。1.0 = 无惩罚，0.4 = 最低。
    
    返回: (penalty, volume_ratio, initiation_ratio)
    """
    if to_ts is not None:
        rows = conn.execute(
            "SELECT sender_id, timestamp FROM messages "
            "WHERE conversation_id = ? AND type = 1 AND timestamp <= ? ORDER BY timestamp",
            (contact_wxid, to_ts),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT sender_id, timestamp FROM messages "
            "WHERE conversation_id = ? AND type = 1 ORDER BY timestamp",
            (contact_wxid,),
        ).fetchall()

    if len(rows) < 2:
        return 1.0, 1.0, 0.5

    my_msgs = [r for r in rows if r["sender_id"] == my_wxid]
    her_msgs = [r for r in rows if r["sender_id"] != my_wxid]

    if not her_msgs:
        return 0.5, 1.0, 0.5

    # 1. 消息量比惩罚
    volume_ratio = len(my_msgs) / max(len(her_msgs), 1)
    volume_penalty = 1.0
    if volume_ratio > 1.3:
        excess = volume_ratio - 1.3
        volume_penalty = 1.0 - excess * 0.3
    volume_penalty = max(0.5, volume_penalty)

    # 2. 发起频率惩罚
    gap_seconds = session_gap_hours * 3600
    my_initiations = 0
    her_initiations = 0

    for i in range(1, len(rows)):
        dt = rows[i]["timestamp"] - rows[i - 1]["timestamp"]
        if dt > gap_seconds:
            if rows[i]["sender_id"] == my_wxid:
                my_initiations += 1
            else:
                her_initiations += 1

    total_initiations = my_initiations + her_initiations
    initiation_ratio = my_initiations / max(total_initiations, 1)

    initiation_penalty = 1.0
    if initiation_ratio > 0.6:
        excess = initiation_ratio - 0.6
        initiation_penalty = 1.0 - excess * 2.0
    initiation_penalty = max(0.4, initiation_penalty)

    penalty = round(min(volume_penalty, initiation_penalty), 4)
    return penalty, volume_ratio, initiation_ratio


def compute_msg_volume_trend(conn: sqlite3.Connection, contact_wxid: str, window_days: int = 30, ref_date: Optional[datetime] = None) -> MetricValue:
    """消息量变化率 = 最近7天消息数 / 前7天消息数。下降 = 负向信号。"""
    now_ts = int((ref_date or datetime.now()).timestamp())
    this_week_start = now_ts - 7 * 86400
    last_week_start = now_ts - 14 * 86400

    this_week = conn.execute(
        "SELECT COUNT(*) AS cnt FROM messages WHERE conversation_id = ? AND timestamp >= ? AND type = 1",
        (contact_wxid, this_week_start),
    ).fetchone()["cnt"]

    last_week = conn.execute(
        "SELECT COUNT(*) AS cnt FROM messages WHERE conversation_id = ? AND timestamp >= ? AND timestamp < ? AND type = 1",
        (contact_wxid, last_week_start, this_week_start),
    ).fetchone()["cnt"]

    if last_week == 0:
        if this_week == 0:
            return MetricValue(raw=1.0, normalized=0.5, confidence=0.0, sample_size=0)
        return MetricValue(raw=99.0, normalized=1.0, confidence=0.0, sample_size=this_week)

    raw = this_week / last_week  # 1.0=稳定, <1.0=下降, >1.0=增长
    # normalized: 比值越高越好。0.5→0.25, 1.0→0.5, 2.0→0.67
    # 但下降（<1.0）应该惩罚更重：0.3→0.15, 0.5→0.25, 0.7→0.35
    normalized = _clamp(raw / (1.0 + raw))
    sample = this_week + last_week

    return MetricValue(
        raw=round(raw, 4),
        normalized=round(normalized, 4),
        confidence=round(_confidence(sample), 2),
        sample_size=sample,
    )


def compute_latency_trend(conn: sqlite3.Connection, my_wxid: str, contact_wxid: str, window_days: int = 30, session_gap_hours: int = 4, ref_date: Optional[datetime] = None) -> MetricValue:
    """回复速度变化趋势 = 上周平均回复时间 / 本周平均回复时间。变慢 = 负向信号。"""
    now_ts = int((ref_date or datetime.now()).timestamp())
    this_week_start = now_ts - 7 * 86400
    last_week_start = now_ts - 14 * 86400
    gap_seconds = session_gap_hours * 3600

    def _avg_latency(rows: list[dict]) -> float:
        intervals = []
        for i in range(1, len(rows)):
            dt = rows[i]["timestamp"] - rows[i - 1]["timestamp"]
            if 0 < dt <= gap_seconds and rows[i - 1]["sender_id"] != rows[i]["sender_id"]:
                if rows[i]["sender_id"] != my_wxid:
                    intervals.append(dt)
        return sum(intervals) / len(intervals) if intervals else 0

    this_rows = conn.execute(
        "SELECT sender_id, timestamp FROM messages "
        "WHERE conversation_id = ? AND timestamp >= ? AND type = 1 ORDER BY timestamp",
        (contact_wxid, this_week_start),
    ).fetchall()

    last_rows = conn.execute(
        "SELECT sender_id, timestamp FROM messages "
        "WHERE conversation_id = ? AND timestamp >= ? AND timestamp < ? AND type = 1 ORDER BY timestamp",
        (contact_wxid, last_week_start, this_week_start),
    ).fetchall()

    this_avg = _avg_latency(this_rows)
    last_avg = _avg_latency(last_rows)

    if last_avg == 0 or this_avg == 0:
        return MetricValue(raw=1.0, normalized=0.5, confidence=0.0, sample_size=0)

    # raw = 上周/本周，>1 表示变快（好），<1 表示变慢（坏）
    raw = last_avg / this_avg
    normalized = _clamp(raw / (1.0 + raw))
    sample = len(this_rows) + len(last_rows)

    return MetricValue(
        raw=round(raw, 4),
        normalized=round(normalized, 4),
        confidence=round(_confidence(sample), 2),
        sample_size=sample,
    )


# ---------------------------------------------------------------------------
# 媒体参与度指标
# ---------------------------------------------------------------------------

def compute_media_engagement(conn: sqlite3.Connection, contact_wxid: str, my_wxid: str, window_days: int = 30, ref_date: Optional[datetime] = None) -> dict:
    """统计贴纸(type=47)和图片(type=3)的发送频率，提取贴纸 md5 词典。"""
    now = ref_date or datetime.now()
    cutoff = int((now - timedelta(days=window_days)).timestamp())

    # 她的总消息数
    her_total = conn.execute(
        "SELECT COUNT(*) AS cnt FROM messages WHERE conversation_id = ? "
        "AND sender_id != ? AND timestamp >= ?",
        (contact_wxid, my_wxid, cutoff),
    ).fetchone()["cnt"]

    if her_total == 0:
        return {"sticker_count": 0, "image_count": 0,
                "sticker_ratio": 0.0, "image_ratio": 0.0,
                "her_total": 0, "distinct_stickers": 0, "top_stickers": []}

    # 她发的贴纸数
    her_stickers = conn.execute(
        "SELECT COUNT(*) AS cnt FROM messages WHERE conversation_id = ? "
        "AND sender_id != ? AND timestamp >= ? AND type = 47",
        (contact_wxid, my_wxid, cutoff),
    ).fetchone()["cnt"]

    # 她发的图片数
    her_images = conn.execute(
        "SELECT COUNT(*) AS cnt FROM messages WHERE conversation_id = ? "
        "AND sender_id != ? AND timestamp >= ? AND type = 3",
        (contact_wxid, my_wxid, cutoff),
    ).fetchone()["cnt"]

    # 提取她的贴纸 md5 词典
    import re as _re
    _md5_pattern = _re.compile(r'md5="([a-f0-9]{32})"')
    sticker_rows = conn.execute(
        "SELECT raw_content FROM messages WHERE conversation_id = ? "
        "AND sender_id != ? AND timestamp >= ? AND type = 47 "
        "AND raw_content IS NOT NULL",
        (contact_wxid, my_wxid, cutoff),
    ).fetchall()

    sticker_vocab: dict[str, int] = {}
    for r in sticker_rows:
        m = _md5_pattern.search(r["raw_content"] or "")
        if m:
            md5 = m.group(1)
            sticker_vocab[md5] = sticker_vocab.get(md5, 0) + 1

    # 镜像检测用更长的窗口（180天），因为镜像信号需要时间积累
    mimicry_cutoff = int((datetime.now() - timedelta(days=180)).timestamp())

    # 我的贴纸 md5 词典（全局，跨所有会话，180天）
    my_sticker_rows = conn.execute(
        "SELECT DISTINCT raw_content FROM messages "
        "WHERE sender_id = ? AND timestamp >= ? AND type = 47 "
        "AND raw_content IS NOT NULL",
        (my_wxid, mimicry_cutoff),
    ).fetchall()

    my_sticker_set: set[str] = set()
    for r in my_sticker_rows:
        m = _md5_pattern.search(r["raw_content"] or "")
        if m:
            my_sticker_set.add(m.group(1))

    # 她的贴纸也用 180 天窗口做镜像比较
    her_sticker_rows_m = conn.execute(
        "SELECT raw_content FROM messages WHERE conversation_id = ? "
        "AND sender_id != ? AND timestamp >= ? AND type = 47 "
        "AND raw_content IS NOT NULL",
        (contact_wxid, my_wxid, mimicry_cutoff),
    ).fetchall()

    her_sticker_set_m: set[str] = set()
    for r in her_sticker_rows_m:
        m = _md5_pattern.search(r["raw_content"] or "")
        if m:
            her_sticker_set_m.add(m.group(1))

    # 镜像检测：她的贴纸中有多少是我用过的（180天窗口）
    mimicry_set = her_sticker_set_m & my_sticker_set
    mimicry_types = len(mimicry_set)
    mimicry_ratio = mimicry_types / len(her_sticker_set_m) if her_sticker_set_m else 0.0

    # 镜像强度判断
    if mimicry_types >= 3 and mimicry_ratio >= 0.3:
        mimicry_signal = f"强镜像：{mimicry_types}种贴纸重叠({mimicry_ratio:.0%})"
    elif mimicry_types >= 2:
        mimicry_signal = f"中镜像：{mimicry_types}种贴纸重叠({mimicry_ratio:.0%})"
    elif mimicry_types >= 1:
        mimicry_signal = f"弱镜像：{mimicry_types}种贴纸重叠"
    else:
        mimicry_signal = ""

    # 最常用的贴纸（最多 5 个）
    top_stickers = sorted(sticker_vocab.items(), key=lambda x: -x[1])[:5]

    return {
        "sticker_count": her_stickers,
        "image_count": her_images,
        "sticker_ratio": round(her_stickers / her_total, 4),
        "image_ratio": round(her_images / her_total, 4),
        "her_total": her_total,
        "distinct_stickers": len(sticker_vocab),
        "top_stickers": [{"md5": md5[:12], "count": cnt} for md5, cnt in top_stickers],
        "mimicry_types": mimicry_types,
        "mimicry_ratio": round(mimicry_ratio, 4),
        "mimicry_signal": mimicry_signal,
    }


# ---------------------------------------------------------------------------
# 动态时间维度指标（signal_flags，不参与 composite 加权）
# ---------------------------------------------------------------------------

def compute_session_recency(conn: sqlite3.Connection, contact_wxid: str, session_gap_hours: int = 4, ref_date: Optional[datetime] = None) -> dict:
    """最近一次有效会话距今天数。越小 = 越近 = 越好。"""
    now_ts = int((ref_date or datetime.now()).timestamp())
    rows = conn.execute(
        "SELECT timestamp FROM messages WHERE conversation_id = ? AND type = 1 "
        "ORDER BY timestamp DESC",
        (contact_wxid,),
    ).fetchall()

    if not rows:
        return {"days_ago": 999, "label": "无消息"}

    gap_seconds = session_gap_hours * 3600
    # 找最近一个会话的起始时间（从最新消息往前找会话边界）
    latest_ts = rows[0]["timestamp"]
    session_start_ts = latest_ts
    for i in range(1, len(rows)):
        dt = rows[i - 1]["timestamp"] - rows[i]["timestamp"]
        if dt > gap_seconds:
            break
        session_start_ts = rows[i]["timestamp"]

    days_ago = (now_ts - latest_ts) / 86400

    if days_ago < 1:
        label = "今天活跃"
    elif days_ago < 3:
        label = f"{int(days_ago)}天前"
    elif days_ago < 7:
        label = f"{int(days_ago)}天前（本周）"
    elif days_ago < 30:
        label = f"{int(days_ago)}天前（本月）"
    elif days_ago < 90:
        label = f"{int(days_ago)}天前（近期断联）"
    else:
        label = f"{int(days_ago)}天前（长期断联）"

    return {
        "days_ago": round(days_ago, 1),
        "session_start": session_start_ts,
        "latest_ts": latest_ts,
        "label": label,
    }


def compute_momentum(conn: sqlite3.Connection, contact_wxid: str, my_wxid: str, session_gap_hours: int = 4, ref_date: Optional[datetime] = None) -> dict:
    """动量 = 最近7天 vs 前7天的多维变化。用于识别爆发/降温。"""
    now_ts = int((ref_date or datetime.now()).timestamp())
    this_start = now_ts - 7 * 86400
    last_start = now_ts - 14 * 86400

    def _stats(start: int, end: int) -> dict:
        rows = conn.execute(
            "SELECT sender_id, content, timestamp FROM messages "
            "WHERE conversation_id = ? AND timestamp >= ? AND timestamp < ? AND type = 1 "
            "ORDER BY timestamp",
            (contact_wxid, start, end),
        ).fetchall()
        total = len(rows)
        her = sum(1 for r in rows if r["sender_id"] != my_wxid)
        days = len(set(datetime.fromtimestamp(r["timestamp"]).strftime("%Y-%m-%d") for r in rows)) if rows else 0
        # 她发起的会话数
        gap = session_gap_hours * 3600
        her_init = sum(
            1 for i in range(1, len(rows))
            if rows[i]["timestamp"] - rows[i - 1]["timestamp"] > gap
            and rows[i]["sender_id"] != my_wxid
        )
        return {"total": total, "her": her, "days": days, "her_init": her_init}

    this_week = _stats(this_start, now_ts)
    last_week = _stats(last_start, this_start)

    # 计算变化率
    def _ratio(a: float, b: float) -> float:
        if b == 0:
            return 99.0 if a > 0 else 1.0
        return a / b

    total_ratio = _ratio(this_week["total"], last_week["total"])
    her_ratio = _ratio(this_week["her"], last_week["her"])
    days_ratio = _ratio(this_week["days"], last_week["days"])

    # 综合动量：三个维度的几何平均
    import math
    vals = [total_ratio, her_ratio, days_ratio]
    geo_mean = math.prod(max(0.01, v) for v in vals) ** (1.0 / len(vals))

    # 判断方向
    if geo_mean > 1.5 and this_week["total"] > 20:
        direction = "爆发上升"
    elif geo_mean > 1.2:
        direction = "温和上升"
    elif geo_mean < 0.5 and last_week["total"] > 20:
        direction = "急剧降温"
    elif geo_mean < 0.8:
        direction = "缓慢降温"
    else:
        direction = "稳定"

    return {
        "this_week": this_week,
        "last_week": last_week,
        "total_ratio": round(total_ratio, 2),
        "her_ratio": round(her_ratio, 2),
        "days_ratio": round(days_ratio, 2),
        "momentum": round(geo_mean, 2),
        "direction": direction,
    }


def compute_initiation_source(conn: sqlite3.Connection, contact_wxid: str, my_wxid: str, session_gap_hours: int = 4, ref_date: Optional[datetime] = None) -> dict:
    """最近一次会话是谁发起的。她发起 = 强正向信号。"""
    now_ts = int((ref_date or datetime.now()).timestamp())
    rows = conn.execute(
        "SELECT sender_id, timestamp FROM messages "
        "WHERE conversation_id = ? AND type = 1 ORDER BY timestamp DESC",
        (contact_wxid,),
    ).fetchall()

    if not rows:
        return {"initiator": "none", "label": "无消息"}

    gap_seconds = session_gap_hours * 3600
    # 找最近一个会话的边界
    session_msgs = [rows[0]]
    for i in range(1, len(rows)):
        dt = rows[i - 1]["timestamp"] - rows[i]["timestamp"]
        if dt > gap_seconds:
            break
        session_msgs.append(rows[i])

    # 会话内最早的消息 = 发起者（消息已按 DESC 排序，最后一条是最早的）
    initiator_msg = session_msgs[-1]
    initiator = "her" if initiator_msg["sender_id"] != my_wxid else "me"

    # 会话距今多久
    days_ago = (now_ts - rows[0]["timestamp"]) / 86400

    # 判断信号强度
    if initiator == "her" and days_ago < 3:
        signal = "强正向：她最近主动发起"
    elif initiator == "her" and days_ago < 7:
        signal = "正向：她本周主动发起"
    elif initiator == "her":
        signal = "弱正向：她曾主动发起"
    elif days_ago < 3:
        signal = "中性：你最近主动"
    else:
        signal = "中性"

    return {
        "initiator": initiator,
        "session_size": len(session_msgs),
        "days_ago": round(days_ago, 1),
        "signal": signal,
    }


def classify_interaction_pattern(metrics: Metrics) -> str:
    """判断互动模式：lover / provider / neutral。"""
    fback = metrics.fback.normalized
    qsp = metrics.qscore_personal.normalized
    qsf = metrics.qscore_functional.normalized
    neediness = metrics.neediness_penalty
    volatility = metrics.escore_volatility.normalized

    if fback > 0.4 and qsp > 0.3 and neediness > 0.7:
        return "lover"
    if qsf > qsp and neediness < 0.7 and volatility < 0.2:
        return "provider"
    return "neutral"


# ---------------------------------------------------------------------------
# Wiki 衍生指标（v2）
#
# 设计依据（来源 wiki 实体页）：
#   - IOI（兴趣指标）：主动发起=强IOI；看密度趋势不看单个信号
#   - 窗口识别：延续话题=好感窗口；简短/不延续=防感窗口
#   - 信号质量（costly signal vs cheap talk）：看行为不看语言
#   - 等值心态/需求感控制：不对等=需求感暴露
#   - 情绪判断九分类：综合速度+长度+表情+主动
#   - 友谊区：只聊日常不聊情感=友谊区信号
# ---------------------------------------------------------------------------

# 敷衍终结词（Grice 量的准则违反 → 信号质量 cheap）
_TERMINATOR_EXACT = {"嗯", "哦", "好", "好的", "是的", "嗯嗯", "哦哦", "好吧", "ok", "OK", "行", "收到", "了解"}
# 日常话题关键词（友谊区信号：只聊日常不聊情感）
_DAILY_TOPICS = ["吃", "睡", "上班", "下班", "加班", "天气", "公交", "地铁", "作业", "考试",
                 "课件", "老师", "外卖", "买", "快递", "周末", "放假", "回家"]
# 情感话题关键词（好感窗口信号：愿意进入情绪区）
_EMOTIONAL_TOPICS = ["想", "喜欢", "开心", "难过", "委屈", "生气", "害怕", "担心", "感觉",
                     "心情", "梦想", "未来", "家里", "小时候", "故事", "秘密", "抱", "亲"]


def compute_her_initiation_rate(conn: sqlite3.Connection, my_wxid: str, contact_wxid: str,
                                 window_days: int = 30, session_gap_hours: int = 4,
                                 ref_date: Optional[datetime] = None) -> MetricValue:
    """她主动开启新会话的比例。

    Wiki 依据：IOI 分级中"主动发消息给你=强IOI"。
    一个新 session = 与上一条消息间隔 > session_gap_hours。
    她主动 = session 的第一条消息来自她。
    """
    now = ref_date or datetime.now()
    cutoff = int((now - timedelta(days=window_days)).timestamp())
    rows = conn.execute(
        "SELECT sender_id, timestamp FROM messages "
        "WHERE conversation_id = ? AND type = 1 AND timestamp >= ? ORDER BY timestamp",
        (contact_wxid, cutoff),
    ).fetchall()

    if len(rows) < 2:
        return MetricValue(raw=0.0, normalized=0.0, confidence=0.0, sample_size=len(rows))

    gap_seconds = session_gap_hours * 3600
    sessions = []
    current_session_start = rows[0]
    for i in range(1, len(rows)):
        dt = rows[i]["timestamp"] - rows[i - 1]["timestamp"]
        if dt > gap_seconds:
            sessions.append(current_session_start)
            current_session_start = rows[i]
    sessions.append(current_session_start)

    if len(sessions) < 2:
        return MetricValue(raw=0.0, normalized=0.0, confidence=0.0, sample_size=len(sessions))

    her_initiations = sum(1 for s in sessions if s["sender_id"] != my_wxid)
    rate = her_initiations / len(sessions)
    return MetricValue(
        raw=round(rate, 4),
        normalized=round(_clamp(rate * 1.5), 4),
        confidence=round(_confidence(len(sessions)), 2),
        sample_size=len(sessions),
    )


def compute_topic_continuation(conn: sqlite3.Connection, my_wxid: str, contact_wxid: str,
                                window_days: int = 30, ref_date: Optional[datetime] = None) -> MetricValue:
    """她延续话题的比例。

    Wiki 依据：窗口识别中"主动找话题延续对话=好感窗口"；Grice 量的准则违反="嗯嗯"=终结。
    延续信号：回复长度>5字 / 包含问句 / 包含情绪词；
    终结信号：回复为敷衍终结词（"嗯""哦""好"）。
    """
    now = ref_date or datetime.now()
    cutoff = int((now - timedelta(days=window_days)).timestamp())
    rows = conn.execute(
        "SELECT content FROM messages "
        "WHERE conversation_id = ? AND sender_id != ? AND timestamp >= ? AND type = 1 "
        "AND content IS NOT NULL",
        (contact_wxid, my_wxid, cutoff),
    ).fetchall()

    if not rows:
        return MetricValue(raw=0.0, normalized=0.0, confidence=0.0, sample_size=0)

    continuation = 0
    termination = 0
    for r in rows:
        content = (r["content"] or "").strip()
        if content in _TERMINATOR_EXACT:
            termination += 1
        elif len(content) > 5 or "?" in content or "？" in content:
            continuation += 1
        elif any(w in content for w in _EMOTIONAL_TOPICS):
            continuation += 1
        else:
            termination += 1

    total = continuation + termination
    if total == 0:
        return MetricValue(raw=0.0, normalized=0.0, confidence=0.0, sample_size=0)

    rate = continuation / total
    return MetricValue(
        raw=round(rate, 4),
        normalized=round(rate, 4),
        confidence=round(_confidence(total), 2),
        sample_size=total,
    )


def compute_reply_quality(conn: sqlite3.Connection, my_wxid: str, contact_wxid: str,
                           window_days: int = 30, ref_date: Optional[datetime] = None) -> MetricValue:
    """回复质量分（costly signal vs cheap talk）。

    Wiki 依据：信号质量理论——看行为不看语言。
    costly：长回复（>10字）、包含问句、包含情感词、包含表情包；
    cheap：单字/敷衍词、信息量为零。
    """
    now = ref_date or datetime.now()
    cutoff = int((now - timedelta(days=window_days)).timestamp())
    rows = conn.execute(
        "SELECT content FROM messages "
        "WHERE conversation_id = ? AND sender_id != ? AND timestamp >= ? AND type = 1 "
        "AND content IS NOT NULL",
        (contact_wxid, my_wxid, cutoff),
    ).fetchall()

    if not rows:
        return MetricValue(raw=0.0, normalized=0.0, confidence=0.0, sample_size=0)

    quality_sum = 0.0
    for r in rows:
        content = (r["content"] or "").strip()
        score = 0.0
        if len(content) >= 15:
            score += 0.4
        elif len(content) >= 5:
            score += 0.2
        if "?" in content or "？" in content:
            score += 0.3
        if any(w in content for w in _EMOTIONAL_TOPICS):
            score += 0.2
        if content in _TERMINATOR_EXACT:
            score = 0.0
        quality_sum += min(1.0, score)

    avg_quality = quality_sum / len(rows)
    return MetricValue(
        raw=round(avg_quality, 4),
        normalized=round(avg_quality, 4),
        confidence=round(_confidence(len(rows)), 2),
        sample_size=len(rows),
    )


def compute_session_balance(conn: sqlite3.Connection, my_wxid: str, contact_wxid: str,
                             window_days: int = 30, session_gap_hours: int = 4,
                             ref_date: Optional[datetime] = None) -> MetricValue:
    """会话对等性（等值心态）。

    Wiki 依据：需求感控制/等值心态——"她的态度就是你的态度"。
    不对等（我远多于她）= 需求感暴露。
    计算：1 - |my_msgs - her_msgs| / max(my_msgs, her_msgs)，按 session 聚合后取平均。
    """
    now = ref_date or datetime.now()
    cutoff = int((now - timedelta(days=window_days)).timestamp())
    rows = conn.execute(
        "SELECT sender_id, timestamp FROM messages "
        "WHERE conversation_id = ? AND type = 1 AND timestamp >= ? ORDER BY timestamp",
        (contact_wxid, cutoff),
    ).fetchall()

    if len(rows) < 2:
        return MetricValue(raw=0.0, normalized=0.0, confidence=0.0, sample_size=len(rows))

    gap_seconds = session_gap_hours * 3600
    sessions = []
    current = [rows[0]]
    for i in range(1, len(rows)):
        dt = rows[i]["timestamp"] - rows[i - 1]["timestamp"]
        if dt > gap_seconds:
            sessions.append(current)
            current = [rows[i]]
        else:
            current.append(rows[i])
    sessions.append(current)

    balances = []
    for s in sessions:
        my_count = sum(1 for r in s if r["sender_id"] == my_wxid)
        her_count = sum(1 for r in s if r["sender_id"] != my_wxid)
        total = my_count + her_count
        if total < 2:
            continue
        diff = abs(my_count - her_count)
        balance = 1.0 - diff / max(my_count, her_count)
        balances.append(balance)

    if not balances:
        return MetricValue(raw=0.0, normalized=0.0, confidence=0.0, sample_size=0)

    avg_balance = sum(balances) / len(balances)
    return MetricValue(
        raw=round(avg_balance, 4),
        normalized=round(avg_balance, 4),
        confidence=round(_confidence(len(balances)), 2),
        sample_size=len(balances),
    )


def compute_emotional_temperature(conn: sqlite3.Connection, my_wxid: str, contact_wxid: str,
                                   window_days: int = 30, session_gap_hours: int = 4,
                                   ref_date: Optional[datetime] = None) -> MetricValue:
    """情绪温度（情绪判断九分类的连续化版本）。

    Wiki 依据：情绪判断——综合回复速度、长度、表情使用、主动度。
    输出 0-1 连续值：0=冰点，0.5=平淡，1=真好。
    """
    now = ref_date or datetime.now()
    cutoff = int((now - timedelta(days=window_days)).timestamp())
    rows = conn.execute(
        "SELECT sender_id, timestamp, content FROM messages "
        "WHERE conversation_id = ? AND type = 1 AND timestamp >= ? ORDER BY timestamp",
        (contact_wxid, cutoff),
    ).fetchall()

    if len(rows) < 2:
        return MetricValue(raw=0.0, normalized=0.0, confidence=0.0, sample_size=len(rows))

    gap_seconds = session_gap_hours * 3600
    her_replies = []
    for i in range(1, len(rows)):
        prev = rows[i - 1]
        curr = rows[i]
        if curr["sender_id"] == my_wxid:
            continue
        if prev["sender_id"] != my_wxid:
            continue
        dt = curr["timestamp"] - prev["timestamp"]
        if dt <= 0 or dt > gap_seconds:
            continue
        her_replies.append({"dt": dt, "content": curr["content"] or ""})

    if not her_replies:
        return MetricValue(raw=0.0, normalized=0.0, confidence=0.0, sample_size=0)

    temp_sum = 0.0
    for r in her_replies:
        score = 0.0
        # 速度分：<10分钟=0.4，<1小时=0.25，<4小时=0.1
        if r["dt"] < 600:
            score += 0.4
        elif r["dt"] < 3600:
            score += 0.25
        elif r["dt"] < gap_seconds:
            score += 0.1
        # 长度分：>15字=0.3，>5字=0.15
        content = r["content"].strip()
        if len(content) >= 15:
            score += 0.3
        elif len(content) >= 5:
            score += 0.15
        # 情感分：包含情感词=0.3
        if any(w in content for w in _EMOTIONAL_TOPICS):
            score += 0.3
        # 敷衍惩罚
        if content in _TERMINATOR_EXACT:
            score = 0.0
        temp_sum += min(1.0, score)

    avg_temp = temp_sum / len(her_replies)
    return MetricValue(
        raw=round(avg_temp, 4),
        normalized=round(avg_temp, 4),
        confidence=round(_confidence(len(her_replies)), 2),
        sample_size=len(her_replies),
    )


def compute_friendzone_risk(conn: sqlite3.Connection, my_wxid: str, contact_wxid: str,
                             window_days: int = 30, ref_date: Optional[datetime] = None) -> MetricValue:
    """友谊区风险（反向指标，normalized 越高=风险越高）。

    Wiki 依据：友谊区——只聊日常不聊情感、提到别的男人、叫"哥们/兄弟"。
    计算：日常话题比例 - 情感话题比例（clamp 到 [0,1]）。
    """
    now = ref_date or datetime.now()
    cutoff = int((now - timedelta(days=window_days)).timestamp())
    rows = conn.execute(
        "SELECT content FROM messages "
        "WHERE conversation_id = ? AND sender_id != ? AND timestamp >= ? AND type = 1 "
        "AND content IS NOT NULL",
        (contact_wxid, my_wxid, cutoff),
    ).fetchall()

    if not rows:
        return MetricValue(raw=0.0, normalized=0.0, confidence=0.0, sample_size=0)

    daily_count = 0
    emotional_count = 0
    for r in rows:
        content = (r["content"] or "")
        if any(w in content for w in _DAILY_TOPICS):
            daily_count += 1
        if any(w in content for w in _EMOTIONAL_TOPICS):
            emotional_count += 1

    total = len(rows)
    daily_ratio = daily_count / total
    emotional_ratio = emotional_count / total
    # 风险 = 日常占比高且情感占比低
    risk = _clamp(daily_ratio - emotional_ratio + 0.5)
    return MetricValue(
        raw=round(daily_ratio - emotional_ratio, 4),
        normalized=round(risk, 4),
        confidence=round(_confidence(total), 2),
        sample_size=total,
        extra={"daily_ratio": round(daily_ratio, 4), "emotional_ratio": round(emotional_ratio, 4)},
    )


def _linear_slope(points: list[tuple[int, float]]) -> float:
    """简单线性回归斜率。points = [(x, y), ...]，x 为序号。"""
    n = len(points)
    if n < 2:
        return 0.0
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    x_mean = sum(xs) / n
    y_mean = sum(ys) / n
    num = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
    den = sum((x - x_mean) ** 2 for x in xs)
    if den == 0:
        return 0.0
    return num / den


def compute_composite_slope(conn: sqlite3.Connection, config: Config, contact_wxid: str,
                            contact_name: str = "", ref_date: Optional[datetime] = None,
                            sample_points: int = 3, sample_interval_days: int = 7) -> MetricValue:
    """计算 composite 趋势斜率。

    在 ref_date 之前按固定间隔取多个时间点，计算每个点的 composite，
    做线性回归得到斜率。

    Wiki 依据：IOI 兴趣指标——"看密度和趋势，不看单个信号"。
    回测验证：成功案例斜率 > +0.005，失败案例 ≈ 0 或负。
    """
    now = ref_date or datetime.now()
    points = []
    history_details = []

    for i in range(sample_points):
        pt = now - timedelta(days=i * sample_interval_days)
        to_ts = int(pt.timestamp())
        m = compute_metrics_for_contact(conn, config, contact_wxid, contact_name,
                                        ref_date=pt, to_ts=to_ts, compute_slope=False)
        day_offset = -i * sample_interval_days
        points.append((day_offset, m.composite))
        history_details.append({
            "day_offset": day_offset,
            "composite": round(m.composite, 4),
            "msg_count": m.msg_count.raw,
        })

    if len(points) < 2:
        return MetricValue(raw=0.0, normalized=0.5, confidence=0.0, sample_size=0)

    slope = _linear_slope(points)
    valid_points = sum(1 for p in points if p[1] > 0)

    if valid_points < 2:
        return MetricValue(raw=0.0, normalized=0.5, confidence=0.0, sample_size=valid_points)

    normalized = _clamp(0.5 + slope * 25)

    if slope > 0.005:
        trend_label = "上升"
    elif slope < -0.005:
        trend_label = "下降"
    else:
        trend_label = "平稳"

    return MetricValue(
        raw=round(slope, 6),
        normalized=round(normalized, 4),
        confidence=round(_confidence(valid_points * 10), 2),
        sample_size=valid_points,
        extra={
            "trend_label": trend_label,
            "sample_interval_days": sample_interval_days,
            "history": history_details,
        },
    )


def _compute_semantic_indicators(
    conn: sqlite3.Connection, config: Config, contact_wxid: str,
    window_days: int = 30, ref_date: Optional[datetime] = None,
    source: str = "rule",
) -> tuple[MetricValue, MetricValue, MetricValue]:
    """计算语义指标（flirt/invitation/emotion_balance）。

    双参考机制：source="rule" 用规则baseline（快约0.1s），"macbert" 用模型（慢约2-5s）。
    回测验证：flirt 和 invitation 是区分成功/失败的最强指标。

    Returns:
        (semantic_flirt, semantic_invitation, semantic_emotion_balance)
    """
    from engine.analyzers.semantic import (
        _build_turns, _extract_windows, _classify_window_onnx, _classify_window_rule,
        _compute_emotion_balance, LABELS,
    )

    if ref_date:
        end_ts = int(ref_date.timestamp())
        cutoff = int((ref_date - timedelta(days=window_days)).timestamp())
    else:
        end_ts = int(datetime.now().timestamp())
        cutoff = int((datetime.now() - timedelta(days=window_days)).timestamp())

    rows = conn.execute(
        "SELECT id, sender_id, content, timestamp, type "
        "FROM messages WHERE conversation_id = ? AND type = 1 "
        "AND timestamp >= ? AND timestamp <= ? "
        "ORDER BY timestamp ASC",
        (contact_wxid, cutoff, end_ts),
    ).fetchall()

    messages = []
    for row in rows:
        sender_id = row["sender_id"] or ""
        messages.append({
            "id": row["id"],
            "sender_id": sender_id,
            "is_mine": sender_id == config.my_wxid,
            "content": row["content"] or "",
            "timestamp": row["timestamp"],
        })

    empty_flirt = MetricValue(raw=0.0, normalized=0.0, confidence=0.0, sample_size=0)
    empty_invitation = MetricValue(raw=0.0, normalized=0.0, confidence=0.0, sample_size=0)
    empty_emo = MetricValue(raw=0.5, normalized=0.5, confidence=0.0, sample_size=0)

    if len(messages) < 5:
        return empty_flirt, empty_invitation, empty_emo

    turns = _build_turns(messages, config.my_wxid)
    windows_turns = _extract_windows(turns)

    if not windows_turns:
        return empty_flirt, empty_invitation, empty_emo

    window_scores = []
    for wt in windows_turns:
        if source == "macbert":
            scores, _ = _classify_window_onnx(wt)
        else:
            scores, _ = _classify_window_rule(wt)
        window_scores.append(scores)

    recent = window_scores[-3:] if len(window_scores) >= 3 else window_scores
    avg_scores = {}
    for label in LABELS:
        vals = [w.get(label, 0) for w in recent]
        avg_scores[label] = sum(vals) / len(vals)

    flirt_raw = avg_scores.get("flirt", 0)
    invitation_raw = avg_scores.get("invitation", 0)
    emo_balance = _compute_emotion_balance(avg_scores)
    conf = min(1.0, len(window_scores) / 10.0)

    flirt_mv = MetricValue(
        raw=round(flirt_raw, 2), normalized=round(flirt_raw / 9.0, 4),
        confidence=conf, sample_size=len(window_scores),
    )
    invitation_mv = MetricValue(
        raw=round(invitation_raw, 2), normalized=round(invitation_raw / 9.0, 4),
        confidence=conf, sample_size=len(window_scores),
    )
    emo_mv = MetricValue(
        raw=round(emo_balance, 3), normalized=round(emo_balance, 4),
        confidence=conf, sample_size=len(window_scores),
    )
    return flirt_mv, invitation_mv, emo_mv


def compute_metrics_for_contact(conn: sqlite3.Connection, config: Config, contact_wxid: str, contact_name: str = "",
                                top_target: bool = False, prev_base_score: Optional[float] = None,
                                ref_date: Optional[datetime] = None, to_ts: Optional[int] = None,
                                compute_slope: bool = False, semantic_source: str = "rule") -> Metrics:
    """为单个联系人计算全部指标。

    compute_slope=True 时额外计算 composite 趋势斜率（3x 计算量，单联系人分析/回测时启用）。
    semantic_source: 语义指标来源 "rule"（默认，快）或 "macbert"（模型，慢但准确）。
    """
    my_wxid = config.my_wxid
    mc = config.metrics

    # 原始指标
    fback = compute_fback(conn, my_wxid, contact_wxid, mc.active_days_window, ref_date=ref_date)
    rlatency = compute_rlatency(conn, my_wxid, contact_wxid, mc.session_gap_hours, to_ts=to_ts)
    qscore = _compute_her_ratio(conn, contact_wxid, "?", mc.active_days_window, ref_date=ref_date)
    escore = _compute_emotion_ratio(conn, my_wxid, contact_wxid, mc.active_days_window, ref_date=ref_date)
    moments = compute_moments(conn, contact_wxid, to_ts=to_ts)
    msg_count = compute_msg_count(conn, contact_wxid, to_ts=to_ts)
    active_days = compute_active_days(conn, contact_wxid, mc.active_days_window, ref_date=ref_date)
    recent = compute_recent(conn, contact_wxid, mc.recency_decay, ref_date=ref_date)

    # 新增指标
    fback_quality = compute_fback_quality(conn, my_wxid, contact_wxid, mc.active_days_window, ref_date=ref_date)
    escore_volatility = compute_escore_volatility(conn, my_wxid, contact_wxid,
                                                   mc.active_days_window, mc.session_gap_hours, ref_date=ref_date)
    qscore_personal, qscore_functional = compute_qscore_detailed(conn, contact_wxid, mc.active_days_window, ref_date=ref_date)
    rlatency_context = compute_rlatency_context(conn, my_wxid, contact_wxid,
                                                 mc.active_days_window, mc.session_gap_hours, ref_date=ref_date)
    neediness_result = compute_neediness_penalty(conn, my_wxid, contact_wxid, mc.session_gap_hours, to_ts=to_ts)
    neediness_penalty, volume_ratio, initiation_ratio = neediness_result
    msg_volume_trend = compute_msg_volume_trend(conn, contact_wxid, mc.active_days_window, ref_date=ref_date)
    latency_trend = compute_latency_trend(conn, my_wxid, contact_wxid,
                                           mc.active_days_window, mc.session_gap_hours, ref_date=ref_date)

    # Wiki 衍生指标（v2）
    her_initiation_rate = compute_her_initiation_rate(conn, my_wxid, contact_wxid,
                                                       mc.active_days_window, mc.session_gap_hours, ref_date=ref_date)
    topic_continuation = compute_topic_continuation(conn, my_wxid, contact_wxid,
                                                     mc.active_days_window, ref_date=ref_date)
    reply_quality = compute_reply_quality(conn, my_wxid, contact_wxid,
                                           mc.active_days_window, ref_date=ref_date)
    session_balance = compute_session_balance(conn, my_wxid, contact_wxid,
                                               mc.active_days_window, mc.session_gap_hours, ref_date=ref_date)
    emotional_temperature = compute_emotional_temperature(conn, my_wxid, contact_wxid,
                                                           mc.active_days_window, mc.session_gap_hours, ref_date=ref_date)
    friendzone_risk = compute_friendzone_risk(conn, my_wxid, contact_wxid,
                                               mc.active_days_window, ref_date=ref_date)

    # 语义指标（Layer 2，来自 MacBERT/规则双参考）
    semantic_flirt, semantic_invitation, semantic_emotion_balance = _compute_semantic_indicators(
        conn, config, contact_wxid, mc.active_days_window, ref_date=ref_date, source=semantic_source,
    )

    sid = contact_wxid[-6:] if len(contact_wxid) >= 6 else contact_wxid
    metrics = Metrics(
        _id=f"{contact_name or contact_wxid}_{sid}_metrics",
        fback=fback, rlatency=rlatency, qscore=qscore, escore=escore,
        moments=moments, msg_count=msg_count, active_days=active_days, recent=recent,
        fback_quality=fback_quality, escore_volatility=escore_volatility,
        qscore_personal=qscore_personal, qscore_functional=qscore_functional,
        rlatency_context=rlatency_context,
        msg_volume_trend=msg_volume_trend, latency_trend=latency_trend,
        her_initiation_rate=her_initiation_rate,
        topic_continuation=topic_continuation,
        reply_quality=reply_quality,
        session_balance=session_balance,
        emotional_temperature=emotional_temperature,
        friendzone_risk=friendzone_risk,
        semantic_flirt=semantic_flirt,
        semantic_invitation=semantic_invitation,
        semantic_emotion_balance=semantic_emotion_balance,
        neediness_penalty=neediness_penalty,
        volume_ratio=volume_ratio,
        initiation_ratio=initiation_ratio,
        top_target_bonus=top_target,
    )

    # 互动模式判断
    metrics.interaction_pattern = classify_interaction_pattern(metrics)

    # 动态时间信号（不参与加权，仅注入上下文）
    metrics.session_recency = compute_session_recency(conn, contact_wxid, mc.session_gap_hours, ref_date=ref_date)
    metrics.momentum = compute_momentum(conn, contact_wxid, my_wxid, mc.session_gap_hours, ref_date=ref_date)
    metrics.initiation_source = compute_initiation_source(conn, contact_wxid, my_wxid, mc.session_gap_hours, ref_date=ref_date)
    metrics.media_engagement = compute_media_engagement(conn, contact_wxid, my_wxid, mc.active_days_window, ref_date=ref_date)

    base_score = compute_base_score(metrics, config.weights, top_target)
    metrics.base_score = base_score

    if prev_base_score is not None:
        trend_raw = base_score - prev_base_score
        metrics.trend = MetricValue(
            raw=round(trend_raw, 4),
            normalized=round(_clamp(trend_raw + 0.5), 4),
            confidence=0.5, sample_size=2,
        )
    else:
        metrics.trend = MetricValue(raw=0.0, normalized=0.5, confidence=0.0, sample_size=0)

    trend_weight = config.weights.trend
    composite = base_score * neediness_penalty + metrics.trend.raw * trend_weight
    metrics.composite = round(_clamp(composite), 4)
    metrics.signal_level = compute_signal_level(metrics.composite)

    if compute_slope:
        metrics.composite_slope = compute_composite_slope(
            conn, config, contact_wxid, contact_name, ref_date=ref_date,
        )

    return metrics


def get_all_contacts_with_messages(conn: sqlite3.Connection, min_messages: int = 0) -> list[dict]:
    """获取所有有消息的联系人（私聊）。"""
    rows = conn.execute(
        """
        SELECT c.id AS wxid,
               COALESCE(c.display_name, c.id) AS display_name,
               COUNT(m.id) AS message_count
        FROM conversations c
        JOIN messages m ON m.conversation_id = c.id
        WHERE c.type = 'private'
        GROUP BY c.id
        HAVING message_count >= ?
        ORDER BY message_count DESC
        """,
        (min_messages,),
    ).fetchall()

    return [{"wxid": r["wxid"], "display_name": r["display_name"],
             "message_count": r["message_count"]} for r in rows]