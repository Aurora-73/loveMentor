# Tests 单元测试

## 概述

`tests/` 存放项目的**单元测试文件**，使用 pytest 框架。测试覆盖核心功能，确保代码质量和回归安全。

## 文件清单

| 文件 | 职责 | 覆盖模块 |
|------|------|---------|
| `conftest.py` | 共享 fixture | 临时数据库、配置、消息数据 |
| `test_formulas.py` | 战态公式测试 | engine/formulas.py |
| `test_metrics.py` | 指标计算测试 | engine/analyzers/metrics.py |
| `test_identity.py` | 身份解析测试 | engine/identity/directory.py |
| `test_signals.py` | 信号检测测试 | engine/agent/signals.py |
| `test_stage_recognizer.py` | 阶段识别测试 | engine/analyzers/stage_recognizer.py |
| `test_structured_tools.py` | 结构化工具测试 | engine/agent/ 下的工具函数 |
| `test_tools_smoke.py` | 工具冒烟测试 | engine/tools.py |
| `test_wcd_client.py` | WCD 客户端测试 | engine/importers/wcd_client.py |
| `test_wiki_retriever.py` | Wiki 检索测试 | engine/knowledge/wiki_retriever.py |
| `test_facts_dedup.py` | 事实档案去重测试 | engine/facts/people_archive.py |

## 测试分类

### 核心模块测试

| 测试文件 | 覆盖内容 |
|----------|---------|
| `test_metrics.py` | 15维指标计算、乘法惩罚、信号等级、互动模式 |
| `test_formulas.py` | IVI/SPE/EWS/IS/Gap_Effect/EEV/CS/action 公式计算 |
| `test_identity.py` | 身份解析、模糊搜索、别名管理、账号绑定 |
| `test_stage_recognizer.py` | 9个关系阶段的自动识别 |

### 工具测试

| 测试文件 | 覆盖内容 |
|----------|---------|
| `test_structured_tools.py` | Agent 工具函数的输入输出契约 |
| `test_tools_smoke.py` | 工具基本可用性测试 |

### 检索测试

| 测试文件 | 覆盖内容 |
|----------|---------|
| `test_wiki_retriever.py` | Wiki 搜索、读取、去重 |

### 数据层测试

| 测试文件 | 覆盖内容 |
|----------|---------|
| `test_facts_dedup.py` | 事实档案去重逻辑 |
| `test_wcd_client.py` | WCD API 客户端 |

## 运行测试

### 运行全部测试

```bash
pytest
```

### 运行单文件测试

```bash
pytest tests/test_metrics.py
```

### 详细输出

```bash
pytest tests/test_metrics.py -v
```

### 失败即停 + 详细 + 不捕获 stdout

```bash
pytest -xvs
```

### 运行特定测试

```bash
pytest tests/test_metrics.py::test_composite_calculation
```

## Fixture 说明

`conftest.py` 提供以下共享 fixture：

| Fixture | 说明 | 用途 |
|---------|------|------|
| `tmp_db` | 临时 SQLite 数据库 | 测试数据库操作 |
| `test_config` | 测试配置对象 | 测试配置相关功能 |
| `test_messages` | 测试消息数据 | 测试指标计算、信号检测 |
| `test_person` | 测试身份对象 | 测试身份解析 |
| `test_wiki_index` | 测试 Wiki 索引 | 测试 Wiki 检索 |

## 测试原则

1. **独立运行**：每个测试用例独立，不依赖其他测试的执行顺序
2. **覆盖边界**：测试正常场景和边界条件
3. **快速执行**：测试应在几秒内完成，不依赖外部服务
4. **不修改真实数据**：使用临时数据库和 mock 对象
5. **断言明确**：断言应清晰表达预期结果

## 测试覆盖率

核心模块测试覆盖率：

| 模块 | 覆盖率 |
|------|--------|
| engine/formulas.py | 高 |
| engine/analyzers/metrics.py | 高 |
| engine/identity/directory.py | 中 |
| engine/analyzers/stage_recognizer.py | 中 |
| engine/knowledge/wiki_retriever.py | 中 |

## 新增测试流程

1. 在对应测试文件中添加新测试用例
2. 运行测试确保通过：`pytest tests/test_xxx.py`
3. 运行全部测试确保无回归：`pytest`
4. 提交代码

## 参考文档

- pytest 配置：`pytest.ini`