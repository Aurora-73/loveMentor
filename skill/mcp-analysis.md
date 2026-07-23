# 分析工作流 — 完整流程 + 决策树 + 报告模板

## 核心原则：Wiki 贯穿全程

Wiki 不是"第二步做完就不管了"的参考材料。它是推理主轴，在分析过程的每个环节都应随时查阅：
- 看到 brief 信号 → 查 Wiki 理解信号含义
- 看到聊天模式 → 查 Wiki 找话术和互动策略
- 看到指标数据 → 查 Wiki 解读指标背后的含义
- 看到关系阶段 → 查 Wiki 找阶段策略
- 写报告时 → 查 Wiki 引用具体条目作为策略依据

**工作流导航**：`workflow_step('analysis')` 查看完整流程步骤；`skill_map(tool_name)` 查询工具映射

---

## 完整分析流程

### 第零步（必须）：同步最新消息 — 【MCP工具】`person_sync(name)`
不同步看到的是旧数据，可能遗漏最近聊天。耗时几秒。同步失败不阻塞分析。

⚠️ 联系人搜不到（PERSON_NOT_FOUND）时：
1. `system_sync(meta_only=True)` — 【MCP工具】同步联系人列表（约 1 秒）
2. `contact_search(query)` — 【MCP工具】搜索联系人
3. 找到了 → `person_sync(name)` 同步消息后继续
4. 还是没找到 → 告诉用户"微信里没有和这个人的聊天记录"

**下一步**：`person_brief` 获取全局视图

---

### 第一步：获取全局视图 + 初次 Wiki 查询
1. `person_brief(name)` — 【MCP工具】结构化数据：身份信息、指标、事件、信号、Wiki 推荐
2. 看到 brief 中的信号后，立即查 Wiki 建立方法论框架：
   - `wiki_context(queries, stage, focus)` — 【MCP工具】【推荐主入口】批量构建知识框架（替代分散的 wiki_search+wiki_read）
   - `wiki_search("关键词")` — 精确搜索某关键词（钻取时使用）
   - `wiki_read("路径")` — 读取具体页面全文（引用时使用）

常用 Wiki 框架速查：
| 信号 | 推荐搜索词 |
|------|-----------|
| 兴趣指标 | IOI 兴趣指标 |
| 回复变慢 | 70%频率法则 需求感 |
| 约会 | 从线上到第一次见面 |
| 忽冷忽热 | 推拉 情绪波动 |
| 表白时机 | 窗口识别 |

**下一步**：`person_chat` 查看聊天记录

---

### 第二步：详细数据 + 持续 Wiki 查询
逐步获取数据，每看到新信息就用 `wiki_context(queries, stage, focus)` 查 Wiki 解读（下方 wiki_search 关键词可传入 queries 参数）：

1. `person_chat(name, recent=200)` — 【MCP工具】聊天记录
   → 看到聊天模式后：`wiki_search("聊天技巧"/"推拉"/"冷读")`
2. `person_metrics(name)` — 【MCP工具】指标数据
   → 看到具体数值后：`wiki_search("频率法则"/"需求感"/"IOI")`
3. `person_signals(name)` — 【MCP工具】信号详情
   → 看到信号类型后：`wiki_read` 读取对应框架全文
4. `person_stage(name)` — 【MCP工具】关系阶段
   → 看到阶段后：`wiki_search("阶段策略"/"升温"/"推进")`
5. `person_timeline(name)` — 【MCP工具】关系时间线
   → 看到趋势后：`wiki_search("趋势分析"/"降温"/"窗口期")`
6. `person_evidence(name)` — 【MCP工具】事实档案
   → 对比历史事实与 Wiki 框架
7. `person_moments_stats(name)` — 【MCP工具】朋友圈互动
   → `wiki_search("展示面"/"朋友圈"/"社交认证")`

**下一步**：`formula_get_params` 获取公式参数

---

### 第三步：公式核验 + Wiki 交叉验证
- `formula_get_params(name)` — 【MCP工具】获取自动参数
- `formula_calc_ivi(...)` / `formula_calc_spe(...)` / `formula_calc_ews(...)` — 【MCP工具】量化视角
- `formula_calc_action(...)` — 【MCP工具】终极决策参考

⚠️ 公式数值只在"数据全貌"表出现一次，策略全部回指 Wiki 条目
⚠️ 不机械套阈值。IVI=0.5 不一定比 IVI=1.1 差，结合 Wiki 判断
→ 公式结果与 Wiki 矛盾时？以 Wiki 为准，公式仅作参考

**下一步**：`save_from_markdown` 保存分析报告

---

### 第四步（必须）：保存分析报告
1. 【必须】`save_from_markdown(name, markdown_text)` — 【MCP工具】写入 latest.md + latest.yaml
2. 【可选】`person_save_analysis(name, stage=..., confidence=..., ...)` — 【MCP工具】补充结构化字段

**工作流完成** ✅

---

## 决策树：用户想要什么 → 怎么做

### 场景 1：分析某个人的关系
```
用户说"帮我分析XX" / "XX的情况" / "看看XX"
  ├─ person_sync("XX")          # 【MCP工具·必须】同步
  ├─ person_brief("XX")         # 【MCP工具】全局视图
  ├─ wiki_search(信号关键词)     # 【MCP工具】读 Wiki 框架
  ├─ person_chat("XX", recent=200)  # 【MCP工具·可选】看聊天
  ├─ person_evidence("XX")      # 【MCP工具·可选】追溯事实
  ├─ person_metrics/signals/stage  # 【MCP工具】指标+信号+阶段
  ├─ formula_calc_*              # 【MCP工具·可选】公式核验
  └─ save_from_markdown("XX", 报告)  # 【MCP工具·必须】保存
```
**工作流**：`workflow_step('analysis')` 查看完整步骤

### 场景 2：紧急回复
```
用户说"她发了XX怎么回" / "怎么回复"
  ├─ person_sync("XX")          # 【MCP工具】同步
  ├─ person_chat("XX", recent=30)  # 【MCP工具】最近聊天
  ├─ person_metrics("XX")       # 【MCP工具】指标
  ├─ wiki_search("推拉 冷读 废物测试 邀约")  # 【MCP工具】找策略
  └─ 给出：一条可直接发送的推荐回复 + 备选 + 不要说 + 观察点
```

### 场景 3：约会现场
```
用户说"约会中" / "她说XX了怎么办"
  ├─ person_brief("XX")         # 【MCP工具】全局视图
  ├─ wiki_search("第一次约会 肢体接触")  # 【MCP工具】找策略
  └─ 即时建议：简短、可执行、不要长篇大论
```

### 场景 4：搜索知识
```
用户说"怎么推拉" / "什么是IOI" / "帮我搜一下XX"
  ├─ wiki_search("关键词")      # 【MCP工具】搜索
  ├─ wiki_read("路径")          # 【MCP工具】读全文
  └─ 结合知识内容回答
```

### 场景 5：开放求助
```
用户说"我该怎么办" / "她最近忽冷忽热" / "要不要放弃"
  ├─ person_sync("XX")          # 【MCP工具】同步
  ├─ person_brief("XX")         # 【MCP工具】全局视图
  ├─ wiki_search("忽冷忽热")     # 【MCP工具】找框架
  └─ 深度分析 + 策略 + 风险
```

### 场景 6：心理侧写
```
用户说"帮我侧写XX" / "XX是什么性格"
  ├─ person_sync("XX")          # 【MCP工具】同步
  ├─ person_chat("XX", recent=200)  # 【MCP工具】聊天记录
  ├─ person_evidence("XX")      # 【MCP工具】事实档案
  ├─ wiki_search("女性心理 冷读")  # 【MCP工具】找框架
  └─ 性格画像 + 沟通指南 + 冷读话术
```

### 场景 7：记录信息
```
用户说"帮我记一下XX" / "XX说了XX"
  ├─ person_note("XX", "内容")          # 【MCP工具】添加备注
  ├─ person_date("XX", date_text="2026-06-08", location="岳麓山", rating=4)  # 【MCP工具】记录约会
  ├─ person_evaluate("XX", "评估内容")  # 【MCP工具】记录评估
  └─ events_save("XX")                  # 【MCP工具】检测并写入事件
```

### 场景 8：周报
```
用户说"做一下周报" / "本周排名"
  ├─ system_sync()              # 【MCP工具】全局同步
  └─ weekly_report()            # 【MCP工具】生成周报
```
**工作流**：`workflow_step('weekly')` 查看完整步骤

### 场景 9：展示面诊断
```
用户说"帮我看看朋友圈" / "展示面诊断"
  ├─ wiki_search("展示面建设")   # 【MCP工具】找框架
  └─ 按平台维度打分：头像+简介+内容比例+社交场景
```

### 场景 10：挽回 / 冷激活
```
用户说"她不理我了" / "想挽回"
  ├─ person_sync("XX")          # 【MCP工具】同步
  ├─ person_brief("XX")         # 【MCP工具】看断联时间+信号
  ├─ wiki_search("挽回 冷激活 断联")  # 【MCP工具】找策略
  └─ 判断类型后给方案：冷激活/关系挽回
```

---

## 时间线感知

拿到聊天记录分析时，**第一件事梳理时间线**：
- 回复间隔：秒回还是几小时？有没有变化趋势？
- 主动 vs 被动：谁先发的？哪段是她主动？
- 密集 vs 冷淡：哪段热？哪段降温？降温前发生了什么？
- 最后一条：谁发的？多久没动静了？
- 整体趋势：升温还是降温？

时间维度直接影响建议：她连续 3 小时秒回然后突然不回 ≠ 她一直慢回。

---

## 分析报告模板（8 段式深度报告）

⚠️ 这不是简短摘要，而是详细分析报告。每段必须有实质内容。
⚠️ 策略段必须引用 Wiki 条目（[[条目名]] 格式）。

```markdown
# {显示名} 关系分析报告

> 分析日期：{YYYY-MM-DD}
> 数据来源：MCP 工具链（person_brief/metrics/stage/signals/timeline/chat）
> 知识库参考：{列出本次引用的 Wiki 条目}

## 一、场景理解（至少 3-5 句叙事）
- 当前关系阶段、互动周期、核心问题
- 用叙事方式描述情境
- 格式：阶段（置信度 XX%）+ 详细情境描述

## 二、数据全貌（表格，Wiki 解读列不能为空）
| 维度 | 数值 | Wiki 解读 |
|------|------|----------|
| 综合指数 | composite | [[窗口识别]] — 信号等级 |
| 回复字数比 | fback | [[IOI]] — 字数比反映兴趣 |
| 回复速度 | rlatency | [[70%频率法则]] |
| 聊天质量 | fback_quality | [[需求感控制]] |
| 个人化问题 | qscore_personal | [[意向判断]] |
| 趋势变化 | trend | [[窗口识别]] |
| 情绪波动 | escore_volatility | [[情绪波动技术]] |
| 朋友圈互动 | moments | [[展示面建设]] |
| 饥饿感 | msg_volume_trend | [[需求刺激]] |
| 最后联系 | recent | — |

公式参考（辅助视角）：IVI={} SPE={} EWS={}
→ 这些数值不主导策略，策略依据见下方 Wiki 诊断

## 三、关键信号分析（分积极/消极）
### 积极信号
| 信号 | 具体表现 | Wiki 来源 |
|------|---------|----------|
| 例：主动分享 | 她本周主动发了3次日常 | [[IOI]] |

### 消极信号
| 信号 | 具体表现 | Wiki 来源 |
|------|---------|----------|
| 例：回复变慢 | 平均回复时延从2h升到8h | [[70%频率法则]] |

## 四、Wiki 框架诊断（至少引用 3 个 Wiki 条目）
- 用多个 Wiki 条目交叉分析
- 每个条目先简述框架核心观点，再对照本案例数据
- 区分事实（她说了什么）和推断（可能什么意思）

## 五、具体操作（分阶段，每步引用 Wiki，含话术示例）
### 第一阶段（如：线上互动调整）
| 她的行为 | 信号 | 你该做什么 | Wiki 依据 |
|---------|------|-----------|----------|
| 例：问你在干嘛 | IOI | 不秒回，用推拉 | [[推拉]] |

### 第二阶段（如：推进约会）
- 具体邀约话术示例

## 六、绝对不要做（每条有 Wiki 依据）
| ❌ 不要做 | 原因 | Wiki 依据 |
|----------|------|----------|
| 例：秒回每条消息 | 暴露需求感 | [[需求感控制]] |

## 七、核心风险
| 风险 | 概率 | 说明 | 应对 |
|------|------|------|------|
| 例：关系降温 | 高 | 回复时延持续上升 | [[窗口识别]] |

## 八、底层判断
- 对当前关系本质的判断
- 用 **加粗** 标注关键结论
- 回指 Wiki 框架作为判断依据
```
