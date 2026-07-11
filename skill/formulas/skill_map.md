---
name: formula-skill-map
description: 公式与Skill的映射关系 — 每个公式对应哪个Wiki框架
---

# 公式-Skill 映射

## 映射总览

| 公式 | Wiki依据 | Skill参考 | 下一步建议 |
|------|----------|-----------|-----------|
| formula_calc_ivi | [[IOI（兴趣指标）]] | `signals/basic_signals.md` | `wiki_context("IOI")` |
| formula_calc_spe | [[框架（Frame）]] | `signals/manipulation_signals.md` | `wiki_search("框架")` |
| formula_calc_ews | [[窗口识别]] | `workflows/analysis.md` | `wiki_search("窗口")` |
| formula_calc_is | [[亲密度]] | `signals/basic_signals.md` | `wiki_search("亲密")` |
| formula_calc_gap_effect | [[情绪波动]] | `signals/basic_signals.md` | `wiki_search("情绪")` |
| formula_calc_eev | [[行动决策]] | `workflows/analysis.md` | `wiki_search("决策")` |
| formula_calc_cs | [[矛盾]] | `signals/manipulation_signals.md` | `wiki_search("矛盾")` |
| formula_calc_action | [[行动决策]] | `workflows/analysis.md` | `wiki_search("行动")` |

---

## 使用流程

```
1. formula_get_params(name)     # 获取公式参数
2. formula_calc_ivi(...)        # 计算公式
3. wiki_context("IOI")           # 根据公式结果查Wiki
4. wiki_read("...")             # 读取Wiki全文
5. 结合Wiki知识判断              # 不机械套用公式阈值
```

---

## 公式核验示例

**场景**：`formula_calc_ivi` 返回 IVI=0.5（中性区间）

**错误做法**：
```
IVI=0.5 < 1.0 → "没戏" → 放弃
```

**正确做法**：
```
1. 查 Wiki [[IOI（兴趣指标）]]
2. 看聊天记录：对方最近3次主动询问你的情况
3. 看指标：回复速度快，回复质量高
4. 判断：虽然IVI中等，但实际是IOI信号
```

---

## 冲突裁决

当公式结果与 Wiki 知识矛盾时，区分两种冲突：

| 类型 | 裁决方式 |
|------|---------|
| **数据冲突**（公式输出 vs 实时数据） | 实时数据为准，不可推翻 |
| **解释冲突**（公式阈值判断 vs Wiki 框架解读） | Wiki 框架决定怎么看，公式只做辅助参考 |

**原则**：Wiki 是解释框架，不是数据源。Wiki 决定怎么看数据，实时数据决定发生了什么。公式结果只能作为辅助参考视角，不能推翻实时数据和 Wiki 框架。