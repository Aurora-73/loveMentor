# Engine Backtest 回测框架

## 概述

回测框架用于验证 loveMentor 系统参数的合理性。核心思想是：**以已知结果的历史案例作为 ground truth，反向审判系统参数是否合理**。

## 目录结构

```
engine/backtest/
├── __init__.py
├── collect.py           # 数据采集（Phase A/B）
├── analyze.py           # 案例内时序分析 + 跨案例归纳
├── calibrate.py         # 校准闭环 + 留一验证
├── validate.py          # 数据验证
├── config/
│   └── cases.yaml       # 案例定义（从 data/system/ 迁移）
├── outputs/             # 回测输出（自动创建）
└── README.md
```

## 核心目标

| 目标 | 描述 |
|------|------|
| 验证指标区分力 | composite/neediness_penalty 是否能有效区分成功/失败案例 |
| 诊断 composite 公式 | 识别公式权重是否合理，阈值是否恰当 |
| 分析信号预警能力 | 系统能否在关系破裂前发出有效预警 |
| 审计 neediness_penalty | 需求感惩罚的触发条件是否符合实际情况 |
| 校准阈值 | 通过描述性统计调整关键参数阈值 |

## 使用方式

```bash
# 采集所有案例（Phase A）
python -m engine.backtest.collect

# 采集公式层（Phase B）
python -m engine.backtest.collect --phase B

# 验证数据完整性
python -m engine.backtest.validate

# 分析采集数据
python -m engine.backtest.analyze

# 运行校准闭环
python -m engine.backtest.calibrate
```

## 参考文档

- `readme/backtest.md` - 回测框架详细文档
- `plan/回测方案.md` - 框架设计文档
- `plan/回测案例.md` - 案例分类定义