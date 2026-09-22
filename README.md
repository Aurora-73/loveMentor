<p align="center">
  <h1 align="center">LoveMentor</h1>
</p>

<p align="center">
  <em>完全本地运行的对话观察与关系决策辅助系统</em>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.13+-blue?logo=python" alt="Python">
  <img src="https://img.shields.io/badge/platform-Windows-lightgrey" alt="Platform">
  <img src="https://img.shields.io/badge/MCP-49%20tools-green?logo=claude" alt="MCP Tools">
  <img src="https://img.shields.io/badge/license-MIT-yellow" alt="License">
  <img src="https://img.shields.io/badge/PRs-welcome-brightgreen" alt="PRs welcome">
  <a href="https://github.com/Aurora-73/loveMentor/issues?q=state%3Aopen%20label%3A%22good%20first%20issue%22"><img src="https://img.shields.io/github/issues/Aurora-73/loveMentor/good%20first%20issue?label=good%20first%20issues" alt="Good first issues"></a>
  <img src="https://img.shields.io/badge/status-active-brightgreen" alt="Status">
</p>

<p align="center">
  <strong>本地数据 · 可观测信号 · 可解释分析 · 谨慎行动建议</strong>
  <br><br>
  <b>代码负责数据，Agent 负责推理。</b>
</p>

---

![LoveMentor hero cover](readme/assets/hero-cover-captioned.png)

> 图片说明：本 README 中的全部人物图片均由 AI 生成，仅作产品视觉演示。人物、场景和关系均为虚构，不代表真实用户、聊天记录或互动经历。

**项目自身不会上传聊天记录。** 先用合成演示体验输出；接入真实数据时，数据由本地程序处理和保存。若你显式使用云端大模型，发送给模型的内容将由相应服务商处理。

```bash
git clone https://github.com/Aurora-73/loveMentor.git
cd loveMentor
python -m lovementor.demo
```

> 初学者友好：欢迎文档、测试、示例、Bug 修复和功能 PR。维护者会认真 Review，并尽量在 7 天内回复 Issue 和 PR。请从 [贡献指南](CONTRIBUTING.md) 或 GitHub 上的 `good first issue` 开始。

## 目录

- [为什么需要 LoveMentor](#为什么需要-lovementor)
- [设计理念](#设计理念)
- [功能特性](#功能特性)
- [公开案例](#公开案例)
- [快速开始](#快速开始)
- [架构设计](#架构设计)
- [对比](#对比)
- [项目结构](#项目结构)
- [文档索引](#文档索引)
- [参与贡献](#参与贡献)
- [路线图](#路线图)
- [License](#license)

---

## 为什么需要 LoveMentor

在亲密关系中，人容易陷入"当局者迷"的状态。问题往往是相通的：

| 问题 | 后果 |
|------|------|
| 对方到底有没有好感？ | 过度解读或错过窗口期，全靠朋友参谋 |
| 聊了很多但关系没推进 | 停留在"友谊区"或信息层面，没有情感升级 |
| 气氛不对但看不出原因 | 没有指标追踪，只能凭感觉判断 |
| 不知道下一步该怎么做 | 缺乏方法论指导，被动等待 |

**LoveMentor 做的事：** 自动同步微信聊天记录 → 量化为可观测行为指标 → 结合专业恋爱知识库推理 → 生成分析建议。

**不做的：** 不是自动回复工具、不是 PUA 话术库、不替你做决策。

---

## 设计理念

```
聊天文本 → 可观测行为检测 → 指标量化 → 知识库推理 → 分析建议
    模型只做文本特征提取      引擎做关系判断    Agent 做综合输出
```

系统不试图让 AI "猜对方是否喜欢你"，而是：

1. **检测文本中可观测的行为信号**（提问、分享、暧昧、敷衍等）
2. **量化行为统计指标**（回复速度、消息量、情绪波动等）
3. **用专业恋爱知识框架进行推理**
4. **输出结构化的分析报告和 actionable 建议**

### 标签分层架构

```
Layer 1: Observable Behavior（模型输出）
──────────────────────────────────────────
模型只回答"这段聊天里出现了哪些可观测的文本特征？"
- question_asking / flirt / self_disclosure
- invitation / perfunctory / framing_boundary
- 共 10 个文本行为标签

Layer 2: Derived Behavior Signals（engine 层聚合）
──────────────────────────────────────────
engine 层将行为观测 + 统计指标 + 事件数据
聚合为派生行为信号（客观统计，非关系判断）：
interest_signal   = f(question_asking, self_disclosure, flirt, invitation, ...)
friendzone_risk   = f(framing_boundary, perfunctory, stagnation, ...)
emotion_balance   = emotion_positive / emotion_negative 计数比
```

---

## 功能特性

### 数据自动同步

从微信自动拉取聊天记录、联系人、朋友圈数据，无需手动录入。支持两种后端：

| 后端 | 原理 | 优势 | 局限 |
|------|------|------|------|
| **WCD** ([WeChatDataAnalysis](https://github.com/LifeArchiveProject/WeChatDataAnalysis)) | 解密微信本地 SQLite 数据库 | 数据完整、支持朋友圈 | 需 Windows + 解密环境 |
| **WeFlow** ([WeFlow](https://github.com/hicccc77/WeFlow)) | HTTP API 拉取 | 跨平台、部署简单 | 功能相对受限 |

同步特性：
- 增量同步（默认），基于 checkpoint 避免重复拉取
- 按人同步（`sync_person`），分析单个人前快速刷新
- 朋友圈互动同步
- 自动解密（WCD 后端），无需手动干预

### 22 维指标体系

| 类别 | 指标 | 含义 |
|------|------|------|
| **互动** | `fback` / `rlatency` | 回复字数比 / 速度比 |
| **质量** | `fback_quality` / `qscore_personal` | 回复质量 / 个性化问题 |
| **情绪** | `escore` / `escore_volatility` | 情绪表达 / 情绪波动 |
| **主动** | `her_initiation_rate` / `topic_continuation` | 她的主动发起率 / 话题延续率 |
| **活跃** | `recent` / `active_days` / `msg_count` | 最后活跃 / 活跃天数 / 消息量 |
| **朋友圈** | `moments` | 朋友圈互动频率 |
| **趋势** | `trend` / `msg_volume_trend` / `latency_trend` | 周变化趋势 |
| **语义** | `semantic_flirt` / `semantic_invitation` / `semantic_emotion_balance` | 暧昧程度 / 邀约积极性 / 情绪平衡 |
| **Wiki 衍生** | `reply_quality` / `session_balance` / `emotional_temperature` | 回复质量 / 会话对等性 / 情绪温度 |
| **惩罚** | `neediness_penalty` | 消息占比过高时降权 |

输出信号等级：**强窗口** / **中窗口** / **弱窗口** / **冷淡** / **无信号**

互动模式分类：`lover` / `provider` / `neutral`

### 语义分析：把“感觉”拆成可观察的信号

系统不把一句话或一次点赞解释为关系结论，而是识别十类文本行为（如提问、分享、邀约、边界表达），再与回复节奏、话题延续和互动趋势结合。

- **规则与模型双参考**：`source="rule"` 适合快速解释；`source="macbert"` 用于语义推理和交叉核验。
- **角色感知分析**：支持区分对话双方，避免把同一句话放错语境。
- **派生信号而非判决**：`interest_signal`、`friendzone_indicator`、`engagement_depth` 等只提示下一步需要核验的方向。
- **本地数据不随仓库发布**：训练数据、模型权重和个人聊天内容均不包含在公开仓库中。

模型输出始终是辅助证据。它不替用户判断他人意图，也不鼓励操纵、纠缠或越过边界。

### 回测框架

以已知结果的历史案例作为 ground truth，反向审判系统参数是否合理：

- **案例内时序分析**：同一案例不同阶段切片对比，识别转折点
- **描述性统计**：分布表、重叠区间、均值差异（不做推断统计）
- **留一验证**：Leave-One-Case-Out 验证参数稳定性
- **语义回测**：用 MacBERT 分析聊天内容，验证语义指标区分力
- **全量扫描**：从多个对象的汇总趋势中发现值得复核的变化

### 公开案例

仓库附带的是**合成、不可回溯**的案例：它们展示“可观测信号 → 推理框架 → 低压力行动”的过程，不包含原始聊天、联系人信息或精确时间线。

![LoveMentor synthetic relationship overview](readme/assets/relationship-overview-captioned.png)

> 上图中的人物和界面均为 AI 生成的合成视觉素材；卡片仅表达分析概念，不含真实聊天或个人数据。

| 案例 | 你会看到什么 |
|------|--------------|
| [窗口降温](examples/window-cooling.md) | 邀约没有被接住时，如何降低投入并观察后续信号 |
| [朋友信号 ≠ 浪漫信号](examples/friend-signal-vs-romantic.md) | 如何避免把低成本友好误读为浪漫窗口 |
| [冲突修复](examples/boundary-repair.md) | 为什么先处理边界与修复，再讨论关系推进 |
| [分数滞后](examples/score-lag.md) | 为什么综合分较高时，仍要重视近期的延期与行动反馈变化 |
| [话题失配](examples/topic-mismatch.md) | 为什么消息很多，却仍没有形成自然推进的共同体验 |

案例的完整脱敏标准见 [examples/README.md](examples/README.md)。

### 事件检测

自动识别关系关键节点：

| 事件 | 含义 |
|------|------|
| `FIRST_CHAT` | 首次聊天 |
| `DISCONNECT` | 连续 N 天无消息 |
| `RECONNECT` | 断联后恢复 |
| `FREQUENCY_UP/DOWN` | 消息频率变化 |
| `STAGE_CHANGE` | 关系阶段变化 |

### Wiki 知识库（推理主轴）

内置 OKF 格式恋爱知识库，涵盖：

- **实体框架** — IOI、IOD、窗口信号、友谊区、需求感
- **场景决策** — 邀约策略、升温节奏、断联处理、暧昧升级
- **主题综述** — 推拉、废物测试、情绪价值、长期关系
- **方法论** — 阶段识别、关系评估框架

**关键设计：** Wiki 是 Agent 的推理主轴。Agent 先检索方法论再分析数据，每个判断引用 Wiki 条目作为依据。

### 辅助参考公式

| 公式 | 含义 | 用途 |
|------|------|------|
| IVI | 意图真实度 | 区分真心 vs 敷衍 |
| SPE | 社交势能 | 对话投入平衡度 |
| EWS | 升温窗口期 | 最佳升温时机 |
| IS | 真实亲密度 | 表面 vs 实际亲密度 |
| Action | 策略决策 | 进攻/拉扯/重置/维持 |

公式是**辅助参考**，不机械套阈值。Agent 核验公式结果，最终以 Wiki 方法论 + 事实档案为准。

### MCP 服务器

全部工具通过 [FastMCP](https://github.com/jlowin/fastmcp) stdio 协议暴露，兼容 Claude Desktop / Cursor：

- **23 只读** — brief / chat / metrics / rank / wiki_search 等
- **写入** — note / date / evaluate / save_analysis / evidence 等
- **公式** — IVI / SPE / EWS / IS / Action 等

AI 可直接驱动完整分析工作流。

---

## 快速开始

### 环境要求

- Python 3.13+（演示模式无需额外依赖）
- 真实数据后端（二选一，可选）：
  - [WCD (WeChatDataAnalysis)](https://github.com/LifeArchiveProject/WeChatDataAnalysis) — Windows，需解密环境
  - [WeFlow](https://github.com/hicccc77/WeFlow) — 跨平台，轻量部署

### 安装

```bash
# 1. 克隆仓库并体验合成演示（无需微信、WCD 或 WeFlow）
git clone https://github.com/Aurora-73/loveMentor.git
cd loveMentor
python -m lovementor.demo

# 2. 如需开发核心功能，安装依赖
pip install pyyaml fastmcp pydantic pytest
# OCR（可选）：pip install rapidocr-onnxruntime Pillow

# 3. 接入真实数据前，按下方配置可选 Provider
```

### 配置

编辑 `data/system/config.yaml`：

```yaml
weflow:
  backend: wcd                    # wcd 或 weflow
  base_url: "http://127.0.0.1:10392"
  token: "your_token_here"
my_wxid: "wxid_xxxxxxxx"
```

### 同步数据

```bash
# 全量同步（首次使用）
python -c "from engine.tools import sync; sync(mode='full')"

# 同步单个人（分析前快速刷新）
python -c "from engine.tools import sync_person; sync_person('姓名')"

# 查看全局排名
python -c "from engine.tools import rank; print(rank())"

# 查看人物概览
python -c "from engine.tools import brief; print(brief('姓名'))"
```

### 启动 MCP 服务器（可选）

```bash
python -m mcp_server.server
```

接入 Claude Desktop / Cursor 后，Agent 可直接完成分析、判断、记录。

### 常用操作速查

```python
from engine.tools import sync_person, brief, chat, metrics, rank
from engine.tools import wiki_search, note, date, events, save_analysis

# 分析流程
sync_person("姓名")
overview = brief("姓名")                    # 概览（指标+事件+信号）
history = chat("姓名", recent=100)          # 最近聊天
m = metrics("姓名")                          # 详细指标
wiki_search("窗口识别 IOI")                  # 查方法论

# 记录事实
note("姓名", "她说下周末有空出来吃饭")
date("姓名", date_text="2026-07-12", location="咖啡厅", rating=4)

# 检测事件
events("姓名", scan=True)

# 保存分析报告
save_analysis("姓名", stage="暧昧期", strategy="邀约推进", ...)
```

完整工具清单见 [readme/tools.md](readme/tools.md)。

---

## 架构设计

![LoveMentor relationship journey](readme/assets/relationship-journey-captioned.png)

> 上图为 AI 生成的概念插画，用于说明“回顾互动 → 发现变化 → 理解彼此 → 审慎行动”的使用旅程。

### 核心原则

**代码负责数据，Agent 负责推理。**

系统提供完整的数据采集、指标计算、语义分析、事实存储管线，而分析和决策全部交给 AI Agent (Claude Code)。代码层不写死业务逻辑，Agent 参考 Wiki 方法论 + 量化指标 + 事实档案做综合判断。

### 完整数据流

```text
微信客户端
    │
    ▼  WCD / WeFlow HTTP API
┌──────────────────────────────────────────────┐
│           importers/（同步管道）               │
│   sync_messages / sync_contacts / sync_moments│
└──────────────────────┬───────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────┐
│         core.db (SQLite 本地数据库)            │
│   messages / contacts / conversations / moments│
└──────────────────────┬───────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────┐
│            analyzers/（分析引擎）               │
│   22 维指标 · 事件检测 · 排名 · 阶段识别       │
└──────────────────────┬───────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────┐
│        Agent 工具层 (engine/tools.py)          │
│   包装所有数据操作，禁止直接查数据库            │
└──────────────────────┬───────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────┐
│             Agent 推理循环                    │
│                                               │
│   ① 读 Wiki 找方法论框架                      │
│      └─ 搜索 IOI、窗口信号、友谊区等           │
│                                               │
│   ② 查事实档案了解历史                       │
│      └─ 读取 facts + 历史分析结论              │
│                                               │
│   ③ 看实时聊天和指标                         │
│      └─ brief / chat / metrics / status       │
│                                               │
│   ④ 核验公式获取量化参考                     │
│      └─ IVI / SPE / EWS / IS / Action         │
└───────────────────────────────────────────────┘
```

### 语义分析管线

```text
聊天文本
    │
    ▼
Conversation Window (20轮滑动窗口)
    │
    ├────→ 规则 baseline（Phase 0，✅ 完成）
    │       10 个可观测行为标签 · kappa 0.885
    │
    ├────→ 人工标注 2099 条（Phase 1，✅ 完成）
    │       放弃 Qwen3，纯人工标注
    │
    └────→ MacBERT ONNX 分类器（Phase 2 + B2 部署，✅ 完成）
            本地 1660Ti · ONNX 部署 · 双参考机制
                │
                ├─ B0' (roleless) ── 回退基线
                └─ B2 (role-aware) ── 默认生产模型
                     │
                     ▼
    Layer 2 融合为关系指标 → 融入 composite → Agent
```

### 身份解析流程

```text
输入: "姓名"
    │
    ▼
engine/identity/directory.py
    │
    ├─ ① 精确匹配 (person_id / wxid)
    ├─ ② 别名匹配 (contact_aliases.value_norm)
    ├─ ③ 模糊搜索 (display_name / remark / nickname)
    └─ ④ 最佳匹配排序
    │
    ▼
输出: Person 对象（含全部 account + alias）
```

---

## 对比

| 维度 | LoveMentor | 情感咨询 App | 自己琢磨 |
|------|-----------|-------------|---------|
| 数据来源 | 微信自动同步 | 手动记录 | 全靠记忆 |
| 量化分析 | 22 维指标 + 10 行为标签 + 公式 + 回测校准 | 无 | 无 |
| 方法论 | 内置 Wiki 知识库 | 通用文章 | 碎片化 |
| 推理 | Agent 基于数据做分析 | 人工回复 | 自己猜 |
| 客观性 | 量化指标 + 事实档案 | 主观判断 | 极度主观 |
| 数据安全 | **项目自身完全本地运行** | 上云 | 无 |
| 部署成本 | 本地搭环境，0 费用 | 付费订阅 | 0 |
| 隐私 | 项目不主动上传；云端模型调用取决于用户配置 | 上传服务器 | 无 |

---

## 项目结构

```text
loveMentor/
│
├── engine/                         # 核心引擎
│   ├── tools.py                    # Agent 工具统一入口
│   ├── formulas.py                 # 辅助公式 (IVI/SPE/EWS/IS)
│   ├── config.py                   # 配置管理
│   │
│   ├── agent/                      # Agent 工具实现
│   │   ├── core.py                 # 共享基础设施
│   │   ├── brief.py / chat.py      # 数据读取
│   │   ├── write.py / evidence.py  # 数据写入与档案
│   │   ├── report.py / signals.py  # 报告与信号
│   │   ├── identity_ops.py         # 身份操作
│   │   └── sync_agent.py           # 同步入口
│   │
│   ├── analyzers/                  # 分析引擎
│   │   ├── metrics.py              # 22 维指标（16 行为统计 + 6 Wiki 衍生 + 3 语义）
│   │   ├── semantic.py             # Layer 2 语义融合引擎
│   │   ├── ranker.py               # 联系人排名
│   │   ├── events.py               # 事件检测
│   │   ├── stage_recognizer.py     # 关系阶段识别
│   │   └── weekly_report.py        # 周报生成
│   │
│   ├── backtest/                   # 回测框架
│   │   ├── config/cases.yaml       # 案例定义+切片级标签
│   │   ├── collect.py              # Phase A/B 数据采集
│   │   ├── analyze.py              # 案例内时序分析+描述性统计
│   │   ├── calibrate.py            # 留一验证+校准候选值
│   │   └── semantic_backtest.py    # 语义回测验证
│   │
│   ├── identity/                   # 身份目录
│   │   └── directory.py            # Person→Account→Alias
│   │
│   ├── facts/                      # 事实档案
│   │   ├── people_archive.py       # 联系人档案
│   │   └── failure_archive.py      # 失败案例
│   │
│   ├── importers/                  # 同步管道
│   │   ├── sync.py                 # 同步调度
│   │   ├── wcd_client.py           # WCD 后端
│   │   ├── weflow_client.py        # WeFlow 后端
│   │   └── db_init.py              # 数据库初始化
│   │
│   └── knowledge/                  # Wiki 检索
│       ├── wiki_index.py           # 索引构建
│       ├── wiki_retriever.py       # 五维度检索
│       └── wiki_context.py         # 上下文组装
│
├── mcp_server/                     # MCP 服务器
│   ├── server.py                   # FastMCP 入口
│   ├── tools_read.py               # 只读工具
│   ├── tools_write.py              # 写入工具
│   ├── tools_formula.py            # 公式工具
│   ├── tools_config.py             # 配置管理
│   └── tests/                      # 集成测试
│
├── ml/                             # 语义分析与训练管线（公开仓库不含训练数据）
│   ├── dataset/                    # 2083 条微信标注 + 11592 条外部数据（去重后）
│   │   ├── samples_phase0.jsonl    # 微信对话样本（2099 条原始）
│   │   ├── batches/                # 外部数据批次（batch_001~014.jsonl，每批 1000 条）
│   │   └── annotations/            # 标注结果 + me_side_pilot_v1 候选集
│   ├── lexicons/                   # 10 个 YAML 行为词典
│   ├── rules/                      # 规则 baseline + MacBERT ONNX 推理（B0'/B2 双实例）
│   ├── models/                     # MacBERT 模型权重（.gitignored）
│   │   ├── baseline_b0_prime/      #   B0' roleless 基线
│   │   └── b2_role_balanced/       #   B2 role-aware 默认模型
│   ├── evaluation/                 # 评估工具
│   ├── scripts/                    # 标注/训练/推理/拆分脚本
│   ├── LABELING_GUIDE.md           # 标注标准（10 个行为维度，0-9 评分）
│   └── ANNOTATION_PROMPT.md        # LLM 批量标注提示词模板
│
├── skill/                          # Agent Skill 文件
├── readme/                         # 模块文档
├── tests/                          # 单元测试
├── docs/wiki/                      # 恋爱知识库（独立仓库）
└── data/                           # 本地数据 (.gitignored)
```

---

## 文档索引

| 文档 | 说明 |
|------|------|
| [PROJECT.md](readme/PROJECT.md) | 项目总览、架构说明、工具契约 |
| [tools.md](readme/tools.md) | 工具函数签名与速查表 |
| [analyzers.md](readme/analyzers.md) | 指标引擎、排名、事件检测 |
| [formulas.md](readme/formulas.md) | 辅助公式系统 |
| [facts.md](readme/facts.md) | 事实档案结构与分层设计 |
| [identity.md](readme/identity.md) | 身份目录三层映射 |
| [importers.md](readme/importers.md) | 数据同步管道 |
| [knowledge.md](readme/knowledge.md) | Wiki 知识库检索 |
| [mcp.md](readme/mcp.md) | MCP 服务器配置 |
| [models.md](readme/models.md) | 数据模型定义 |
| [agent.md](readme/agent.md) | Agent 工具层实现 |
| [maintain-relationship-workflow.md](readme/maintain-relationship-workflow.md) | 关系维护工作流 |

---

## 参与贡献

LoveMentor 欢迎第一次参与开源的贡献者；你不需要先理解全部架构。

- 改进文档、错误提示、测试和合成示例；
- 为指标计算、身份解析或同步适配器补边界测试；
- 改进演示报告与可视化；
- 实现可选数据源适配器或跨平台兼容性修复。

提交前请阅读 [贡献指南](CONTRIBUTING.md)。标有 `good first issue` 或 `help wanted` 的 GitHub 任务会优先拆分为可独立提交的范围。维护者会认真 Review 合理 PR，并尽量在 7 天内回应。

## 路线图

首个公开 Release 定义为 **v0.1.0 — Core & Demo**：分析核心与合成预览必须可用；WCD、WeFlow 和本地模型是可选 Provider，不会阻塞首次体验。详见 [ROADMAP.md](ROADMAP.md) 和 [CHANGELOG.md](CHANGELOG.md)。

## 隐私说明

- 本项目处理个人微信聊天数据，`data/` 和 `docs/` 为独立 git 仓库
- 代码中使用假名代替真实联系人信息
- 配置文件 `data/system/config.yaml`（含 token）不进 git
- 项目自身完全在本地运行，不会主动上传聊天数据、联系人信息或分析结果
- 若用户显式接入云端大模型，发送给该模型的提示词、聊天片段或分析上下文将按该服务商的政策处理；请仅发送你愿意交由该服务商处理的内容
- 详细隐私规则见 `CLAUDE.md`

---

## License

[MIT](LICENSE)

---

*LoveMentor — 完全本地运行的对话观察与关系决策辅助系统。代码负责数据，Agent 负责推理。*
