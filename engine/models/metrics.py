"""指标模型。"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class MetricValue:
    raw: float = 0.0
    normalized: float = 0.0
    confidence: float = 0.0
    sample_size: int = 0
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        data = {
            "raw": self.raw,
            "normalized": self.normalized,
            "confidence": self.confidence,
            "sample_size": self.sample_size,
        }
        if self.extra:
            data["extra"] = self.extra
        return data

    @classmethod
    def from_dict(cls, d: dict) -> "MetricValue":
        return cls(
            raw=d.get("raw", 0.0),
            normalized=d.get("normalized", 0.0),
            confidence=d.get("confidence", 0.0),
            sample_size=d.get("sample_size", 0),
            extra=d.get("extra", {}),
        )


@dataclass
class DeltaInfo:
    composite: float = 0.0
    rank: int = 0

    def to_dict(self) -> dict:
        return {"composite": self.composite, "rank": self.rank}

    @classmethod
    def from_dict(cls, d: dict) -> "DeltaInfo":
        return cls(composite=d.get("composite", 0.0), rank=d.get("rank", 0))


@dataclass
class Metrics:
    _id: str = ""
    base_score: float = 0.0
    composite: float = 0.0
    signal_level: str = ""
    top_target_bonus: bool = False

    # 原始指标
    fback: MetricValue = field(default_factory=MetricValue)
    rlatency: MetricValue = field(default_factory=MetricValue)
    qscore: MetricValue = field(default_factory=MetricValue)
    escore: MetricValue = field(default_factory=MetricValue)
    moments: MetricValue = field(default_factory=MetricValue)
    msg_count: MetricValue = field(default_factory=MetricValue)
    active_days: MetricValue = field(default_factory=MetricValue)
    recent: MetricValue = field(default_factory=MetricValue)
    trend: MetricValue = field(default_factory=MetricValue)

    # 新增指标
    fback_quality: MetricValue = field(default_factory=MetricValue)
    escore_volatility: MetricValue = field(default_factory=MetricValue)
    qscore_personal: MetricValue = field(default_factory=MetricValue)
    qscore_functional: MetricValue = field(default_factory=MetricValue)
    rlatency_context: MetricValue = field(default_factory=MetricValue)
    msg_volume_trend: MetricValue = field(default_factory=MetricValue)
    latency_trend: MetricValue = field(default_factory=MetricValue)

    # Wiki 衍生指标（v2 新增）
    her_initiation_rate: MetricValue = field(default_factory=MetricValue)
    topic_continuation: MetricValue = field(default_factory=MetricValue)
    reply_quality: MetricValue = field(default_factory=MetricValue)
    session_balance: MetricValue = field(default_factory=MetricValue)
    emotional_temperature: MetricValue = field(default_factory=MetricValue)
    friendzone_risk: MetricValue = field(default_factory=MetricValue)

    # 语义指标（Layer 2，来自 MacBERT/规则双参考）
    semantic_flirt: MetricValue = field(default_factory=MetricValue)
    semantic_invitation: MetricValue = field(default_factory=MetricValue)
    semantic_emotion_balance: MetricValue = field(default_factory=MetricValue)

    # 需求感惩罚（乘法系数，不参与加权）
    neediness_penalty: float = 1.0
    volume_ratio: float = 1.0
    initiation_ratio: float = 0.5
    # 互动模式标签
    interaction_pattern: str = ""

    # 动态时间信号（signal_flags，不参与 composite 加权）
    session_recency: dict = field(default_factory=dict)
    momentum: dict = field(default_factory=dict)
    initiation_source: dict = field(default_factory=dict)
    # 媒体参与度
    media_engagement: dict = field(default_factory=dict)
    # composite 趋势斜率（回测验证有区分力：成功 >+0.005，失败 ≈0 或负）
    composite_slope: MetricValue = field(default_factory=MetricValue)

    delta: DeltaInfo = field(default_factory=DeltaInfo)

    def all_metrics(self) -> dict[str, MetricValue]:
        """返回所有参与加权的 MetricValue 字段。"""
        return {
            "fback": self.fback,
            "rlatency": self.rlatency,
            "qscore": self.qscore,
            "escore": self.escore,
            "moments": self.moments,
            "msg_count": self.msg_count,
            "active_days": self.active_days,
            "recent": self.recent,
            "trend": self.trend,
            "fback_quality": self.fback_quality,
            "escore_volatility": self.escore_volatility,
            "qscore_personal": self.qscore_personal,
            "qscore_functional": self.qscore_functional,
            "rlatency_context": self.rlatency_context,
            "msg_volume_trend": self.msg_volume_trend,
            "latency_trend": self.latency_trend,
            "her_initiation_rate": self.her_initiation_rate,
            "topic_continuation": self.topic_continuation,
            "reply_quality": self.reply_quality,
            "session_balance": self.session_balance,
            "emotional_temperature": self.emotional_temperature,
            "friendzone_risk": self.friendzone_risk,
            "semantic_flirt": self.semantic_flirt,
            "semantic_invitation": self.semantic_invitation,
            "semantic_emotion_balance": self.semantic_emotion_balance,
        }

    def to_yaml(self) -> dict:
        data = {
            "_id": self._id,
            "base_score": round(self.base_score, 4),
            "composite": round(self.composite, 4),
            "signal_level": self.signal_level,
            "top_target_bonus": self.top_target_bonus,
            "neediness_penalty": round(self.neediness_penalty, 4),
            "volume_ratio": round(self.volume_ratio, 4),
            "initiation_ratio": round(self.initiation_ratio, 4),
            "interaction_pattern": self.interaction_pattern,
            "metrics": {k: v.to_dict() for k, v in self.all_metrics().items()},
            "delta": self.delta.to_dict(),
        }
        if self.session_recency:
            data["session_recency"] = self.session_recency
        if self.momentum:
            data["momentum"] = self.momentum
        if self.initiation_source:
            data["initiation_source"] = self.initiation_source
        if self.media_engagement:
            data["media_engagement"] = self.media_engagement
        if self.composite_slope.sample_size > 0:
            data["composite_slope"] = self.composite_slope.to_dict()
        return data

    @classmethod
    def from_yaml(cls, d: dict) -> "Metrics":
        metrics_d = d.get("metrics", {})
        return cls(
            _id=d.get("_id", ""),
            base_score=d.get("base_score", 0.0),
            composite=d.get("composite", 0.0),
            signal_level=d.get("signal_level", ""),
            top_target_bonus=d.get("top_target_bonus", False),
            neediness_penalty=d.get("neediness_penalty", 1.0),
            volume_ratio=d.get("volume_ratio", 1.0),
            initiation_ratio=d.get("initiation_ratio", 0.5),
            interaction_pattern=d.get("interaction_pattern", ""),
            fback=MetricValue.from_dict(metrics_d.get("fback", {})),
            rlatency=MetricValue.from_dict(metrics_d.get("rlatency", {})),
            qscore=MetricValue.from_dict(metrics_d.get("qscore", {})),
            escore=MetricValue.from_dict(metrics_d.get("escore", {})),
            moments=MetricValue.from_dict(metrics_d.get("moments", {})),
            msg_count=MetricValue.from_dict(metrics_d.get("msg_count", {})),
            active_days=MetricValue.from_dict(metrics_d.get("active_days", {})),
            recent=MetricValue.from_dict(metrics_d.get("recent", {})),
            trend=MetricValue.from_dict(metrics_d.get("trend", {})),
            fback_quality=MetricValue.from_dict(metrics_d.get("fback_quality", {})),
            escore_volatility=MetricValue.from_dict(metrics_d.get("escore_volatility", {})),
            qscore_personal=MetricValue.from_dict(metrics_d.get("qscore_personal", {})),
            qscore_functional=MetricValue.from_dict(metrics_d.get("qscore_functional", {})),
            rlatency_context=MetricValue.from_dict(metrics_d.get("rlatency_context", {})),
            msg_volume_trend=MetricValue.from_dict(metrics_d.get("msg_volume_trend", {})),
            latency_trend=MetricValue.from_dict(metrics_d.get("latency_trend", {})),
            her_initiation_rate=MetricValue.from_dict(metrics_d.get("her_initiation_rate", {})),
            topic_continuation=MetricValue.from_dict(metrics_d.get("topic_continuation", {})),
            reply_quality=MetricValue.from_dict(metrics_d.get("reply_quality", {})),
            session_balance=MetricValue.from_dict(metrics_d.get("session_balance", {})),
            emotional_temperature=MetricValue.from_dict(metrics_d.get("emotional_temperature", {})),
            friendzone_risk=MetricValue.from_dict(metrics_d.get("friendzone_risk", {})),
            session_recency=d.get("session_recency", {}),
            momentum=d.get("momentum", {}),
            initiation_source=d.get("initiation_source", {}),
            media_engagement=d.get("media_engagement", {}),
            composite_slope=MetricValue.from_dict(d.get("composite_slope", {})),
            delta=DeltaInfo.from_dict(d.get("delta", {})),
        )
