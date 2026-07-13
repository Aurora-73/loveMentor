# 数据模型

## 概述

`engine/models/` 定义系统中所有数据结构。全部是纯 Python dataclass，支持 YAML 序列化。不包含业务逻辑。

## 核心文件

| 文件 | 行数 | 关键类 |
|------|------|--------|
| `metrics.py` | 206 | `MetricValue`, `Metrics`, `DeltaInfo` |
| `ranking.py` | 104 | `RankedPerson`, `Ranking`, `RankingChange`, `InsufficientData` |
| `stage.py` | 118 | `Stage`, `StageState`, `StageOverride`, `EvidenceEntry` |
| `event.py` | 40 | `Event` |
| `failure.py` | 77 | `FailureCase`, `FailurePattern` |
| `profile.py` | ~90 | `Profile`（继承 EntityBase，支持自定义字段） |
| `strategy.py` | 71 | `Strategy`, `Action`, `Risk` |
| `evaluation.py` | 54 | `Evaluation`, `TimelineEntry` |
| `date_review.py` | 54 | `DateReview` |
| `base.py` | 46 | `EntityBase`（元数据基类） |

## MetricValue（单个指标）

```python
@dataclass
class MetricValue:
    raw: float = 0.0           # 原始值
    normalized: float = 0.0    # 归一化到 [0, 1]
    confidence: float = 0.0    # 置信度（样本量越少越低）
    sample_size: int = 0       # 计算用的样本数
    extra: dict = field(default_factory=dict)  # 附加数据（非空时才序列化）
```

## DeltaInfo（变化信息）

```python
@dataclass
class DeltaInfo:
    composite: float = 0.0   # composite 变化量
    rank: int = 0            # 排名变化量
```

## Metrics（指标集合）

```python
@dataclass
class Metrics:
    # 元数据
    _id: str = ""

    # 复合指标
    base_score: float = 0.0          # composite × neediness_penalty
    composite: float = 0.0           # 最终加权分数
    signal_level: str = ""           # "强窗口" / "中窗口" / "弱窗口" / "冷淡" / "无信号"
    top_target_bonus: bool = False   # 置顶攻略对象加成

    # 原始指标（每个都是 MetricValue）
    fback: MetricValue               # 回复率
    rlatency: MetricValue            # 回复延迟
    qscore: MetricValue              # 基础质量分
    escore: MetricValue              # 情绪分
    moments: MetricValue             # 朋友圈互动
    msg_count: MetricValue           # 消息总数
    active_days: MetricValue         # 活跃天数
    recent: MetricValue              # 最后消息距今天数
    trend: MetricValue               # 趋势变化

    # 新增指标
    fback_quality: MetricValue       # 回复质量
    escore_volatility: MetricValue   # 情绪波动
    qscore_personal: MetricValue     # 个人兴趣质量
    qscore_functional: MetricValue   # 功能性聊天质量
    rlatency_context: MetricValue    # 上下文回复延迟
    msg_volume_trend: MetricValue    # 消息量趋势
    latency_trend: MetricValue       # 延迟趋势

    # Wiki 衍生指标（v2 新增）
    her_initiation_rate: MetricValue       # 她主动发起率
    topic_continuation: MetricValue        # 话题延续度
    reply_quality: MetricValue             # 回复质量（Wiki）
    session_balance: MetricValue           # 会话平衡度
    emotional_temperature: MetricValue     # 情绪温度
    friendzone_risk: MetricValue           # 好人卡风险

    # 语义指标（Layer 2，来自 MacBERT/规则双参考）
    semantic_flirt: MetricValue            # 语义调情
    semantic_invitation: MetricValue       # 语义邀约
    semantic_emotion_balance: MetricValue  # 语义情绪平衡

    # 需求感惩罚（乘法系数，不参与加权）
    neediness_penalty: float = 1.0   # 乘法惩罚 (0.4-1.0)
    volume_ratio: float = 1.0        # 消息量比（你/她）
    initiation_ratio: float = 0.5    # 你主动发起的比例
    interaction_pattern: str = ""    # "lover" / "provider" / "neutral"

    # 动态时间信号（不参与 composite 加权）
    session_recency: dict = field(default_factory=dict)
    momentum: dict = field(default_factory=dict)
    initiation_source: dict = field(default_factory=dict)
    media_engagement: dict = field(default_factory=dict)
    composite_slope: MetricValue = field(default_factory=MetricValue)  # composite 趋势斜率

    # 变化
    delta: DeltaInfo = field(default_factory=DeltaInfo)  # 与上周对比
```

## RankedPerson（排名条目）

```python
@dataclass
class RankedPerson:
    rank: int = 0               # 排名（1-based）
    name: str = ""              # 显示名
    _id: str = ""               # 向后兼容，等于 person_id
    person_id: str = ""         # identity 系统的 person_id
    base_score: float = 0.0     # 加权分数
    composite: float = 0.0      # 最终分数
    signal_level: str = ""      # 信号等级
    stage: str = ""             # 关系阶段
    delta_rank: int = 0         # 排名变化（正=上升，负=下降）
    delta_composite: float = 0.0
    tags: list[str] = field(default_factory=list)  # ["riser", "faller", "置顶攻略对象"]
```

## Ranking（排名集合）

```python
@dataclass
class RankingChange:
    name: str = ""
    reason: str = ""

@dataclass
class InsufficientData:
    name: str = ""
    message_count: int = 0
    status: str = "数据不足，不参与排名"

@dataclass
class Ranking:
    week: str = ""                                    # "2026-W24"
    generated_at: str = ""
    total_candidates: int = 0                         # 总候选人数
    rankings: list[RankedPerson] = field(default_factory=list)  # 按 composite 降序
    risers: list[RankingChange] = field(default_factory=list)   # 排名上升的人
    fallers: list[RankingChange] = field(default_factory=list)  # 排名下降的人
    insufficient_data: list[InsufficientData] = field(default_factory=list)
    strategy_summary: list[dict] = field(default_factory=list)  # 策略摘要
```

## Stage（关系阶段）

阶段列表（共 9 个，注意代码中没有"冷淡/停滞"）：

```python
STAGES = [
    "未识别",      # 没有足够数据判断
    "初识",        # 刚认识，礼貌性回复
    "有基本互动",  # 有来有回但停留在表面
    "高频聊天",    # 经常聊天，主动分享日常
    "已约见",      # 已经线下见过面
    "持续接触",    # 见面后继续保持联系
    "暧昧推进",    # 明确好感信号
    "关系确认",    # 已确认恋爱关系
    "退出/失败",   # 基本不再联系或明确拒绝
]
```

```python
@dataclass
class StageState:
    current_stage: str = "未识别"
    entered_at: str = ""
    days_in_current_stage: int = 0
    is_stagnant: bool = False
    next_stage: str = ""
    advancement_signals: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)

@dataclass
class StageOverride:
    stage: str = ""
    reason: str = ""
    overridden_at: str = ""

@dataclass
class EvidenceEntry:
    date: str = ""
    event: str = ""
    source: str = ""
    metrics_snapshot: dict = field(default_factory=dict)
    stage_change: str = ""

@dataclass
class Stage:
    stage_state: StageState = field(default_factory=StageState)
    stage_override: Optional[StageOverride] = None
    evidence_chain: list[EvidenceEntry] = field(default_factory=list)

    @property
    def effective_stage(self) -> str:
        """优先返回 stage_override，否则返回 stage_state.current_stage。"""
```

## Event（关系事件）

```python
@dataclass
class Event:
    _id: str = ""
    timestamp: str = ""        # 事件时间戳
    event_type: str = ""       # 事件类型（FIRST_CHAT / DISCONNECT / RECONNECT 等）
    content: str = ""          # 事件描述
    source: str = "manual"     # 来源（manual / system / agent）
    confidence: float = 1.0    # 置信度
    tags: list[str] = field(default_factory=list)  # 标签
    ref: str = ""              # 引用（关联消息 ID 等）
```

## Profile（联系人档案）

联系人基础档案，继承自 `EntityBase`，支持 YAML 序列化。

```python
@dataclass
class Profile(EntityBase):
    name: str = ""
    wxid: str = ""
    wechat_id: str = ""
    nickname: str = ""
    remark: str = ""
    tags: list[str] = field(default_factory=list)
    description: str = ""
    added_date: str = ""
    age: int | None = None
    occupation: str = ""

    custom_fields: dict[str, str] = field(default_factory=dict)
```

### 自定义字段（custom_fields）

支持任意键值对的扩展字段，用于存储项目特有、不想硬编码到模型中的数据。

```python
# 设置自定义字段
profile.set_custom("mbti", "INFP")
profile.set_custom("hobby", "摄影")

# 获取自定义字段
mbti = profile.get_custom("mbti")       # "INFP"
unknown = profile.get_custom("not_exist")    # ""
unknown2 = profile.get_custom("not_exist", "默认值")  # "默认值"

# 删除自定义字段
profile.remove_custom("mbti")
```

**YAML 序列化规则**：
- `custom_fields` 非空时才会出现在 YAML 中
- 旧版 YAML 没有 custom_fields 字段，加载时默认为空 dict
- 完全向后兼容

### 从微信同步创建

```python
profile = Profile.from_wechat_row(row)  # 从 contacts 表行创建
```

## FailureCase（失败案例）

```python
@dataclass
class FailurePattern:
    category: str = ""
    detail: str = ""

@dataclass
class FailureCase:
    person_id: str = ""           # 关联的 person_id（可选）
    person: str = ""              # 人物名称（显示用）
    date: str = ""                # 发生日期
    stage: str = ""               # 当时所处阶段
    cause: str = ""               # 失败原因（一句话）
    signals: list[str] = field(default_factory=list)       # 失败信号
    outcome: str = ""             # 结果
    lesson: str = ""              # 教训
    duration_months: int = 0      # 持续月数
    stage_reached: str = ""       # 达到的最高阶段
    failure_reasons: list[FailurePattern] = field(default_factory=list)  # 关联的失败模式
    error_patterns: list[str] = field(default_factory=list)
    lessons: list[str] = field(default_factory=list)
    retrospective_detection: bool = False
    detection_signals: list[str] = field(default_factory=list)
    created_at: str = ""
```

## Strategy（策略）

```python
@dataclass
class Action:
    priority: int = 0       # 优先级（数字越大越优先）
    action: str = ""        # 行动描述
    detail: str = ""        # 详细说明
    reason: str = ""        # 推荐理由

@dataclass
class Risk:
    description: str = ""   # 风险描述
    source: str = ""        # 风险来源
    severity: str = "low"   # "high" / "medium" / "low"

@dataclass
class Strategy:
    _id: str = ""
    current_stage: str = ""        # 当前阶段
    heat_level: float = 0.0        # 热度等级
    her_intent: str = "none"       # 她的意图
    advancement_risk: str = "low"  # 推进风险
    actions: list[Action] = field(default_factory=list)
    risks: list[Risk] = field(default_factory=list)
    knowledge_refs: list[str] = field(default_factory=list)  # Wiki 引用
```

## EntityBase（元数据基类）

```python
@dataclass
class EntityBase:
    """所有实体必须携带的统一元数据"""
    _id: str = ""
    source: str = ""
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    version: int = 1
    confidence: float = 1.0
    privacy_level: str = "private"

    def touch(self):
        """更新 updated_at 时间戳并递增 version。"""
        self.updated_at = now_iso()
        self.version += 1
```

## YAML 序列化

各 model 自行实现序列化方法，命名不统一：

| 模型 | 序列化方法 |
|------|-----------|
| `Metrics` | `to_yaml()` / `from_yaml()` |
| `Profile` | `to_yaml()` / `from_yaml()` |
| `Stage` | `to_yaml()` / `from_yaml()` |
| `FailureCase` | `to_yaml()` / `from_yaml()` |
| `Strategy` | `to_yaml()` / `from_yaml()` |
| `Ranking` | `to_yaml()` / `from_yaml()` |
| `MetricValue` | `to_dict()` / `from_dict()` |
| `DeltaInfo` | `to_dict()` / `from_dict()` |
| `RankedPerson` | `to_dict()` / `from_dict()` |
| `Event` | `to_dict()` / `from_dict()` |
| `RankingChange` | `to_dict()` |

`EntityBase` 仅提供 `_id`/`source`/`created_at` 等元数据字段和 `touch()` 方法，不包含序列化逻辑。

```python
from engine.models.metrics import Metrics
m = Metrics(...)
data = m.to_yaml()  # → dict（可直接 yaml.dump）
m2 = Metrics.from_yaml(data)  # → Metrics
```

排名快照存储在 `data/outputs/rankings/` 下，格式为 YAML。

## 注意事项

1. **MetricValue.confidence**：样本量少于 10 条消息时，confidence 会显著下降。`ranker.py` 会把低信心的人放入 `insufficient_data` 列表。
2. **Stage 与 metrics 的关系**：Stage 是离散的状态，metrics 是连续的 [0,1] 分数。Stage 判断需要结合两者。
3. **DeltaInfo**：默认为空对象（非 None），`delta.composite = 0.0` 且 `delta.rank = 0`。首次运行周报时 delta 保持默认值。
4. **Interaction pattern**：通过消息量比、发起频率、回复质量综合判断。"provider" 表示你在供养者模式。
5. **序列化方法不统一**：大模型用 `to_yaml`/`from_yaml`，小型值对象用 `to_dict`/`from_dict`。使用时需注意区分。
