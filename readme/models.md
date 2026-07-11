# 数据模型

## 概述

`engine/models/` 定义系统中所有数据结构。全部是纯 Python dataclass，支持 YAML 序列化。不包含业务逻辑。

## 核心文件

| 文件 | 行数 | 关键类 |
|------|------|--------|
| `metrics.py` | 162 | `MetricValue`, `Metrics`, `DeltaInfo` |
| `ranking.py` | 104 | `RankedPerson`, `Ranking`, `RankingChange`, `InsufficientData` |
| `stage.py` | 118 | `Stage`, `StageState`, `StageOverride`, `EvidenceEntry` |
| `event.py` | 40 | `Event` |
| `failure.py` | 77 | `FailureCase`, `FailurePattern` |
| `profile.py` | ~90 | `Profile`（继承 EntityBase，支持自定义字段） |
| `strategy.py` | 71 | `Strategy`, `Action`, `Risk` |
| `evaluation.py` | 54 | `Evaluation`, `TimelineEntry` |
| `date_review.py` | 54 | `DateReview` |
| `base.py` | 46 | `EntityBase`（YAML 序列化基类） |

## MetricValue（单个指标）

```python
@dataclass
class MetricValue:
    raw: float           # 原始值
    normalized: float    # 归一化到 [0, 1]
    confidence: float    # 置信度（样本量越少越低）
    sample_size: int     # 计算用的样本数
```

## Metrics（指标集合）

```python
@dataclass
class Metrics:
    # 指标字段（每个都是 MetricValue）
    fback: MetricValue
    rlatency: MetricValue
    fback_quality: MetricValue
    qscore_personal: MetricValue
    trend: MetricValue
    escore_volatility: MetricValue
    moments: MetricValue
    qscore_functional: MetricValue
    rlatency_context: MetricValue
    msg_volume_trend: MetricValue
    latency_trend: MetricValue
    recent: MetricValue
    active_days: MetricValue
    escore: MetricValue
    msg_count: MetricValue

    # 复合指标
    neediness_penalty: float  # 乘法惩罚 (0.4-1.0)
    interaction_pattern: str  # "lover" / "provider" / "neutral"
    composite: float          # 最终加权分数
    signal_level: str         # "强窗口" / "中窗口" / "弱窗口" / "冷淡" / "无信号"
    base_score: float         # composite × neediness_penalty

    # 动态信号
    session_recency: dict
    momentum: dict
    initiation_source: dict
    media_engagement: dict
    composite_slope: MetricValue  # composite趋势斜率（3点线性回归，不参与加权）

    # 变化
    delta: DeltaInfo | None  # 与上周对比
```

## RankedPerson（排名条目）

```python
@dataclass
class RankedPerson:
    rank: int              # 排名（1-based）
    name: str              # 显示名
    person_id: str
    wxid: str
    base_score: float      # 加权分数
    composite: float       # 最终分数
    signal_level: str      # 信号等级
    delta_rank: int | None # 排名变化（正=上升，负=下降）
    delta_composite: float | None
    tags: list[str]        # ["riser", "faller", "置顶攻略对象"]
    insufficient_data: bool
```

## Ranking（排名集合）

```python
@dataclass
class Ranking:
    week: str                       # "2026-W24"
    generated_at: str
    rankings: list[RankedPerson]    # 按 composite 降序
    risers: list[RankedPerson]      # 排名上升的人
    fallers: list[RankedPerson]     # 排名下降的人
    insufficient_data: list[InsufficientData]  # 数据不足的人
```

## Stage（关系阶段）

阶段的生命周期：

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
    "冷淡/停滞",   # 兴趣下降
    "退出/失败",   # 基本不再联系或明确拒绝
]
```

```python
@dataclass
class Stage:
    state: StageState       # 当前阶段状态
    override: StageOverride | None  # 手动覆盖
    evidence: list[EvidenceEntry]   # 阶段变化证据

    @property
    def effective_stage(self) -> str:
        """优先返回 override，否则返回 state.current。"""
```

## Event（关系事件）

```python
@dataclass
class Event:
    event_type: str   # FIRST_CHAT / DISCONNECT / RECONNECT / FREQUENCY_UP / FREQUENCY_DOWN / FIRST_FLIRT / CONFESSION / TOGETHER / MILESTONE / SIGNAL_LEVEL_UP / SIGNAL_LEVEL_DOWN / INFO_UPDATE
    date: str         # "2026-06-01"
    detail: str       # 描述
    confidence: float = 1.0  # 置信度
    category: str     # 分类：里程碑/沟通动态/信号变化/关系进展/信息更新
    metadata: dict    # 附加数据
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
class FailureCase:
    person: str
    date: str
    stage: str
    signals: list[str]
    diagnosis: str
    lessons: list[str]
    patterns: list[FailurePattern]  # 关联的失败模式
```

## Strategy（策略）

```python
@dataclass
class Strategy:
    actions: list[Action]  # 推荐行动列表
    risks: list[Risk]      # 风险列表
    reasoning: str         # 推理过程

@dataclass
class Action:
    description: str
    priority: str   # "high" / "medium" / "low"
    timing: str     # "now" / "next_conversation" / "next_date"

@dataclass
class Risk:
    description: str
    severity: str   # "high" / "medium" / "low"
    mitigation: str # 缓解措施
```

## YAML 序列化

所有 model 都支持 `to_dict()` / `from_dict()` 方法，通过 `EntityBase` 基类实现。

```python
from engine.models.metrics import Metrics
m = Metrics(...)
data = m.to_dict()  # → dict
m2 = Metrics.from_dict(data)  # → Metrics
```

排名快照存储在 `data/outputs/rankings/` 下，格式为 YAML。

## 注意事项

1. **MetricValue.confidence**：样本量少于 10 条消息时，confidence 会显著下降。`ranker.py` 会把低信心的人放入 `insufficient_data` 列表。
2. **Stage 与 metrics 的关系**：Stage 是离散的状态，metrics 是连续的 [0,1] 分数。Stage 判断需要结合两者。
3. **DeltaInfo**：只有在有上周快照时才非 None。首次运行周报时 delta 全部为 None。
4. **Interaction pattern**：通过消息量比、发起频率、回复质量综合判断。"provider" 表示你在供养者模式。
