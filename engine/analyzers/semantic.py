"""语义分析引擎 — Layer 2 派生行为信号聚合。

架构定位（见 readme/PROJECT.md #语义分析）：
    Layer 1: MacBERT/规则 → 10 个可观测行为标签（文本层面）
    Layer 2: 本模块 → 将观测结果聚合为派生行为信号（客观统计，非关系判断）

定位（行为信号层，非判断层）：
    本模块输出的是结构化统计数据（比例、均值、聚合值），不是关系结论。
    "interest_signal=0.8" 表示"兴趣相关行为标签占比 80%"，不是"她对你有兴趣"。
    关系判断由 Agent + Wiki + 事实档案综合完成，本模块只提供客观观测值。

聚合公式（规划文档 2.3）：
    conversation_layer = {information_exchange, opinion_expression, flirt}
                         + {emotion_positive, emotion_negative}
    emotion_balance    = emotion_positive / (emotion_positive + emotion_negative)
    interest_signal    = f(question_asking, self_disclosure, invitation, flirt)
    friendship_signal  = f(framing_boundary, perfunctory)

friendzone_risk 需要额外的事件/约会数据（stagnation + date_progress），
不在本模块计算，由 Agent 综合判断。

双尺度架构（规划文档 3.2）：
    Window（20轮局部窗口）→ 模型负责，本模块调用
    Timeline（跨窗口趋势）→ 本模块聚合
"""
from __future__ import annotations

import sqlite3
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from engine.config import Config
from engine.identity import IdentityPerson

logger = logging.getLogger(__name__)

# 滑动窗口参数（规划文档 3.1）
WINDOW_SIZE = 20  # 20 轮（一来一回算一轮，连续同人消息合并为一个发言轮次）
SLIDE_SIZE = 10   # 每 10 轮抽一个窗口
MIN_TURNS = 10    # 窗口内最少轮次

# 10 个可观测行为标签
LABELS = [
    "information_exchange",
    "opinion_expression",
    "emotion_positive",
    "emotion_negative",
    "flirt",
    "question_asking",
    "self_disclosure",
    "invitation",
    "framing_boundary",
    "perfunctory",
]


@dataclass
class WindowBehavior:
    """单个窗口的行为分析结果。"""
    window_index: int
    start_ts: int
    end_ts: int
    turn_count: int
    scores: dict[str, float]  # 0-9 分数
    labels: dict[str, bool]   # binary 判定


@dataclass
class SemanticMetrics:
    """语义指标（Layer 2 融合结果）。"""
    # 原始观测值（最近窗口的平均分）
    behavior_scores: dict[str, float] = field(default_factory=dict)

    # 派生指标
    emotion_balance: float = 0.0        # 正负情绪比 [0, 1]
    interest_signal: float = 0.0        # 兴趣信号 [0, 1]
    friendship_signal: float = 0.0      # 友谊化信号 [0, 1]
    conversation_depth: float = 0.0     # 对话深度（信息+观点+情感+暧昧）

    # 趋势指标（跨窗口）
    flirt_trend: float = 0.0           # 暧昧变化趋势
    emotion_trend: float = 0.0         # 情绪变化趋势
    interest_trend: float = 0.0        # 兴趣变化趋势

    # 窗口列表
    windows: list[WindowBehavior] = field(default_factory=list)

    # 元信息
    window_count: int = 0
    source: str = "macbert"  # macbert | rule | ensemble


def _build_turns(messages: list[dict], my_wxid: str) -> list[dict]:
    """将消息列表按发言轮次合并。

    连续同人消息合并为一个发言轮次，交替计数。
    返回 [{"role": "her"/"me", "content": "合并文本", "ts": timestamp}, ...]
    """
    if not messages:
        return []

    turns: list[dict] = []
    current_role = None
    current_texts: list[str] = []
    current_ts = 0

    for msg in messages:
        is_mine = msg.get("is_mine", msg.get("sender_id") == my_wxid)
        role = "me" if is_mine else "her"
        content = msg.get("content", "")

        if role != current_role:
            if current_role is not None and current_texts:
                turns.append({
                    "role": current_role,
                    "content": "\n".join(current_texts),
                    "ts": current_ts,
                })
            current_role = role
            current_texts = [content]
            current_ts = msg.get("timestamp", 0)
        else:
            current_texts.append(content)

    if current_role is not None and current_texts:
        turns.append({
            "role": current_role,
            "content": "\n".join(current_texts),
            "ts": current_ts,
        })

    return turns


def _extract_windows(turns: list[dict], window_size: int = WINDOW_SIZE,
                     slide_size: int = SLIDE_SIZE, min_turns: int = MIN_TURNS) -> list[list[dict]]:
    """从轮次列表中提取滑动窗口。"""
    if len(turns) < min_turns:
        return []

    windows: list[list[dict]] = []
    i = 0
    while i + window_size <= len(turns):
        windows.append(turns[i:i + window_size])
        i += slide_size

    if not windows and len(turns) >= min_turns:
        windows.append(turns)

    return windows


def _query_recent_messages(
    conn: sqlite3.Connection, config: Config, person: IdentityPerson,
    window_days: int = 30,
) -> list[dict]:
    """查询最近 N 天的聊天消息。"""
    cutoff = int((datetime.now() - timedelta(days=window_days)).timestamp())
    messages: list[dict] = []

    for account in person.accounts:
        cid = account.conversation_id or account.wxid
        if not cid:
            continue
        rows = conn.execute(
            "SELECT id, sender_id, content, timestamp, type "
            "FROM messages WHERE conversation_id = ? AND type = 1 AND timestamp >= ? "
            "ORDER BY timestamp ASC",
            (cid, cutoff),
        ).fetchall()
        for row in rows:
            sender_id = row["sender_id"] or ""
            messages.append({
                "id": row["id"],
                "sender_id": sender_id,
                "is_mine": sender_id == config.my_wxid,
                "content": row["content"] or "",
                "timestamp": row["timestamp"],
            })

    messages.sort(key=lambda m: m["timestamp"])
    return messages


def _classify_window_onnx(window_turns: list[dict], model: str = "b0",
                           target_role: str = "her") -> tuple[dict[str, float], dict[str, bool]]:
    """用 MacBERT ONNX 对单个窗口做行为分析。

    Args:
        window_turns: _build_turns 输出的窗口（含 role/content/ts 的 dict 列表）
        model: "b0"（B0' roleless）| "b2"（B2 role-aware）
        target_role: "her" | "me"。只在 model="b2" 时有效，B0' 忽略
    """
    from ml.rules.classifier_onnx import ONNXBehaviorClassifier

    clf = ONNXBehaviorClassifier.get_b2() if model == "b2" else ONNXBehaviorClassifier.get_b0()
    scores = clf.predict_scores(window_turns, target_role=target_role)
    labels = {label: score >= 3.0 for label, score in scores.items()}
    return scores, labels


def _classify_window_rule(window_turns: list[dict]) -> tuple[dict[str, float], dict[str, bool]]:
    """用规则 baseline 对单个窗口做行为分析（双参考）。"""
    from ml.rules.baseline_classifier import load_all_classifiers

    classifiers = load_all_classifiers()
    her_messages = [{"content": t["content"]} for t in window_turns if t["role"] == "her"]

    scores: dict[str, float] = {}
    labels: dict[str, bool] = {}
    for label, clf in classifiers.items():
        pred, conf = clf.classify_window(her_messages)
        labels[label] = pred
        scores[label] = round(conf * 9.0, 2)

    return scores, labels


def _compute_emotion_balance(scores: dict[str, float]) -> float:
    """emotion_balance = positive / (positive + negative)。"""
    pos = scores.get("emotion_positive", 0)
    neg = scores.get("emotion_negative", 0)
    total = pos + neg
    if total < 0.01:
        return 0.5  # 无情绪数据时返回中性
    return round(pos / total, 3)


def _compute_interest_signal(scores: dict[str, float]) -> float:
    """interest_signal = f(question_asking, self_disclosure, invitation, flirt)。

    归一化到 [0, 1]，输入是 0-9 分数。
    """
    keys = ["question_asking", "self_disclosure", "invitation", "flirt"]
    vals = [scores.get(k, 0) for k in keys]
    avg = sum(vals) / len(vals) / 9.0  # 归一化到 0-1
    return round(min(1.0, avg), 3)


def _compute_friendship_signal(scores: dict[str, float]) -> float:
    """friendship_signal = f(framing_boundary, perfunctory)。"""
    keys = ["framing_boundary", "perfunctory"]
    vals = [scores.get(k, 0) for k in keys]
    avg = sum(vals) / len(vals) / 9.0
    return round(min(1.0, avg), 3)


def _compute_conversation_depth(scores: dict[str, float]) -> float:
    """conversation_depth = 信息+观点+情感+暧昧的综合深度。"""
    keys = ["information_exchange", "opinion_expression",
            "emotion_positive", "emotion_negative", "flirt"]
    vals = [scores.get(k, 0) for k in keys]
    avg = sum(vals) / len(vals) / 9.0
    return round(min(1.0, avg), 3)


def _compute_trend(windows: list[WindowBehavior], label: str) -> float:
    """计算某标签的跨窗口趋势（线性回归斜率的简化版）。

    Returns:
        正值 = 上升趋势，负值 = 下降趋势，0 = 稳定
    """
    if len(windows) < 2:
        return 0.0

    values = [w.scores.get(label, 0) for w in windows]
    n = len(values)
    first_half = sum(values[:n // 2]) / max(1, n // 2)
    second_half = sum(values[n // 2:]) / max(1, n - n // 2)

    return round((second_half - first_half) / 9.0, 3)


def compute_semantic_metrics(
    conn: sqlite3.Connection,
    config: Config,
    person: IdentityPerson,
    *,
    window_days: int = 30,
    source: str = "macbert",
    model: str = "b0",
    target_role: str = "her",
) -> SemanticMetrics:
    """计算某人的语义指标。

    Args:
        conn: SQLite 连接
        config: 配置
        person: 联系人
        window_days: 回溯天数
        source: 分析源 "macbert" | "rule" | "ensemble"
        model: "b0"（B0' roleless）| "b2"（B2 role-aware）
        target_role: "her" | "me"。B0' 忽略此参数

    Returns:
        SemanticMetrics
    """
    messages = _query_recent_messages(conn, config, person, window_days=window_days)

    if len(messages) < 5:
        return SemanticMetrics(
            behavior_scores={label: 0.0 for label in LABELS},
            source=source,
            window_count=0,
        )

    turns = _build_turns(messages, config.my_wxid)
    windows_turns = _extract_windows(turns)

    if not windows_turns:
        return SemanticMetrics(
            behavior_scores={label: 0.0 for label in LABELS},
            source=source,
            window_count=0,
        )

    windows: list[WindowBehavior] = []
    for i, wt in enumerate(windows_turns):
        if source == "rule":
            scores, labels = _classify_window_rule(wt)
        else:
            scores, labels = _classify_window_onnx(wt, model=model, target_role=target_role)

        windows.append(WindowBehavior(
            window_index=i,
            start_ts=wt[0]["ts"],
            end_ts=wt[-1]["ts"],
            turn_count=len(wt),
            scores=scores,
            labels=labels,
        ))

    # 聚合：取最近窗口的均值作为当前行为画像
    recent_windows = windows[-3:] if len(windows) >= 3 else windows
    avg_scores: dict[str, float] = {}
    for label in LABELS:
        vals = [w.scores.get(label, 0) for w in recent_windows]
        avg_scores[label] = round(sum(vals) / len(vals), 2)

    # Layer 2 融合
    emotion_balance = _compute_emotion_balance(avg_scores)
    interest_signal = _compute_interest_signal(avg_scores)
    friendship_signal = _compute_friendship_signal(avg_scores)
    conversation_depth = _compute_conversation_depth(avg_scores)

    # 趋势
    flirt_trend = _compute_trend(windows, "flirt")
    emotion_trend = _compute_trend(windows, "emotion_positive")
    interest_trend = _compute_trend(windows, "question_asking")

    return SemanticMetrics(
        behavior_scores=avg_scores,
        emotion_balance=emotion_balance,
        interest_signal=interest_signal,
        friendship_signal=friendship_signal,
        conversation_depth=conversation_depth,
        flirt_trend=flirt_trend,
        emotion_trend=emotion_trend,
        interest_trend=interest_trend,
        windows=windows,
        window_count=len(windows),
        source=source,
    )


def format_semantic_report(metrics: SemanticMetrics, display_name: str = "") -> str:
    """将语义指标格式化为 Markdown 报告。"""
    lines: list[str] = []
    name = display_name or "对方"
    lines.append(f"## {name} 语义行为分析\n")
    lines.append(f"**分析源**: {metrics.source} | **窗口数**: {metrics.window_count}\n")

    lines.append("### 可观测行为标签（0-9）\n")
    lines.append("| 标签 | 分数 | 判定 | 可视化 |")
    lines.append("|------|------|------|--------|")
    for label in LABELS:
        score = metrics.behavior_scores.get(label, 0)
        present = "✓" if score >= 3.0 else " "
        bar = "█" * max(0, min(10, int(score))) + "░" * max(0, 10 - max(0, min(10, int(score))))
        lines.append(f"| {label} | {score:.1f} | {present} | {bar} |")

    lines.append("\n### 派生指标（Layer 2 融合）\n")
    lines.append("| 指标 | 值 | 说明 |")
    lines.append("|------|-----|------|")
    lines.append(f"| emotion_balance | {metrics.emotion_balance:.2f} | 正负情绪比（0=全负, 0.5=平衡, 1=全正） |")
    lines.append(f"| interest_signal | {metrics.interest_signal:.2f} | 兴趣信号（提问+分享+邀约+暧昧） |")
    lines.append(f"| friendship_signal | {metrics.friendship_signal:.2f} | 友谊化信号（边界词+敷衍） |")
    lines.append(f"| conversation_depth | {metrics.conversation_depth:.2f} | 对话深度（信息+观点+情感+暧昧） |")

    lines.append("\n### 趋势分析（跨窗口）\n")
    lines.append("| 维度 | 趋势 | 方向 |")
    lines.append("|------|------|------|")
    trend_arrow = lambda v: "↑ 上升" if v > 0.05 else ("↓ 下降" if v < -0.05 else "→ 稳定")
    lines.append(f"| 暧昧趋势 | {metrics.flirt_trend:+.3f} | {trend_arrow(metrics.flirt_trend)} |")
    lines.append(f"| 正向情绪趋势 | {metrics.emotion_trend:+.3f} | {trend_arrow(metrics.emotion_trend)} |")
    lines.append(f"| 提问趋势 | {metrics.interest_trend:+.3f} | {trend_arrow(metrics.interest_trend)} |")

    if metrics.windows:
        lines.append("\n### 窗口明细\n")
        lines.append("| # | 轮次 | 时间 | flirt | interest | friendship |")
        lines.append("|---|------|------|-------|----------|------------|")
        for w in metrics.windows:
            dt = datetime.fromtimestamp(w.start_ts).strftime("%m-%d %H:%M")
            flirt_s = w.scores.get("flirt", 0)
            interest_keys = ["question_asking", "self_disclosure", "invitation", "flirt"]
            interest_avg = sum(w.scores.get(k, 0) for k in interest_keys) / len(interest_keys)
            friend_keys = ["framing_boundary", "perfunctory"]
            friend_avg = sum(w.scores.get(k, 0) for k in friend_keys) / len(friend_keys)
            lines.append(f"| {w.window_index} | {w.turn_count} | {dt} | {flirt_s:.1f} | {interest_avg:.1f} | {friend_avg:.1f} |")

    lines.append("\n### 解读提示\n")
    if metrics.interest_signal > 0.4 and metrics.friendship_signal < 0.3:
        lines.append("- 兴趣信号较强且友谊化信号低，关系可能有升温空间")
    elif metrics.interest_signal < 0.2 and metrics.friendship_signal > 0.4:
        lines.append("- 兴趣信号弱且友谊化信号强，可能进入友谊区")
    else:
        lines.append("- 兴趣和友谊信号均衡，需结合 Wiki 框架和事实档案综合判断")

    if metrics.flirt_trend > 0.1:
        lines.append("- 暧昧呈上升趋势，关注升温窗口")
    elif metrics.flirt_trend < -0.1:
        lines.append("- 暧昧呈下降趋势，注意关系冷却")

    if metrics.emotion_balance < 0.3:
        lines.append("- 负面情绪占比较高，注意对方状态")
    elif metrics.emotion_balance > 0.7:
        lines.append("- 正面情绪占比较高，互动氛围良好")

    return "\n".join(lines)
