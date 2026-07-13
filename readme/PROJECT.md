# LoveMentor 项目文档

> 最后更新：2026-07-13
> 基于项目当前代码状态编写

---

## 一、项目概述

LoveMentor 是一个 AI 驱动的恋爱关系辅助系统。用户通过 Claude Code（Agent）与系统交互，Agent 直接调用 Python 工具获取数据，以 Wiki 知识库为推理主轴自行分析后输出结果。公式作为辅助参考视角，不主导决策。

**架构**（详见 `exchange/architecture/架构.md`）：

```
原始知识文件          数据管道（微信同步→SQLite→指标/事件/排名）
        │                      │
        ▼                      │
知识构建管道                    │
  OCR/语音转文字                │
  Word/PDF→MD→OKF              │
        │                      │
        ▼                      ▼
┌──────────────┐       ┌──────────┐  ┌──────────┐
│ OKF 知识库   │       │ 事实档案  │  │ 原始数据  │
│ (推理主轴)   │       │(长期记忆) │  │(实时接口) │
│ 评分检索     │       │ 笔记·会面 │  │ 聊天·指标 │
│ 别名扩展     │       └─────┬────┘  └─────┬────┘
│ 渐进式披露   │             │             │
└──────┬───────┘             │             │
       │     公式(辅助参考)   │             │
       │     IVI/SPE/EWS ◄───┼─────────────┘
       │                     │
       └────── 全部通过 MCP 工具访问 ──────────┐
                                │              │
                ┌───────────────▼──────────────▼┐
                │     LLM Agent（推理核心）       │
                │  ① 读取知识库 → 找方法论        │
                │  ② 查阅事实 → 笔记/会面         │
                │  ③ 分析数据 → 指标/事件/排名    │
                │  ④ 核验公式 → 量化视角          │
                └───────────────────────────────┘
```

**核心原则**：代码负责数据，Agent 负责推理，Wiki 是知识依据，公式是参考视角。

用户通过 Claude Code（Agent）与系统交互，Agent 直接调用 Python 工具获取数据，结合 Wiki 知识库自行分析后输出结果。或通过 MCP 协议暴露给 Claude Desktop / Cursor（见 [mcp.md](mcp.md)），MCP Server (FastMCP stdio) 提供 49 个工具，复用 engine/tools.py。

**数据来源**：

```
WeChatDataAnalysis (WCD) 或 WeFlow
  → HTTP API (WCD: http://127.0.0.1:10392 / WeFlow: http://127.0.0.1:5031)
  → engine/importers/* 同步管道（WCDClient / WeFlowClient 自动切换）
  → data/raw/core.db (SQLite)
  → engine/analyzers/* (指标/排名/事件检测)
  → engine/tools.py (Agent 工具入口)
```

---

## 二、已实现功能

### 2.1 数据同步

从 WeChatDataAnalysis (WCD) 或 WeFlow 同步微信数据到本地 SQLite。通过 `config.yaml` 的 `weflow.backend` 切换后端。

| 功能            | 说明                                           |
| --------------- | ---------------------------------------------- |
| 联系人同步      | 从 API 拉取联系人信息（昵称/备注/头像/标签）   |
| 会话同步        | 拉取会话列表（私聊/群聊）                      |
| 消息同步        | **默认增量**拉取消息（支持全量重拉、单会话同步）|
| 朋友圈同步      | 拉取朋友圈动态和互动（点赞/评论）              |
| 截图 OCR 导入   | 从小红书/探探等平台截图 OCR 导入聊天记录       |
| checkpoint 机制 | 基于 watermark 的增量同步，不重复拉取          |

**数据库表**：

- `contacts` — 联系人基础信息
- `conversations` — 会话元数据
- `messages` — 聊天消息（支持多种消息类型）
- `attachments` — 附件记录
- `moments` — 朋友圈动态
- `moment_interactions` — 朋友圈互动（点赞/评论）
- `sync_state` — 同步水位（每个会话独立）
- `sync_log` — 同步日志
- `contact_excludes` — 排除列表
- `contact_merges` — 合并记录
- `people` — 身份目录-人
- `contact_accounts` — 身份目录-账号
- `contact_aliases` — 身份目录-别名
- `contact_identity_log` — 身份操作日志
- `schema_version` — 数据库迁移版本记录

### 2.2 指标引擎

量化指标 + 需求感惩罚 + 动态信号 + 媒体参与度。当前共 22 维指标（16 行为统计 + 6 Wiki 衍生 + 3 语义），权重总和 = 1.00。

#### 行为统计指标（16 维）

| 指标              | 含义                           | 权重 |
| ----------------- | ------------------------------ | ---- |
| fback             | 回复字数比（她/你）            | 0.07 |
| rlatency          | 回复速度比（你/她）            | 0.04 |
| fback_quality     | 回复质量（正向情绪+追问-敷衍） | 0.04 |
| qscore_personal   | 个人化问题比例（IOI）          | 0.02 |
| trend             | composite 周变化               | 0.10 |
| escore_volatility | 情绪波动（会话间标准差）       | 0.01 |
| moments           | 朋友圈互动频率                 | 0.01 |
| qscore_functional | 工具化问题比例（供养者信号）   | 0.01 |
| rlatency_context  | 慢回时有解释的比例             | 0.01 |
| msg_volume_trend  | 消息量周变化率                 | 0.01 |
| latency_trend     | 回复速度周变化率               | 0.01 |
| recent            | 最后消息距今天数               | 0.03 |
| active_days       | 活跃天数（30 天窗口）          | 0.04 |
| escore            | 情绪表达比例                   | 0.01 |
| msg_count         | 消息总数（对数归一化）         | 0.02 |
| qscore            | 问号比例（旧版，权重 0）       | 0.00 |

#### Wiki 衍生指标（6 维，v2 新增）

| 指标 | 含义 | 权重 | Wiki 依据 |
|------|------|------|-----------|
| her_initiation_rate | 她的主动发起率 | 0.10 | IOI 兴趣指标（主动发起=强 IOI） |
| topic_continuation | 话题延续率 | 0.06 | 窗口识别 + Grice 合作原则 |
| reply_quality | 回复质量 | 0.06 | IOI 信号质量（costly vs cheap） |
| session_balance | 会话对等性 | 0.05 | 等值心态/需求感控制 |
| emotional_temperature | 情绪温度 | 0.07 | 情绪判断九分类 |
| friendzone_risk | 友谊区风险 | 0.00 | 友谊区（只聊日常不聊情感） |

#### 语义指标（3 维，v3 新增，来自 MacBERT/规则双参考）

| 指标 | 含义 | 权重 | 区分度 |
|------|------|------|--------|
| semantic_flirt | 暧昧程度（0-9 分归一化） | 0.10 | 强（成功 2.66 vs 失败 1.16） |
| semantic_invitation | 邀约积极性（0-9 分归一化） | 0.08 | 强（成功 ≥3.79 vs 失败 ≤0.88） |
| semantic_emotion_balance | 正负情绪比（0-1） | 0.05 | 强（成功 0.76 vs 失败 0.50） |

**乘法惩罚**：neediness_penalty（0.4-1.0），消息量比>1.3 或发起频率>60% 时触发。
**信号等级**：强窗口(>=0.45) / 中窗口(>=0.35) / 弱窗口(>=0.25) / 冷淡(>=0.10) / 无信号(<0.10)
**互动模式**：lover / provider / neutral（基于回复质量、个人化问题、需求感综合判断）
**动态信号**：session_recency（最近活跃）、momentum（7天动量）、initiation_source（谁发起）
**媒体参与度**：贴纸/图片发送频率、贴纸镜像检测（她用你的贴纸 = 正向信号）

**22 个指标的本质**：这些指标不是"精确评分系统"，而是把几万条非结构化聊天记录压缩成二十几个 Agent 一眼能看懂的结构化数字。来源是 Wiki 知识库准则 + 公开方法论 + 历史案例回测校准。Agent 参考这些指标但不机械套用阈值，最终判断依据是 Wiki 知识 + 事实档案。

### 2.3 Wiki 知识库（推理主轴）

OKF（Open Knowledge Format）格式的结构化知识库，是 Agent 推理的**第一依据**。Wiki 不是"参考资料"，是方法论主轴——Agent 先读 Wiki 找框架，再看数据，最后用公式核验。

| 特性 | 说明 |
|------|------|
| 格式 | Markdown + YAML 前置元数据（title/type/tags/keywords/stages/skills） |
| 条目类型 | entity（概念框架）/ scenario（场景决策）/ topic（主题综述）/ synthesis（跨源对比）/ source（来源摘要） |
| 检索机制 | 五维度评分（title/keyword/tag/stage/skill）+ 别名扩展，不依赖 embedding |
| 渐进式披露 | 4 种 task_type 预算控制返回内容量（default/reply/deep/search），按需检索 |
| 双向链接 | 条目间 `[[条目名]]` 链接，Agent 可追踪相关概念 |

```python
from engine.tools import wiki_search, wiki_show
wiki_search("窗口识别 IOI")  # 多关键词搜索
wiki_show("docs/wiki/wiki/entities/IOI（兴趣指标）.md")  # 读取全文
```

### 2.4 辅助参考：公式与指标

公式是 chat-skills 遗产的独立体系，通过标注 Wiki 依据做软关联。**Agent 核验而非套用**——读公式结果 → 结合 Wiki 知识核验 → 自己做判断，不机械套阈值。

| 公式 | 含义 | Wiki 依据 |
|------|------|-----------|
| formula_ivi | 意图真实度 | `[[IOI（兴趣指标）]]`、`[[意向判断]]` |
| formula_spe | 社交势能 | `[[框架（Frame）]]` |
| formula_ews | 升温窗口期 | `[[窗口识别]]` |
| formula_action | 终极决策 | `[[行动决策]]` |

完整公式说明见 [formulas.md](formulas.md)。阈值是参考，不是硬规则。

### 2.5 身份目录

Person → Account → Alias 三层映射，支持同一人有多个微信号、多个别名。

| 功能       | 说明                                                        |
| ---------- | ----------------------------------------------------------- |
| 自动初始化 | 从现有联系人/会话创建 Person                                |
| 模糊搜索   | 支持名字、别名、wxid、person_id 搜索                        |
| 别名管理   | 支持 fake_name/pinyin/real_name/manual 类型，可标记隐私级别 |
| 账号绑定   | 一个 Person 可绑定多个 wxid                                 |
| 合并       | 两个 Person 合并为一个                                      |
| 审计       | 检测多账号、疑似重复、未归属联系人                          |
| 排名聚合   | 排名按 person_id 聚合多账号指标                             |

### 2.6 事件检测

从聊天记录自动检测关键关系事件。

| 事件类型 | 检测逻辑                     |
| -------- | ---------------------------- |
| 首次聊天 | 最早消息时间                 |
| 断联     | 连续 N 天无消息（默认 7 天） |
| 恢复联系 | 断联后重新开始聊天           |
| 频率变化 | 7 天窗口内消息量翻倍或减半   |

事件可自动写入事实档案（`events("XX", scan=True)`）。

### 2.7 事实档案

纯事实层，只记录客观事实，不做分析。

| 功能       | 说明                                                                |
| ---------- | ------------------------------------------------------------------- |
| 人物档案   | `data/facts/people/<显示名>__<person_id>.md`                      |
| 自我档案   | `data/facts/self/`                                                |
| 备注       | `note("XX", "她说喜欢猫")` → 写入 Notes section                  |
| 约会记录   | `date("XX", date_text="2026-06-08", location="岳麓山", rating=4)` |
| 评估记录   | `evaluate("XX", "还在聊，回复变慢了")` → outputs/evaluations/    |
| 事件写入   | `events("XX", scan=True)` → 关系时间线 section                   |
| 朋友圈同步 | `sync_moments("XX")` → 朋友圈互动 section                          |
| 迁移支持   | 自动从旧格式迁移（display_name 匹配 → person_id 匹配）             |

### 2.8 排名和周报

| 功能       | 说明                                            |
| ---------- | ----------------------------------------------- |
| 排名       | `rank()` → 按 composite 分数排序全部联系人   |
| 周报       | `weekly()` → 排名快照 + 趋势 + Markdown 报告 |
| 数据可信度 | 基于消息量和会话覆盖率计算                      |
| 快照恢复   | `restore --list / --from` 恢复历史排名快照    |
| 排除系统   | 支持硬排除（系统号/企业号）、标签排除、手动排除 |

### 2.9 贴纸系统

| 功能          | 说明                                                   |
| ------------- | ------------------------------------------------------ |
| 贴纸扫描      | 从消息 raw_content XML 提取贴纸 md5                    |
| 贴纸词典      | SQLite 表存储 md5/label/emotion/content_type/frequency |
| 情绪标注      | 按对对方态度分类：好感/敌意/中性/暧昧                   |
| 镜像检测      | 她用了你用过的贴纸 = 正向信号（强/中/弱三级）          |
| HTML 标注工具 | `engine/stickers/label.py` 生成浏览器标注页面         |

### 2.10 朋友圈互动统计

```python
from engine.tools import moments_stats
data = moments_stats("小溪")
# → her_posts: 她发了多少条朋友圈
# → my_likes_on_her / my_comments_on_her: 我给她的互动
# → her_likes_on_my / her_comments_on_my: 她给我的互动（含评论内容）
# → her_like_ratio: 她给我的点赞比例
# → engagement_summary: "她主动：她有 9 次互动，你 0 次"
```

### 2.11 语义分析（Phase 0-2 完成 + B2 双模型部署）

10 个可观测行为标签的双层检测系统，共标注 **13,675 条对话窗口**（每条约 20 轮聊天，清洗去重后），并部署 B0'/B2 双模型架构：

**Layer 1 — 行为检测（模型/规则）**：

| 标签 | 含义 | 举例 |
|------|------|------|
| `information_exchange` | 信息交换 | "明天几点？" |
| `opinion_expression` | 观点表达 | "我觉得这个电影不错" |
| `emotion_positive` | 正向情绪 | "哈哈太开心了" |
| `emotion_negative` | 负向情绪 | "今天好累" |
| `flirt` | 暧昧/调侃/撒娇 | "想你了""你猜～" |
| `question_asking` | 主动提问 | "你觉得呢？" |
| `self_disclosure` | 自我暴露 | "我家里养了只猫" |
| `invitation` | 邀约/提议 | "周末要不要出来" |
| `framing_boundary` | 关系边界信号 | "兄弟""只是朋友" |
| `perfunctory` | 敷衍回应 | "嗯""哦""好的" |

**双参考机制**：
- `source="macbert"` — MacBERT ONNX 模型推理（约 0.5s/窗口，语义覆盖全面）
- `source="rule"` — 规则词典匹配（约 0.02s/窗口，可解释性强）

**B2 双模型架构**（2026-07-13 部署）：
- **B0'**（roleless，`model="b0"`）：纯文本输入，生产基线/回退模型
- **B2**（role-aware，`model="b2"`）：含 `[TARGET]/[OTHER]` 角色前缀，**默认生产模型**
- `behaviors("姓名")` 默认走 B2 her-side，Agent 无感知切换
- B2 me-side（`target_role="me"`）只在 SELF/OTHER 对比分析中使用，不直接输出确定性结论
- 回滚策略：B2 加载失败时，调用侧 catch 异常后回退 `get_b0()`

模型使用 **13,675 条对话窗口**（清洗去重后）训练：2,083 条来自真实微信私聊（core.db），11,592 条来自恋爱教学案例库（完整聊天记录、Tinder 案例、PUA 教学系列，经 4000+ 原始文件清洗得到）。外部数据按 1000 条一批分 14 批，通过 LLM 批量标注（含 `quality_ok` 质量开关），清洗去重后保留 11,592 条。

**Layer 2 — 关系解读融合（engine/analyzers/semantic.py）**：

| 派生指标 | 计算方式 | 含义 |
|----------|----------|------|
| emotion_balance | pos / (pos + neg) | 正负情绪比 |
| interest_signal | avg(question, disclosure, invitation, flirt) | 兴趣信号强度 |
| friendship_signal | avg(framing_boundary, perfunctory) | 友谊区/敷衍信号 |
| conversation_depth | avg(info, opinion, emo_pos, emo_neg, flirt) | 互动深度 |

**回测验证结果**：flirt 和 invitation 是区分成功/失败案例的最强指标。成功案例 invitation ≥3.79，失败案例 ≤0.88。语义指标已融入 composite 加权体系（见 2.2 节）。

```python
from engine.tools import behaviors, behaviors_data
report = behaviors("姓名", window_days=30, source="macbert")  # 默认 B2 her-side，Markdown 报告
data = behaviors_data("姓名", source="rule")  # 结构化数据
# 可选：model="b0" 回退基线，target_role="me" 切换视角
```

### 2.12 互动序列分析（Phase 0 完成）

三视角架构三层视角覆盖 SELF/OTHER/INTERACTION，Phase 0 已交付基础设施：

**Phase 0 完成内容**：
- `engine/analyzers/interaction_sequence.py` — Turn/TurnPair 数据结构、连续同人消息合并、会话分组、cue-response 配对
- 29 个单元测试全部通过，38 个语义回归测试无副作用
- `Turn.timestamp_reliability` 处理 missing/synthetic/unknown 时间戳
- `TurnPair` 不携带推断结论（response_type 不属于此结构），严格区分证据与结论

**新增工具 `turn_stats("姓名")`**：纯描述性统计，零模型依赖，输出 self/other 轮次分布、会话发起频率、回复延迟、未响应 cue 统计。立即可用于分析。

**Phase 1/2 阻塞原因**：B2 me-side 方向一致率仅 38%（随机基线 35.5%），不足以支撑 SELF 语义画像和互动耦合分析。需更多配对训练数据（B2+）或降低精度要求。

```
Phase 0(完成) ──→ Phase 1(SELF/OTHER 画像) ──→ Phase 2(互动耦合)
     │                    ↑                              ↑
     │             阻塞：B2 me-side 38%             阻塞：Phase 1
     │             需方向一致率 ≥ 70%              需 Phase 1 就绪
     └── turn_stats() 已落地，零模型依赖
```

```python
from engine.tools import turn_stats
stats = turn_stats("姓名", window_days=30)  # Markdown，直接给 Agent 读
```

### 2.13 回测框架

以已知结果的历史案例作为 ground truth，反向审判系统参数是否合理。详见 [backtest.md](backtest.md)。

| 功能 | 说明 |
|------|------|
| 案例定义 | `engine/backtest/config/cases.yaml`，含切片级标签（阶段/窗口状态/风险等级） |
| 数据采集 | Phase A（composite + neediness）+ Phase B（公式层指标） |
| 案例内时序分析 | 同一案例不同阶段切片对比，识别转折点和预警信号 |
| 描述性统计 | 分布表、重叠区间、均值差异（不做推断统计） |
| 留一验证 | Leave-One-Case-Out 验证参数稳定性 |
| 语义回测 | 用 MacBERT 分析聊天内容，验证语义指标区分力 |
| 校准闭环 | 参数调整 → 重新采集 → 效果对比 → 确认/回滚 |

**关键发现**：
- composite=0.10 是"有互动/无互动"的关键分界线
- 趋势斜率 >+0.005 为上升健康，<-0.005 为崩溃
- "熹微异常"（composite 上升但失败）由语义分析解答：flirt 和 invitation 极低，聊得多但不暧昧不邀约

---

## 三、Agent 工具完整列表

所有工具通过 `engine/tools.py` 导入，返回 str（Markdown）或 dict（结构化数据）。

### 3.0 工具契约

#### 分层

工具按职责分为四层，每层有明确的返回 schema：

| 层 | 工具 | 返回类型 | 说明 |
|---|------|---------|------|
| **数据读取** | brief, chat, evidence, metrics, status, rank, wiki_search, wiki_show, moments_stats | str 或 dict | 只读，无副作用，可安全重试 |
| **数据写入** | note, date, evaluate, events(scan=True), save_analysis, save_from_markdown | str（成功消息）或 Path | 有副作用，写入 facts/outputs |
| **身份管理** | contact(alias/link/merge), exclude(add/remove), failure(add), sticker(label) | str（操作结果） | 修改身份目录/排除列表，merge 不可逆 |
| **计算工具** | formula_params, formula_ivi, formula_spe, formula_ews, formula_is, formula_gap_effect, formula_eev, formula_cs, formula_action | dict | 纯计算，无副作用 |
| **维持关系** | maintain_candidates, format_candidates | list[Candidate] 或 str | 候选人筛选，无副作用 |

#### 返回 schema

**数据读取工具返回的 dict**（metrics, moments_stats, formula_*）：

```python
{
    "key": value,           # 数据字段
    # 错误时返回 str 而非 dict：
    # "未找到联系人: XX"
}
```

**数据写入工具返回的 str**：成功消息（如 "已写入备注: /path/to/file.md"）或错误消息。

**错误约定**：所有工具不抛异常，错误情况返回描述性 str（如 "未找到联系人: XX"）。调用方通过 `isinstance(result, dict)` 判断成功与否。

#### 版本

工具接口向后兼容。新增参数必须有默认值，不破坏已有调用。

#### 权限规范

| 操作类型 | 工具 | 是否可回滚 | Agent 行为要求 |
|---------|------|-----------|--------------|
| **只读** | brief/chat/evidence/metrics/status/rank/wiki_*/moments_stats/formula_*/behaviors | N/A | 自由调用 |
| **追加写入** | note/date/evaluate | 是（可手动编辑文件删除） | 直接执行，无需确认 |
| **覆盖写入** | save_analysis/save_from_markdown | 是（旧文件被覆盖） | 覆盖前告知用户 |
| **检测写入** | events(scan=True) | 是（可从档案删除） | 先展示检测结果，再写入 |
| **身份变更** | contact(alias/link) | 是（可撤销） | 直接执行 |
| **不可逆操作** | contact(merge) | 否 | **必须向用户确认后再执行** |
| **排除操作** | exclude(add) | 是（可 remove） | 直接执行，告知原因 |
| **同步** | sync/sync_person | 否（数据已入库） | 直接执行，报告结果 |
| **周报** | weekly | 否（快照已保存） | 直接执行 |

### 3.1 数据获取（只读）

| 工具 | 参数 | 返回 | 用途 |
|------|------|------|------|
| `brief(name, compact=False)` | 名字 | str | 全局视图：事实+指标+事件+信号+Wiki推荐 |
| `brief_data(name)` | 名字 | dict | 结构化摘要（identity/metrics/events/signals/recent_messages），Agent 内部分析用 |
| `chat(name, recent=50, from_date=None, to_date=None, keyword=None, context_lines=0)` | 名字+过滤 | str | 聊天记录（按日期分组，人类阅读） |
| `chat_data(name, recent=50, from_date=None, to_date=None, keyword=None, context_lines=0)` | 名字+过滤 | dict | 结构化聊天查询，Agent 内部分析用 |
| `message_context_data(message_ids, before=20, after=20)` | 消息ID列表 | dict | 根据消息 ID 获取前后上下文（不跨会话） |
| `evidence(name, section="all", since_date=None)` | 名字+section | str | 事实档案（timeline/evaluations/notes/dates/all） |
| `metrics(name)` | 名字 | dict | 全部指标数据（composite/信号等级/指标/动态信号） |
| `status(name)` | 名字 | str | 详细指标状态（格式化表格） |
| `rank()` | 无 | str | 全部联系人排名表 |
| `wiki_search(query)` | 关键词 | str | 跨 Wiki/Analysis/KB 搜索 |
| `wiki_show(path, max_chars=50000)` | 文件路径 | str | 安全读取材料文件全文 |
| `moments_stats(name)` | 名字 | dict | 朋友圈互动统计（双向点赞/评论/比例） |
| `behaviors(name, window_days=30, source="macbert", model="b2", target_role="her")` | 名字+窗口+来源+模型+视角 | str | 语义行为分析报告（10维标签+派生指标，默认 B2 her-side） |
| `behaviors_data(name, window_days=30, source="macbert", model="b2", target_role="her")` | 名字+窗口+来源+模型+视角 | dict | 结构化语义数据（标签均值/派生指标/窗口序列） |

### 3.2 数据写入

| 工具                                                       | 参数          | 返回 | 用途                                           |
| ---------------------------------------------------------- | ------------- | ---- | ---------------------------------------------- |
| `note(name, text)`                                       | 名字+内容     | str  | 添加备注到事实档案                             |
| `date(name, date_text=None, location=None, rating=None)` | 名字+约会信息 | str  | 记录约会                                       |
| `evaluate(name, text)`                                   | 名字+评估     | str  | 记录主观评估                                   |
| `events(name, scan=False, disconnect_days=7)`            | 名字          | str  | 检测关系事件（scan=True 写入档案）             |
| `save_analysis(name, ...)`                               | 分析结果      | str  | 保存分析结论到 YAML（支持 evidence_refs/metric_snapshot/data_window） |
| `save_from_markdown(name, markdown_text)`                | 名字+Markdown | str  | 从结构化 Markdown 保存分析                     |
| `contact(query, action="search", **kwargs)`              | 名字+操作     | str  | 身份目录（search/show/alias/link/merge/audit） |
| `exclude(action="list", **kwargs)`                       | 操作          | str  | 排除管理（list/add/remove）                    |
| `failure(action="list", **kwargs)`                       | 操作          | str  | 失败案例（list/add）                           |
| `sticker(action="list", **kwargs)`                       | 操作          | str  | 贴纸管理（scan/list/label）                    |

### 3.3 同步和周报

| 工具                                          | 参数     | 返回 | 用途                                 |
| --------------------------------------------- | -------- | ---- | ------------------------------------ |
| `sync(mode="incremental", session_id=None, meta_only=False)` | 模式     | str  | 数据同步（**默认增量**）。meta_only=True 只同步联系人/会话（约 1 秒） |
| `sync_person(name, mode="incremental")`     | 名字     | str  | 按人名同步（**默认增量**，只拉该联系人的最新消息） |
| `sync_moments(name)`                               | 名字     | str  | 同步朋友圈互动到事实档案             |
| `weekly(deep=False)`                        | 是否深度 | str  | 生成周报（排名快照 + Markdown）      |
| `compare_analysis(name)`                    | 名字     | str  | 对比 latest 和 previous 分析结论    |

### 3.4 辅助参考工具（公式）

> 公式是 chat-skills 遗产的独立体系，标注 Wiki 依据做软关联。Agent 核验而非套用阈值。

| 工具                                                                      | 参数 | 返回 | 用途                   |
| ------------------------------------------------------------------------- | ---- | ---- | ---------------------- |
| `formula_params(name, conn=None)`                                   | 名字+可选连接 | dict | 自动计算全部可量化参数 |
| `formula_ivi(sp, fback, user_investment, pface)`                        | 参数 | dict | 意图真实度（参考视角） |
| `formula_spe(user_ddepth, target_ddepth, target_latency, user_latency)` | 参数 | dict | 社交势能（参考视角）   |
| `formula_ews(gap_effect, cp_index, eev, scarcity_loss)`                 | 参数 | dict | 升温窗口期（参考视角） |
| `formula_is(backstage, pface)`                                          | 参数 | dict | 真实亲密度（参考视角） |
| `formula_gap_effect(act, exp)`                                          | 参数 | dict | 情绪落差（参考视角）   |
| `formula_eev(p_succ, escalation_bonus, p_fail, power_drop_risk)`        | 参数 | dict | 升温期望值（参考视角） |
| `formula_cs(internal_d, external_r)`                                    | 参数 | dict | 矛盾状态（参考视角）   |
| `formula_action(ivi, spe, ews, cs=0.0, ev=0.5)`                         | 参数 | dict | 终极决策（参考视角）   |

### 3.5 维持关系

| 工具 | 参数 | 返回 | 用途 |
|------|------|------|------|
| `maintain_candidates(max_people=10)` | 最多人数 | list[Candidate] | 筛选需要维持关系的候选人（热度下降/窗口未推进/高潜力） |
| `format_candidates(candidates)` | 候选人列表 | str | 格式化为 Markdown（含上次消息摘要、消息建议规则） |

### 3.6 Wiki 返回契约

**wiki_search 返回**：Markdown 格式的搜索结果列表，每条包含：
- 标题 + 类型（entity/scenario/topic/synthesis/source）
- 匹配原因 + 相关度评分
- 文件路径
- 匹配的关键词

**wiki_show 返回**：文件全文（Markdown），截断到 max_chars。路径越界或文件不存在时返回错误消息。

### 3.7 Agent 操作顺序与冲突裁决

> **重要区分**：操作顺序是"按什么顺序查"（先找方法论再动手），冲突裁决是"谁说了算"（当信息冲突时优先相信什么）。两者不冲突。

#### Agent 操作顺序（推理步骤）

Agent 综合多条输入流，典型操作顺序（先找方法论，再看具体数据）：

| 步骤 | 来源 | 工具 | 说明 |
|------|------|------|------|
| ① | OKF 知识库 | wiki_search / wiki_show | 找相关框架和方法论（推理主轴，出发点） |
| ② | 事实档案 | evidence | 查阅用户记录的会面/笔记/客观事实 |
| ③ | 实时数据 | brief / chat / metrics / status | 分析指标/事件/排名（当前事实） |
| ④ | 公式核验 | formula_params / formula_* | 看量化视角，但不机械套阈值（辅助参考） |

#### 冲突裁决规则（证据链）

当不同来源的信息矛盾时，按证据链优先级裁决：

| 优先级 | 来源 | 工具 | 性质 |
|--------|------|------|------|
| 1（最高） | 实时数据 | brief/chat/metrics/status | 当前事实，不可推翻 |
| 2 | 事实档案 | evidence | 客观记录，可信 |
| 3 | 事件检测 | events | 从数据推导，基本可信 |
| 4 | 公式计算 | formula_* | 量化视角，有启发但需核验 |
| 5（最低） | 历史分析 | data/outputs/analysis/ | 过去的观点，可能已过时 |

**Wiki 的角色**：Wiki 是操作顺序的出发点（方法论主轴），但不直接参与冲突裁决——Wiki 提供"怎么看"的框架，实时数据决定"现在发生了什么"。当低层数据与高层矛盾时，以高层为准。公式结果只能作为"视角"，不能推翻事实和 Wiki 知识。

### 3.8 Agent 分析风格

Agent 实际使用这套系统的预期行为风格，见 `exchange/architecture/example_analysis_love.md`。核心特征：

1. **场景理解** — 先理解情境再分析，不急于给策略
2. **数据全貌** — 表格包含 Wiki 解读列，每个数据点配 Wiki 解释
3. **Wiki 框架诊断** — 用多个 Wiki 条目交叉验证判断
4. **具体操作** — 每步策略都引用 Wiki 依据
5. **绝对不要做** — 列出禁忌及其 Wiki 依据
6. **底层判断** — 用 Wiki 框架做最终结论，公式数值只在数据全貌出现一次

**公式在分析中的角色**：IVI=0.5 这样的数值只在"数据全貌"里出现一次，作为参考视角。后续所有判断、策略都基于 Wiki 知识 + 事实档案，不机械套用公式阈值。

---

## 四、如何使用

### 4.1 前置条件

1. **WeChatDataAnalysis (推荐)** 或 WeFlow 运行中（配置 `config.yaml` 中的 `weflow.backend`）
2. **配置文件** `data/system/config.yaml` 已设置（my_wxid、weflow.base_url、token）
3. **Python 环境**：pyyaml（必须）、rapidocr-onnxruntime + Pillow（截图 OCR 用）

### 4.2 分析某个人

```
用户："帮我分析小溪的情况"

Agent 执行（推荐用法 — 结构化数据 + 证据链）：
1. sync_person("小溪")                       # 同步最新消息
2. brief_data("小溪")                        # 结构化摘要（含指标/事件/信号）
3. 根据信号读取相关 Wiki 页面
4. chat_data("小溪", recent=200)             # 获取聊天结构化数据
5. message_context_data([msg_id_1, ...])     # 对关键消息取上下文
6. formula_params("小溪")                     # 获取量化参数
7. formula_ivi/spe/ews/action(...)            # 计算战态
8. 结合数据 + Wiki 框架，自行分析输出
9. save_analysis("小溪", analysis=分析结论,   # 保存分析（可附带证据引用）
                  evidence_refs=[{"message_id": "xxx", "quote": "她说...", "note": "IOI"}])

旧用法（兼容，Markdown 返回，人类阅读）：
1. sync_person("小溪")                    # 同步最新消息
2. brief("小溪", compact=True)             # 获取全局视图
3. chat("小溪", recent=200)                # 聊天记录
4. formula_params("小溪")                  # 获取量化参数
5. ...结合 Wiki 分析输出
6. save_from_markdown("小溪", 分析结论)     # 保存结论
```

### 4.3 紧急回复

```
用户："她发了'你忙吗'怎么回"

Agent 执行：
1. sync_person("小溪")                    # 同步最新消息
2. chat("小溪", recent=30)                 # 获取最近聊天
3. metrics("小溪")                         # 获取当前指标
4. wiki_search("推拉 冷读")                   # 找相关框架
5. 结合数据 + 框架，给出一条可直接发送的回复
```

### 4.4 查看排名和周报

```
用户："做一下周报"

Agent 执行：
1. sync()                                   # 全局同步
2. weekly()                                 # 生成周报
```

### 4.5 记录信息

```
用户："帮我记一下，小溪说她喜欢猫"

Agent 执行：
1. note("小溪", "她说喜欢猫")              # 写入备注
```

### 4.6 朋友圈互动分析

```
用户："看看我和小溪的朋友圈互动"

Agent 执行：
1. moments_stats("小溪")                   # 获取互动统计
2. 分析互动模式，给出判断
```

---

## 五、目录结构详解

```
loveMentor/
├── engine/                    # 核心引擎（纯数据处理，不依赖 LLM）
│   ├── tools.py              #   Agent 工具统一入口
│   ├── formulas.py           #   战态公式（原 chat-skills）
│   ├── config.py             #   配置管理（Config 类 + 目录常量）
│   ├── stickers.py           #   贴纸词典管理
│   ├── agent/                #   Agent 工具实现（按域拆分）
│   │   ├── core.py            #     共享基础设施（连接/解析/交叉引用）
│   │   ├── context.py         #     上下文组装器（ContextBuilder）
│   │   ├── registry.py        #     Skill 注册表（SkillRegistry）
│   │   ├── brief.py           #     全局摘要（agent_brief 主体）
│   │   ├── snapshot.py        #     摘要辅助（个人模式/消息筛选/月度统计）
│   │   ├── recommend.py       #     Wiki/框架推荐
│   │   ├── chat.py            #     聊天证据（agent_chat）
│   │   ├── evidence.py        #     事实追溯（agent_evidence）
│   │   ├── material.py        #     材料搜索/阅读（agent_material_*）
│   │   ├── write.py           #     数据写入（note/date/evaluate/events/save_*）
│   │   ├── moments.py         #     朋友圈（moments_stats/sync_moments_to_archive）
│   │   ├── sync_agent.py      #     数据同步（agent_sync/sync_person）
│   │   ├── report.py          #     指标报告（metrics/status/rank/weekly）
│   │   ├── identity_ops.py    #     身份管理（contact/exclude/failure/sticker）
│   │   └── signals.py         #     信号检测（关键词/操控/朋友圈联动）
│   ├── analyzers/            #   分析器
│   │   ├── metrics.py        #     指标计算引擎
│   │   ├── ranker.py         #     排名引擎
│   │   ├── events.py         #     事件检测（断联/恢复/频率变化）
│   │   ├── weekly_report.py  #     周报生成
│   │   ├── chat_history.py   #     聊天记录查询
│   │   └── exclude.py        #     排除逻辑
│   ├── knowledge/            #   Wiki 检索
│   │   ├── wiki_index.py     #     索引加载（search-index.json）
│   │   ├── wiki_retriever.py #     检索器（多维打分）
│   │   └── wiki_context.py   #     prompt 格式化
│   ├── facts/                #   事实档案
│   │   ├── people_archive.py #     人物档案读写
│   │   └── failure_archive.py#     失败案例读写
│   ├── identity/             #   身份目录
│   │   └── directory.py      #     Person→Account→Alias 映射
│   ├── importers/            #   数据同步
│   │   ├── sync.py           #     同步主入口
│   │   ├── sync_contacts.py  #     联系人同步
│   │   ├── sync_conversations.py # 会话同步
│   │   ├── sync_messages.py  #     消息增量同步
│   │   ├── sync_moments.py   #     朋友圈同步
│   │   ├── weflow_client.py  #     WeFlow HTTP API 客户端
│   │   ├── wcd_client.py     #     WCD HTTP API 客户端（兼容 WeFlowClient）
│   │   ├── checkpoint.py     #     同步水位管理
│   │   ├── db_init.py        #     SQLite schema 初始化
│   │   ├── ocr_engine.py     #     OCR 引擎（RapidOCR）
│   │   ├── screenshot_parser.py #  截图解析
│   │   └── screenshot_import.py # 截图导入管道
│   ├── models/               #   数据模型（dataclass）
├── ml/                       # 语义分析（13,675 条标注数据，B0'/B2 双模型）
├── .claude/skills/           # Claude Code skills
│   ├── love-mentor.md        #   统一入口（决策树+工具速查+路由表+指标体系）
│   ├── person-info.md        #   人物信息管理
│   └── chat-analyzer.md      #   聊天深度分析
├── docs/
│   ├── wiki/                 #   Wiki 知识库
│   │   ├── wiki/entities/    #     概念/框架
│   │   ├── wiki/scenarios/   #     场景决策页
│   │   ├── wiki/topics/      #     主题综述
│   │   ├── wiki/synthesis/   #     跨源对比
│   │   ├── wiki/sources/     #     来源摘要
│   │   └── search-index.json #     检索索引
│   └── kb/                   #   分层知识库
├── data/                     #   运行时数据（二级 git，隐私数据）
│   ├── system/config.yaml    #     配置文件（含 token，不进 git）
│   ├── raw/core.db           #     SQLite 数据库
│   ├── facts/people/         #     人物事实档案
│   ├── facts/self/           #     自我档案
│   ├── outputs/              #     生成产物
│   │   ├── rankings/         #       排名快照
│   │   ├── reports/          #       周报
│   │   ├── analysis/         #       分析结论
│   │   └── evaluations/      #       评估记录
│   └── input/                #     截图输入
├── tools/                    #   文档处理工具
│   ├── pdf2md.py             #     PDF → Markdown
│   ├── epub2md.py            #     epub → Markdown
│   ├── doc2md.py             #     doc/docx → Markdown
│   ├── generate_wiki_index.py #    Wiki 索引生成
│   └── label_stickers.py     #     贴纸标注 HTML 页面
├── tests/                    #   单元测试
│   ├── conftest.py           #     共享 fixture（临时 DB/Config/消息数据）
│   ├── test_formulas.py      #     战态公式测试
│   ├── test_metrics.py       #     指标计算测试
│   └── test_identity.py      #     身份解析测试
├── pytest.ini                #   pytest 配置
└── readme/                   #   系统设计文档 + 模块文档
    ├── PROJECT.md            #     项目总览（Wiki 主轴 + 公式辅助参考架构）
    ├── formulas.md           #     公式参考（辅助视角，含演进链条）
    ├── facts.md              #     事实档案（evidence/evaluation 分层 + 自检清单）
    ├── mcp.md                #     MCP 工具文档（49 个工具）
    ├── architecture_correction_completed.md  # 架构矫正完成记录
    ├── future_formula_wiki_metadata.md       # P6 未来计划：公式-Wiki 结构化元数据
    └── ...                   #     其他模块文档
```

---

## 六、Agent Skills 详解

### 6.1 love-mentor.md — 统一入口

Agent 的主控文件，包含：

**决策树**（场景路由）：

1. 分析某个人的关系
2. 紧急回复
3. 约会现场
4. 搜索知识
5. 开放求助
6. 心理侧写
7. 记录信息
8. 保存分析结论
9. 周报
10. 展示面诊断
11. 挽回/冷激活

**信息门**：根据用户提供的信息量决定行为（充分→直接分析 / 部分→先给方向再问 / 不足→问 2-3 个问题）。

**回复构造规则**（从 qingsheng-skill 融入）：

- 对话领导原则：浅话题必须 pivot 到性格/感受/价值观
- 粘贴长度触发：>=5 条消息时进入深度分析模式
- 软抗拒时坚持推进：软抗拒+正面信号时坚持框架
- 每次回复必须有一条可直接发送的消息
- 话术必须 context-consistent（不编造不存在的叙事）
- 时间线感知：分析聊天时第一件事梳理时间线

**路由表**：场景关键词 → 推荐 Wiki 页面 / 公式工具。

**指标体系速查**：指标权重 + 乘法惩罚 + 信号等级 + 互动模式。

**关系阶段定义**：初识→退出/失败 + 阶段对照表。

**辅助参考：公式工具**：各公式的用法和阈值（辅助视角，核验而非套用）。

### 6.2 person-info.md — 人物信息管理

管理 `data/facts/people/` 下的事实档案。

- 核心原则：只记录客观事实，不做分析
- 工具：contact、note、date、evaluate、events、evidence、status
- 档案格式：多个 section（基本信息/数据概览/关系时间线/当前状态/关键信息/Dates/Notes）

### 6.3 chat-analyzer.md — 聊天深度分析

四步工作流：

1. 同步 + 获取数据（sync_person/brief/chat/metrics/evidence）
2. 加载 Wiki 知识库（wiki_search/wiki_show）
3. 使用公式作辅助参考分析（formula_params/formula_ivi/formula_spe/formula_ews/formula_action，核验而非套用）
4. 分析输出（阶段判断/窗口信号/问题诊断/下一步行动/整体策略）

---

## 七、已删除组件

### 7.1 Skills（已融入主系统）

| Skill             | 融入方式                                                                                     |
| ----------------- | -------------------------------------------------------------------------------------------- |
| chat-skills       | IVI/SPE/EWS 公式 →`engine/formulas.py`；量化 SOP → `formula_params` 的 manual 参数提示 |
| love-gto          | 路由表 → love-mentor.md；Key Frameworks → Wiki entity 页面（待补充）                       |
| dating-master     | 语用学/依恋理论/信号博弈 → Wiki entity 页面（待补充）                                       |
| love-coach-master | Gottman/Perel/Johnson → Wiki entity 页面（待补充）                                          |
| qingsheng         | 回复规则/信息门 → love-mentor.md；展示面诊断/挽回 playbook → 决策树引用                    |

每个已删除 skill 目录下保留了 `SYSTEM_OVERLAP.md` 和 `ANALYSIS.md` 作为分析记录。

### 7.2 CLI（已删除）

原 `cli/love.py` 的所有命令已迁移到 `engine/tools.py` 的工具函数。Agent 直接调用工具，不再通过 CLI。

### 7.3 LLM 管道（已删除）

原 `engine/llm/`（Anthropic SDK 封装）和 `engine/agent/pipeline_*.py`（代码调 LLM 的管道）已删除。`config.py` 中的 `LLMConfig` 类也已清理。LLM 推理完全由 Agent 自身完成。

### 7.4 Workbench 重导出层（已删除）

原 `engine/agent/workbench.py` 是纯重导出层，已删除。`tools.py` 现在直接从各 agent 模块导入。

### 7.5 Apps（已删除）

原 `apps/` 目录包含两个独立项目，均已删除：
- **mikey-dating-coach**：Node.js Telegram bot（从 GitHub 抓取的参考项目）
- **dating-assistant**：旧版 Python 恋爱分析系统（基于微信导出文件 + Claude API）

两者的功能已被主系统完全替代：数据来源从微信导出文件改为 WeFlow/WCD API，分析从调 Claude API 改为 Agent 自行分析。

---

## 八、Skill-MCP 融合架构

### 8.1 设计理念

本系统采用"**Skill 编排流程 + MCP 执行能力**"的融合架构：

| 层级 | 职责 | 实现 |
|------|------|------|
| **Skill 层** | 业务流程编排、决策规则定义、方法论框架 | `skill/` 下的 Markdown 文件 |
| **MCP 层** | 标准化数据接口、工具执行、安全隔离 | `mcp_server/` 下的 Python 工具 |
| **双向导航** | 工具与文档的双向索引、工作流指引 | `skill_map()` / `workflow_step()` |

### 8.2 核心工具

| 工具 | 功能 | 参数 |
|------|------|------|
| `skill_map(tool_name)` | 查询工具与 Skill 的双向映射，返回下一步建议 | `tool_name`: 工具名（可选） |
| `workflow_step(workflow, step)` | 按步骤执行工作流，返回当前步骤详情和下一步指引 | `workflow`: 工作流名, `step`: 步骤编号（可选） |

### 8.3 工作流列表

| 工作流 | 名称 | 步骤数 | 适用场景 |
|--------|------|--------|----------|
| `analysis` | 人物分析完整流程 | 11 步 | "分析XX"、"帮我看看XX" |
| `emergency_reply` | 紧急回复流程 | 4 步 | "她发了XX怎么回" |
| `weekly` | 周报流程 | 2 步 | "做周报" |
| `maintain` | 维持关系流程 | 4 步 | "维持关系" |

### 8.4 Skill 渐进式披露结构

```
skill/
├── love-mentor.md           # 主入口（场景路由 + 核心原则）
├── mcp-analysis.md          # 分析流程 + 决策树
├── mcp-methodology.md       # 方法论（Wiki主轴/公式辅助/冲突裁决）
├── mcp-rules.md             # 规则（权限/事实档案/回复构造）
├── mcp-tools.md             # 工具速查
├── mcp_index.yaml           # 双向索引数据源
├── workflows/               # 工作流子文件（渐进式披露）
│   ├── analysis.md          # 分析流程详细步骤
│   ├── emergency_reply.md   # 紧急回复流程
│   ├── weekly.md            # 周报流程
│   └── maintain.md          # 维持关系流程
├── signals/                 # 信号解读子文件
│   ├── basic_signals.md     # 基础信号
│   └── manipulation_signals.md # 操控信号
├── metrics/                 # 指标体系子文件
│   └── metrics_system.md    # 22维指标详解（16行为统计+6 Wiki衍生+3语义）
└── formulas/                # 公式子文件
    ├── war_formulas.md      # 战态公式
    └── skill_map.md         # 公式-Skill映射
```

### 8.5 使用模式

**模式 1：按工作流执行（推荐）**

```python
workflow_step('analysis')        # 查看流程概览
workflow_step('analysis', 0)     # 获取第0步详情
person_sync('XX')                # 执行第0步
workflow_step('analysis', 1)     # 获取第1步详情
person_brief('XX')               # 执行第1步
# ...
```

**模式 2：工具驱动探索**

```python
skill_map('person_brief')        # 查 person_brief 之后能调什么
# 根据返回的下一步建议选择工具
```

---

## 九、二级 Git 仓库

- **一级 repo（loveMentor/）**：代码 + 公开文档，可推远程。根 `.gitignore` 已忽略 `data/` 和 `docs/`。
- **二级 repo（data/）**：隐私数据，只在本地有 git 历史，不推远程。

---

## 十、已归档规划（plan/ 已删除）

以下规划文档已完成并从 `plan/` 删除，关键内容已整合到本文档和代码中：

| 规划文件 | 内容摘要 | 整合位置 |
|----------|----------|----------|
| `b2_deployment.md` | B0'/B2 双模型部署、决策框架 | 本文档 2.11 节 |
| `b1_experiment_protocol.md` | B1' 实验协议（失败 → B2 方案取代） | 本文档 2.11 节 |
| `b1_smoke_run.md` | B1-smoke 运行记录 | 实验历史 |
| `codex_建议.md` | 架构批判：从"她对我"到三视角 | 本文档 2.12 节 + `turn_stats()` |
| `role_labeling_design.md` | 角色标注方案（target_other_v1 协议） | `ml/models/` + 训练脚本 |
| `model_inference_mismatch.md` | 训练/推理格式不匹配（已修复） | `ml/input_format.py` |
| `git-cleanup-plan.md` | 隐私文件清理 + .gitignore 更新 | `.gitignore` + 已执行 |
| `目录重组方案.md` | 项目目录结构优化（tools/ 拆分5子目录、回测移入 engine/、stickers 重构为包） | 本文档工程结构 + `tools/README.md` |
| `三层视角架构改造方案.md` | SELF/OTHER/INTERACTION 三视角设计（Phase 0 完成，Phase 1/2 阻塞） | 本文档 2.12 节 + `interaction_sequence.py` + `next_steps.md` |

`data/.gitignore` 规则：

| 纳入跟踪                          | 忽略                               |
| --------------------------------- | ---------------------------------- |
| `facts/people/` — 人物事实档案 | `raw/` — 二进制数据库、媒体文件 |
| `facts/self/` — 自我档案       | `cache/` — 可重建缓存           |
| `outputs/analysis/` — 分析结论 | `outputs/exports/` — 一次性导出 |
| `outputs/rankings/` — 排名快照 | `system/config.yaml` — 含 token |
| `outputs/reports/` — 周报      |                                    |

---

## 十一、隐私规则

- 禁止在任何非 `.gitignore` 文件中写入真实联系人信息，用假名代替
- `data/raw/core.db`、`data/system/config.yaml`、`data/facts/people/` 均为私有本地数据
- 截图输入（`data/input/`）不进 git

---

## 十二、外部依赖

| 依赖                 | 用途                          | 必须？         |
| -------------------- | ----------------------------- | -------------- |
| pyyaml               | 配置文件解析                  | 是             |
| pytest               | 单元测试                      | 开发           |
| rapidocr-onnxruntime | 截图 OCR                      | 仅 import-chat |
| Pillow               | 图片尺寸读取                  | 仅 import-chat |

同步管道和分析器使用 Python 标准库（sqlite3、urllib、json）。
