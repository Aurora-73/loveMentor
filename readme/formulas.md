# 公式参考（辅助视角）

> 公式是 chat-skills 遗产的独立体系，通过标注 Wiki 依据做软关联，不是独立决策系统。
> Agent 核验而非套用——读公式结果 → 结合 Wiki 知识核验 → 自己做判断。

---

## 目标 vs 现状（显式区分）

| 维度 | 目标状态（架构.md 描述的理想） | 当前状态（代码现实） |
|------|------------------------------|---------------------|
| 公式来源 | 从 Wiki 知识派生，GitHub 方法论 + 案例反馈三源融合 | chat-skills 遗产的独立体系，未从 Wiki 派生 |
| 公式与 Wiki 关系 | 派生子集（Wiki 是"老师"，公式是"老师讲的公式"） | 软关联（通过标注 Wiki 依据条目建立关联，非派生） |
| 权重来源 | Wiki 知识派生 + 回测调参 | 经验启发值，部分已通过回测校准 |
| 演进路径 | 软关联 → 回测校准 → 逐步向派生关系靠拢 | 见下方"公式演进链条" |

> **避免叙事困惑**：架构.md 描述的是"公式从 Wiki 派生"的目标状态；本文档描述的是"chat-skills 遗产 + 软关联"的当前状态。两者不矛盾——目标是方向，现状是起点。

---

## 公式演进链条

```
chat-skills 遗产公式（独立体系，经验启发值）
  ↓ 标注 Wiki 依据（软关联，当前进度：5/8 公式已标注）
  ↓ 未来回测校准（权重和阈值，用历史案例数据回归）
  ↓ 迭代优化（新案例积累后重新回测）
  ↓ 最终：逐步向架构.md 描述的派生关系靠拢
```

**当前阶段**：第一步（标注 Wiki 依据）。权重和阈值仍为经验值，尚未回测校准。

---

## 公式的三个来源

| 来源 | 例子 | 在公式中的体现 |
|------|------|--------------|
| **Wiki 知识库（软关联）** | `[[IOI（兴趣指标）]]`说"兴趣指标反映意向" | IVI 公式的意图真实度判断 |
| **GitHub 公开方法论** | 社交动力学框架 | IVI 公式的概念结构借鉴 |
| **历史案例反馈** | 实际在一起/断联案例的复盘 | 权重和阈值的回测校准（当前为经验值，待回测） |

> **注意**：当前权重和阈值多为经验启发值，尚未回测校准。未来通过案例数据回归校准。

---

## 公式与 Wiki 的关系

> 只标注实际存在的 Wiki 条目。不存在的条目等 Wiki 补齐后再补，不写"待补充"。

| 公式 | 含义 | Wiki 依据 | 权重来源 | 阈值（参考） |
|------|------|-----------|---------|------------|
| IVI | 意图真实度 | `[[IOI（兴趣指标）]]` | 经验值（待回测） | >1.0 真实好感, <0.5 没戏 |
| SPE | 社交势能 | `[[框架（Frame）]]` | 经验值（待回测） | 0.8-1.5 健康, <0.6 红线 |
| EWS | 升温窗口期 | `[[窗口识别]]` | 经验值（待回测） | >0.8 出击, <0.3 关闭 |
| IS | 真实亲密度 | `[[亲密距离]]` | 经验值（待回测） | >0.5 高亲密度 |
| Gap_Effect | 情绪落差 | `[[推拉]]` | 经验值（待回测） | >0 正向, <0 负向 |
| EEV | 升温期望值 | — | 经验值（待回测） | >0.3 值得出击 |
| CS | 矛盾状态 | — | 经验值（待回测） | >0 欲望占主导 |
| action | 终极决策 | — | 经验值（待回测） | 基于 IVI+SPE+EWS |

**阈值是参考，不是硬规则**。IVI=0.9 不一定比 IVI=1.1 差，要结合 Wiki 框架和上下文判断。

---

## IVI 核验示例（如何通过 Wiki 条目核验公式结果）

```
场景：formula_ivi 返回 IVI=0.5（中性区间）

机械套用（错误）：
  → IVI=0.5 < 0.5 阈值 → 判断"真实没戏" → 建议"止损"

Wiki 核验（正确）：
  → 读 Wiki[[IOI（兴趣指标）]]：IOI 包括主动追问、延续话题、肢体靠近等
  → 查事实档案：她最近 3 次主动发起聊天，追问周末安排
  → 看数据：回复率 0.8，个人化问题比例 0.6
  → 判断：虽然 IVI=0.5 在中性区间，但 Wiki 框架 + 事实档案 + 数据
    都指向好感窗口开放。IVI 偏低可能因为 Pface（公开面具）评估偏高
  → 结论：继续推进，不机械套用 IVI 阈值
```

**核心原则**：公式是"视角"不是"裁判"。Agent 读公式结果 → 结合 Wiki 知识核验 → 自己做判断。

---

## 工作流程

```python
from engine.tools import formula_params, formula_ivi, formula_action

# 第一步：自动参数（从 DB 指标推导）
params = formula_params("小溪")
# → auto: Sp/Fback/Rlatency/Ve/EV/S_cost/Noise/Exp/User_Investment/Scarcity_Loss
# → manual: Pface/Ddepth/Backstage/Cp_Index（需 Agent 根据聊天判断）

# 第二步：代入公式（用 auto 值 + Agent 判断的 manual 值）
ivi = formula_ivi(sp=params["auto"]["Sp"], fback=params["auto"]["Fback"],
                  user_investment=params["auto"]["User_Investment"], pface=0.4)

# 第三步：核验而非套用（参考视角）
action = formula_action(ivi=ivi["ivi"], spe=1.0, ews=0.5)
# → {"action": "拉扯", "reason": "...", "instructions": [...]}
# → 结合 Wiki 知识核验后再决定是否采纳
```

---

## 公式签名

| 公式 | 签名 |
|------|------|
| IVI | `formula_ivi(sp, fback, user_investment, pface)` |
| SPE | `formula_spe(user_ddepth, target_ddepth, target_latency, user_latency)` |
| EWS | `formula_ews(gap_effect, cp_index, eev, scarcity_loss)` |
| IS | `formula_is(backstage, pface)` |
| Gap_Effect | `formula_gap_effect(act, exp)` |
| EEV | `formula_eev(p_succ, escalation_bonus, p_fail, power_drop_risk)` |
| CS | `formula_cs(internal_d, external_r)` |
| action | `formula_action(ivi, spe, ews, cs=0.0, ev=0.5)` |

---

## 自动参数推导

`formula_params(name)` 从数据库指标推导：

| auto 参数 | 推导逻辑 |
|----------|---------|
| `Sp` | max(0.1, qscore_personal × 1.5 + fback_quality × 0.3) |
| `Fback` | fback.normalized |
| `Rlatency` | rlatency.normalized |
| `User_Investment` | 1.0 - neediness_penalty |
| `Scarcity_Loss` | (0.8-msg_vol_trend) × 0.3 + (0.8-latency_trend) × 0.2 |

完整推导逻辑见 `engine/formulas.py` 源码。

---

## 注意事项

1. **manual 参数是关键**：auto 参数只提供基础数据，真正区分分析质量的是 Agent 对 Pface/Ddepth/Backstage 的判断
2. **公式来自 chat-skills 项目**：原项目已删除，公式提取到 `engine/formulas.py`。通过标注 Wiki 依据做软关联
3. **不要死记阈值**：阈值是参考，不是硬规则。结合 Wiki 框架和上下文判断
4. **参数校验**：所有公式函数对参数做类型校验，非数字参数返回错误消息而非抛异常
5. **冲突裁决优先级**：实时数据 > 事实档案 > 事件检测 > 公式计算 > 历史分析。公式结果不能推翻事实和 Wiki 知识
