# Models 数据模型

## 概述

`engine/models/` 定义了系统中所有**数据模型**，使用 dataclass 实现，用于结构化数据的传输和处理。这些模型是分析引擎、Agent 工具和事实档案之间的数据契约。

## 架构定位

```
数据库查询（SQLite）
    │
    └── engine/models/（数据模型）
            │
            ├── base.py           → 基础模型
            ├── profile.py        → 身份信息
            ├── metrics.py        → 指标数据
            ├── stage.py          → 关系阶段
            ├── strategy.py       → 策略建议
            ├── evaluation.py     → 评估记录
            ├── event.py          → 事件记录
            ├── failure.py        → 失败案例
            ├── ranking.py        → 排名数据
            └── date_review.py    → 约会回顾
                    │
                    ▼
            engine/analyzers/ 和 engine/agent/ 使用这些模型
```

## 模块清单

| 文件 | 职责 | 核心模型 |
|------|------|---------|
| `base.py` | 基础模型 | BaseModel, IdentityPerson, IdentityAccount, IdentityAlias |
| `profile.py` | 身份信息 | PersonProfile, ContactInfo |
| `metrics.py` | 指标数据 | MetricsData, SignalLevel, InteractionPattern, DynamicSignal |
| `stage.py` | 关系阶段 | StageResult, StageInfo, StageSignal |
| `strategy.py` | 策略建议 | StrategyResult, ActionStep, RiskItem |
| `evaluation.py` | 评估记录 | EvaluationRecord, EvidenceReference |
| `event.py` | 事件记录 | EventRecord, EventType |
| `failure.py` | 失败案例 | FailureRecord |
| `ranking.py` | 排名数据 | RankingResult, RankItem |
| `date_review.py` | 约会回顾 | DateReview |

## 核心模型详解

### base.py

**IdentityPerson**：身份目录中的 Person 模型

```python
@dataclass
class IdentityPerson:
    person_id: str
    display_name: str
    accounts: list[IdentityAccount]
    aliases: list[IdentityAlias]
```

**IdentityAccount**：微信账号模型

```python
@dataclass
class IdentityAccount:
    account_id: str
    wxid: str
    created_at: datetime
```

**IdentityAlias**：别名模型

```python
@dataclass
class IdentityAlias:
    alias_id: str
    alias_type: str  # fake_name/pinyin/real_name/manual
    value: str
    privacy_level: str  # public/private
```

### metrics.py

**MetricsData**：完整指标数据模型

```python
@dataclass
class MetricsData:
    composite: float
    signal_level: str  # 强窗口/中窗口/弱窗口/冷淡/无信号
    interaction_pattern: str  # lover/provider/neutral
    neediness_penalty: float
    fback: float
    rlatency: float
    fback_quality: float
    qscore_personal: float
    trend: float
    # ... 其他 11 个指标
    dynamic_signals: list[DynamicSignal]
```

**SignalLevel**：信号等级枚举

| 等级 | 阈值 | 含义 |
|------|------|------|
| 强窗口 | >= 0.70 | 强烈兴趣信号 |
| 中窗口 | >= 0.50 | 中等兴趣信号 |
| 弱窗口 | >= 0.30 | 微弱兴趣信号 |
| 冷淡 | >= 0.15 | 冷淡 |
| 无信号 | < 0.15 | 无兴趣 |

**InteractionPattern**：互动模式枚举

| 模式 | 特征 |
|------|------|
| lover | 高回复质量、高个人化问题、低需求感 |
| provider | 高工具化问题、低个人化问题 |
| neutral | 中等各项指标 |

### stage.py

**StageResult**：关系阶段识别结果

```python
@dataclass
class StageResult:
    current_stage: str  # 初识/有基本互动/高频聊天/已约见/持续接触/暧昧推进/关系确认/冷淡/退出
    confidence: float
    signals: list[StageSignal]
    blockers: list[str]
```

### strategy.py

**StrategyResult**：策略建议

```python
@dataclass
class StrategyResult:
    stage: str
    confidence: float
    diagnosis: str
    strategy: str
    risks: list[RiskItem]
    action_steps: list[ActionStep]
    evidence_refs: list[EvidenceReference]
```

### evaluation.py

**EvaluationRecord**：评估记录

```python
@dataclass
class EvaluationRecord:
    timestamp: datetime
    text: str
    source: str  # manual/analysis/agent
```

**EvidenceReference**：证据引用

```python
@dataclass
class EvidenceReference:
    message_id: str
    quote: str
    note: str
```

### ranking.py

**RankingResult**：排名结果

```python
@dataclass
class RankingResult:
    items: list[RankItem]
    snapshot_time: datetime
    total_contacts: int
```

**RankItem**：排名项

```python
@dataclass
class RankItem:
    rank: int
    display_name: str
    person_id: str
    composite: float
    signal_level: str
    last_message_date: str
    message_count: int
```

## 设计原则

1. **不可变数据**：模型数据从数据库读取后不应修改
2. **类型安全**：使用 dataclass 确保类型检查
3. **序列化友好**：支持 JSON 序列化，用于 API 返回和文件存储
4. **向后兼容**：新增字段必须有默认值

## 模型使用场景

| 模型 | 使用场景 |
|------|---------|
| IdentityPerson | 身份解析、联系人管理 |
| MetricsData | 指标计算、分析报告 |
| StageResult | 关系阶段识别、策略建议 |
| StrategyResult | 分析结论保存、对比分析 |
| RankingResult | 排名展示、周报生成 |
| EvaluationRecord | 事实档案、评估记录 |
| EventRecord | 事件检测、时间线展示 |

## 参考文档

- 模型详细文档：`readme/models.md`
