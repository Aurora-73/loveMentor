# 维持关系工作流

> 每周周报后执行，识别需要主动联系的人，并给出具体消息建议。

---

## 工作流概览

```
rank() → 筛选候选人 → metrics()/chat()/evidence() → 分析 → 输出：谁需要联系 + 发什么
```

---

## 第一步：筛选候选人

从排名中筛选需要主动联系的人，规则：

### 信号 1：关系热度下降（最优先）

| 条件 | 含义 |
|------|------|
| `recent > 3` | 最后消息超过 3 天前 |
| `trend < -0.005` | 周变化下降 |
| 未被排除（非"非攻略对象"/"放弃"/"群友"） | 不是无关的人 |

> 注：前置过滤已排除"无信号"等级，因此信号 1 可能包含"弱窗口"/"中窗口"/"强窗口"/"冷淡"任何非"无信号"等级。

### 信号 2：关系窗口但未推进

| 条件 | 含义 |
|------|------|
| `signal_level` 在"弱窗口"或以上 | 有兴趣但没推进 |
| `recent > 1` | 最近 1 天没联系 |
| 无主动邀约记录（events 无 INVITATION） | 还没约过或没推进约会 |

### 信号 3：高潜力但投入不足

| 条件 | 含义 |
|------|------|
| `neediness_penalty > 0.9` | 你投入正常（不是供养者） |
| `recent > 2` | 你 2 天没联系 |

### 候选人数量控制

工作流建议每次输出 **3-5 人**（手动调用时传 `max_people=5`），函数默认上限为 10。按优先级排序：
1. 关系热度下降（信号 1）：优先级最高
2. 关系窗口（信号 2）：次之
3. 高潜力未投入（信号 3）：再次

---

## 第二步：获取上下文

对每个候选人，Agent 调用以下工具获取分析依据：

```python
brief("候选人", compact=True)        # 全局视图
chat("候选人", recent=30)            # 最近 30 条聊天
metrics("候选人")                    # 指标数据
evidence("候选人", section="timeline") # 关系时间线
formula_params("候选人")             # 量化参数
```

---

## 第三步：分析（Agent 自行推理）

Agent 根据数据判断：

1. **当前关系阶段**：初识/高频聊天/暧昧推进/冷淡停滞...
2. **她的信号强度**：IOI 是否明确？是冷淡还是窗口？
3. **你的投入状态**：是否过度投入？是否该拉扯？
4. **上次聊天的氛围**：是自然结束还是中断？她最后一条消息是什么？
5. **她最近的动态**：朋友圈有什么？是否有新变化？

---

## 第四步：输出建议

每人输出一个**具体可发送的消息草稿**，要求：

### 消息规则

1. **context-consistent**：必须基于实际聊天内容，不编造不存在的叙事
2. **有 hooks**：消息要能让对方有理由回复（问句/分享/轻推拉）
3. **匹配阶段**：
   - 初识：轻松话题，不要压力
   - 高频聊天：分享生活 + 轻微推拉
   - 暧昧推进：升温试探，可以是邀约
   - 冷淡停滞：低频率试探，不要暴露需求感
4. **不超过 2 句话**：简短，不给她压力

### 好消息示例

- "在干嘛" → "在干嘛"（不是好的，太泛）
- "在干嘛" → "刚在XX遇到你上次说的那个XX，突然想起你" → **有具体回忆 + 分享**
- "周末出来" → "周末XX有个XX活动，要不要一起去看看" → **具体邀约 + 低压力**

### 输出格式

```
## 维持关系提醒（本周）

### 1. 小鱼（排名 #3，信号：冷淡，最后联系：3 天前）
- 关系状态：暧昧推进，IOI 明确，但 3 天没联系
- 上次聊天：她主动发了吃的，你回了表情
- 建议消息："今天吃到一家XX，想起你说过XX，下次你来XX带你"
- 原理：延续她上次的话题，具体邀约，低压力

### 2. 白开水（排名 #5，信号：弱窗口，最后联系：5 天前）
...
```

---

## 工作流触发

两种方式：

**方式 A：每周自动**（建议周日晚上）
- 周报完成后自动触发
- 输出 `data/outputs/reports/maintain_weekXX.md`

**方式 B：手动触发**
- 用户说"谁需要联系"或"维持关系分析"
- 立即执行

---

## 注意事项

1. **不要过度打扰**：如果她明确冷淡（信号等级=冷淡且 recent > 7），不要建议主动联系，等她先动
2. **不要群发式**：每个人的消息必须不同，不能套模板
3. **结合当前状态**：如果她最近朋友圈发了和别的男生的照片，建议里要提到这个信号，不要盲目建议
4. **尊重"放弃"标签**：已标记"放弃"的人不进入候选
5. **不要超过 5 人**：你是去建立真实连接，不是做客户维护

---

## 实现方案

已实现两个工具函数（见 `engine/agent/maintain.py`）：

```python
def maintain_candidates(max_people: int = 10) -> list[Candidate] | str:
    """筛选需要维持关系的候选人。

    逻辑：
    1. 从未排除的联系人中，按 composite 排序
    2. 过滤 recent_days > 1（超过 1 天没联系）
    3. 过滤 signal_level 不是"无信号"
    4. 按优先级排序：
       - 热度下降（recent > 3 且 trend < -0.005）最优先
       - 有窗口但未推进（signal_level ≥ 弱窗口 且 recent > 1）次之
       - 高潜力未投入（neediness_penalty > 0.9 且 recent > 2）再次
    5. 返回 top N

    返回 list[Candidate] 或错误字符串。
    """
```

`Candidate` 数据结构：

```python
@dataclass
class Candidate:
    name: str                    # 显示名
    person_id: str               # person_id
    wxid: str                    # 主微信号
    rank: int                    # 排名
    composite: float             # composite 分数
    signal_level: str            # 信号等级
    recent_days: float           # 最后联系天数
    trend: float                 # 趋势变化
    neediness_penalty: float     # 需求感惩罚
    interaction_pattern: str     # 互动模式
    last_msg_summary: str        # 最后消息摘要
    reason: str                  # 筛选原因（热度下降/窗口未推进/高潜力未投入/需关注）
```

```python
def format_candidates(candidates: list[Candidate]) -> str:
    """格式化候选人为 Markdown（含上次消息摘要、消息建议规则）。"""
```

**使用流程**：

```python
from engine.tools import maintain_candidates, format_candidates

candidates = maintain_candidates(max_people=5)
print(format_candidates(candidates))

# 对每个候选人获取详细数据
for c in candidates:
    brief_data(c.name)
    chat_data(c.name, recent=30)
    metrics(c.name)
    # Agent 分析后给出消息建议
```

**筛选优先级**：

| 优先级 | 原因 | 条件 |
|--------|------|------|
| 1 | 热度下降 | recent > 3 且 trend < -0.005 |
| 2 | 窗口未推进 | signal_level ≥ 弱窗口 且 1 < recent ≤ 3 |
| 3 | 高潜力未投入 | neediness_penalty > 0.9 且 recent > 2 |
| 4 | 需关注 | 其他符合条件的 |
