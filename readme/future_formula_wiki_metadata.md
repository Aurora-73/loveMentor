# P6 未来工作：公式-Wiki 关系结构化

> 创建日期：2026-07-02  
> 状态：**未来规划，不在当前矫正计划执行范围内**  
> 前置依赖：P1 任务 7（公式标注 Wiki 依据）已完成，为结构化元数据奠定基础

---

## 一、背景

当前矫正计划（P0-P5）已将公式从"决策核心"降为"辅助参考"，并在 `engine/formulas.py` 每个公式函数的 docstring 中标注了 `Wiki 依据:` 行（软关联）。这是第一步——让 Agent 和开发者能看到公式与 Wiki 的对应关系。

但 docstring 标注是"半结构化"的：人在阅读时能理解，但代码无法自动校验、MCP 工具无法自动附带、文档无法自动生成。

**P6 的目标**：将公式到 Wiki 的映射从 docstring 提升为**结构化元数据**，实现机器可读、可校验、可自动消费。

---

## 二、当前状态（P1 完成后）

`engine/formulas.py` 中每个公式函数的 docstring 形如：

```python
def formula_ivi(...):
    """IVI — 意图真实度指数。
    ...
    Wiki 依据: [[IOI（兴趣指标）]]
    参考 GitHub 方法论: 社交动力学
    权重来源: 经验值（待回测）
    阈值（参考，需结合 Wiki 知识核验）：
        IVI > 1.0：口嫌体正直，真实好感
        IVI < 0.5：真实没戏，立即止损
    """
```

**局限**：
1. 无法自动校验 Wiki 条目是否存在（条目改名后 docstring 失效）
2. MCP 工具返回公式结果时无法自动附带 `wiki_basis` 字段
3. 文档需要人工维护，无法从代码自动生成"公式来源于哪些 Wiki"
4. 3 个公式（EEV/CS/action）无 Wiki 依据，无法被结构化追踪缺口

---

## 三、目标状态

### 3.1 结构化元数据方案

**方案 A：Python 模块**（`engine/formula_metadata.py`）

```python
from dataclasses import dataclass

@dataclass
class FormulaWikiMapping:
    formula: str                    # 公式名，如 "IVI"
    wiki_entries: list[str]         # 对应 Wiki 条目标题，如 ["IOI（兴趣指标）"]
    github_methodology: str         # 参考 GitHub 方法论，如 "社交动力学"
    weight_source: str              # 权重来源，如 "经验值（待回测）"
    thresholds: dict[str, str]      # 阈值说明
    notes: str = ""                 # 备注

FORMULA_WIKI_MAP: dict[str, FormulaWikiMapping] = {
    "IVI": FormulaWikiMapping(
        formula="IVI",
        wiki_entries=["IOI（兴趣指标）"],
        github_methodology="社交动力学",
        weight_source="经验值（待回测）",
        thresholds={">1.0": "口嫌体正直", "<0.5": "真实没戏"},
    ),
    "SPE": FormulaWikiMapping(
        formula="SPE",
        wiki_entries=["框架（Frame）"],
        github_methodology="",
        weight_source="经验值（待回测）",
        thresholds={">0.6": "势能领先", "<0.4": "势能落后"},
    ),
    # ... EEV/CS/action 的 wiki_entries 为空列表，表示缺口
}
```

**方案 B：YAML 配置**（`docs/wiki/formula_wiki_map.yaml`）

```yaml
formulas:
  IVI:
    wiki_entries: [IOI（兴趣指标）]
    github_methodology: 社交动力学
    weight_source: 经验值（待回测）
    thresholds:
      ">1.0": 口嫌体正直
      "<0.5": 真实没戏
  SPE:
    wiki_entries: [框架（Frame）]
    github_methodology: ""
    weight_source: 经验值（待回测）
    thresholds:
      ">0.6": 势能领先
      "<0.4": 势能落后
  # EEV/CS/action 的 wiki_entries 为空
```

**推荐方案 A**：Python 模块便于类型检查、IDE 补全、与公式函数同模块；YAML 便于非开发者编辑但缺乏类型安全。考虑到公式与 Wiki 映射是代码级元数据，选 A。

### 3.2 最少支持的功能

1. **测试校验 Wiki 条目是否存在**
   - 新增 `tests/test_formula_wiki_map.py`
   - 遍历 `FORMULA_WIKI_MAP`，对每个 `wiki_entries` 中的条目，用 `WikiIndex` 校验是否存在
   - Wiki 条目改名后测试失败，强制更新映射
   - `wiki_entries` 为空的公式标记为"Wiki 缺口"，测试中 skip 或标记 xfail

2. **MCP 返回公式结果时附带 `wiki_basis`**
   - `mcp_server/tools_formula.py` 中，公式计算后从 `FORMULA_WIKI_MAP` 查映射
   - 返回结果新增字段：`wiki_basis: ["IOI（兴趣指标）"]`、`wiki_paths: ["entities/IOI（兴趣指标）.md"]`
   - Agent 收到公式结果时可直接 `wiki_read` 对应条目核验

3. **文档自动生成**
   - 新增脚本 `tools/gen_formula_wiki_doc.py`
   - 从 `FORMULA_WIKI_MAP` + `engine/formulas.py` docstring 自动生成 `readme/formulas.md` 的"公式与 Wiki 的关系"表格
   - 文档与代码不再脱节

---

## 四、实施步骤

### 阶段 1：结构化元数据落地（1-2 天）
1. 创建 `engine/formula_metadata.py`，定义 `FormulaWikiMapping` 和 `FORMULA_WIKI_MAP`
2. 从 `engine/formulas.py` docstring 提取现有 Wiki 依据，填充 `FORMULA_WIKI_MAP`
3. `engine/formulas.py` docstring 保留人类可读说明，但 `Wiki 依据:` 行改为引用 `formula_metadata.py`（避免两处维护）

### 阶段 2：测试校验（0.5 天）
4. 新建 `tests/test_formula_wiki_map.py`，校验所有 `wiki_entries` 在 WikiIndex 中存在
5. 对 `wiki_entries` 为空的公式（EEV/CS/action），测试中标记为"Wiki 缺口"并记录到 `plan/` 待补清单

### 阶段 3：MCP 工具附带 wiki_basis（0.5 天）
6. 修改 `mcp_server/tools_formula.py`，公式返回结果新增 `wiki_basis` 和 `wiki_paths` 字段
7. 更新 `readme/mcp.md` 公式工具文档，说明返回结构变化

### 阶段 4：文档自动生成（0.5 天）
8. 创建 `tools/gen_formula_wiki_doc.py`
9. 生成 `readme/formulas.md` 的"公式与 Wiki 的关系"表格部分
10. CI 或手动运行，确保文档与代码同步

---

## 五、与当前矫正计划的关系

| 当前矫正计划（P0-P5） | P6 未来工作 |
|----------------------|------------|
| docstring 标注 `Wiki 依据:`（半结构化） | 结构化元数据 `FORMULA_WIKI_MAP`（机器可读） |
| 人工校验 Wiki 条目存在 | 自动测试校验 |
| MCP 工具描述加"辅助参考"前缀 | MCP 返回结果附带 `wiki_basis` 字段 |
| 手动维护 formulas.md 表格 | 脚本自动生成 |

P6 是 P1 任务 7 的自然延伸：P1 完成"软关联"（docstring 标注），P6 升级为"硬关联"（结构化元数据 + 自动校验）。

---

## 六、风险与注意事项

1. **不改公式逻辑**：P6 只改元数据结构和文档生成，不改公式计算逻辑、权重、阈值
2. **不删公式工具**：9 个公式 MCP 工具保留，只增加返回字段
3. **向后兼容**：`wiki_basis` 是新增字段，不破坏现有 Agent 对公式结果的消费方式
4. **Wiki 缺口追踪**：EEV/CS/action 三个公式暂无 Wiki 依据，P6 阶段 2 测试中标记缺口，等 Wiki 补齐后填入
5. **与 SalesCRM 的复用**：`engine/formula_metadata.py` 的结构（`FormulaWikiMapping` dataclass）可复用，但具体映射内容（`FORMULA_WIKI_MAP`）各项目独立

---

## 七、验收标准

1. `engine/formula_metadata.py` 存在，包含所有 8 个公式的映射
2. `tests/test_formula_wiki_map.py` 全绿，能检测 Wiki 条目改名
3. MCP 公式工具返回结果含 `wiki_basis` 字段
4. `tools/gen_formula_wiki_doc.py` 能自动生成 formulas.md 的关系表格
5. 全量测试通过，无回归
