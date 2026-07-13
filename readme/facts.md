# 事实档案

## 概述

`engine/facts/` 管理两类持久化事实数据：人物事实档案（per-person Markdown）和失败案例归档（YAML）。事实层只记录客观事实，不做分析、不做诊断、不做策略。

## 概念分层：事实档案 vs 分析归档

> **重要**：概念上拆为两层。文件结构暂不重构（evaluate 仍写在事实档案文件内），但概念上必须区分。

| 层 | 概念 | 包含的工具 | 性质 | 冲突裁决优先级 |
|----|------|-----------|------|--------------|
| **事实档案（evidence layer）** | 客观事实，不可污染 | `note` / `date` / `events` / 用户补充 | 客观记录，高可信 | 2（仅次于实时数据） |
| **分析归档（evaluation layer）** | 主观判断，仅作参考 | `evaluate` / `save_analysis` / `save_from_markdown` | 主观判断，可能过时 | 5（最低，低于公式） |

**关键区分**：
- `person_evaluate` 工具写入的"评估"在概念上属于**分析归档**，不属于事实档案。虽然当前文件结构中 evaluations 段落写在事实档案文件内，但 Agent 读取时应将其视为低优先级的主观判断，不能与客观事实同等对待。
- `note` / `date` / `events` 写入的是客观事实（对方原话、对方行为、客观事件），属于事实档案，高可信。

## 写入事实档案的自检清单

**核心原则**：事实档案是**输入层**，不是输出层。Agent 写入前必须自问："这条信息是我观察到的，还是我推断的？"

| ✅ 可以写入（客观事实） | ❌ 不可写入（主观判断） |
|----------------------|----------------------|
| 对方原话："我有一点芒果过敏" | "她对我有好感，值得追" |
| 对方行为："凌晨 00:32 主动发消息约饭" | "她肯定喜欢我" |
| 用户补充："上次见面对方很满意" | "本月表白成功率 80%" |
| 事件记录："6/1-6/15 断联 15 天" | "对方已经不喜欢我了，不用再追" |

**自检三问**（写入前必答）：

1. **这条信息是对方说的/做的，还是我推断的？** → 只能写前者
2. **如果换一个 Agent 读这条信息，会得出同样的结论吗？** → 如果不会，说明掺杂了判断
3. **这条信息 3 个月后还有效吗？** → 事实是稳定的，判断会过时

**特殊说明**：`person_evaluate` 工具写入的"评估"是唯一例外——它允许 Agent 写主观判断，但必须**概念上归入分析归档**而非事实档案。Agent 读取时应对 evaluations 段落保持批判性，不能将其与 notes/events/dates 等客观事实同等对待。

## 核心文件

| 文件 | 行数 | 功能 |
|------|------|------|
| `people_archive.py` | 221 | 人物事实档案读写（Markdown + YAML frontmatter） |
| `failure_archive.py` | 102 | 失败案例归档（YAML） |

## 人物事实档案（people_archive.py）

### 存储位置

```
data/facts/people/
├── 小溪__person_abcd1234.md
├── 阿琳__person_efgh5678.md
└── ...
```

文件: 小溪__person_abcd1234.md

### 文件结构

```markdown
---
person_id: person_abcd1234
display_name: 小溪
created_at: 2026-01-15
updated_at: 2026-06-12
---

## Notes
- [2026-04-01 14:30] 她说喜欢猫
- [2026-04-15 09:12] 在医院工作，白班很累

## 关系时间线
- [2026-04-10] DISCONNECT: 断联 10 天
- [2026-04-20] RECONNECT: 恢复联系

## Dates
### 2026-05-01
- 地点：湖边散步；评分：4/5

## evaluations
- [2026-05-10] 回复变慢了，可能在忙
```

### 关键函数

```python
def get_person_archive_path(person: IdentityPerson, *, my_wxid: str = "") -> Path:
    """生成档案文件路径。my_wxid 非空时，本人档案存到 facts/self/ 而非 facts/people/。"""

def append_note(person: IdentityPerson, text: str, *, my_wxid: str = "") -> Path:
    """添加备注到 ## Notes 段落。格式：- [YYYY-MM-DD HH:MM] 内容。返回写入路径。"""

def append_event(
    person: IdentityPerson, event_date: str, event_type: str, detail: str,
    *, my_wxid: str = "",
) -> tuple[Path, bool]:
    """将事件写入 ## 关系时间线 段落。返回 (path, is_new)：is_new=False 表示重复跳过。"""

def append_date_entry(
    person: IdentityPerson, *,
    date_text: str | None, location: str | None, rating: int | None,
    my_wxid: str = "",
) -> Path:
    """添加约会记录到 ## Dates 段落。"""

def rename_person_archive(
    person: IdentityPerson, new_display_name: str, *, my_wxid: str = "",
) -> Path | None:
    """重命名档案文件（display_name 变更时调用）。"""

def ensure_people_archives_migrated(conn, my_wxid: str) -> None:
    """从旧路径（data/wiki/people/）迁移档案到 data/facts/people/。"""
```

> **注意**：`read_archive` 函数已不存在。读取档案由 `engine/agent/evidence.py` 中的 `agent_evidence` 直接读取文件内容实现。

### 段落管理

档案按 `##` 标题分段。`_ensure_section(content, section_name)` 确保段落存在，`_append_to_section(content, section_name, line)` 在段落末尾追加。

### frontmatter 管理

`_ensure_frontmatter(content, person)` 维护 YAML frontmatter（person_id/display_name/created_at/updated_at）。每次写入时自动更新 `updated_at`。

## 失败案例归档（failure_archive.py）

### 存储位置

```
data/facts/failures/
├── 2026-03-20_阿七.yaml
└── ...
```

### YAML 结构

```yaml
person: 阿七
date: 2026-03-20
stage: 退出/失败
signals:
  - "不太合适"
  - "先做朋友吧"
diagnosis: 需求感过强，被明确拒绝后继续追
lessons:
  - 被明确拒绝后立即停止主动
  - 沉默永远比示弱好
```

### 关键函数

```python
def save_failure(case: FailureCase) -> Path:
    """保存失败案例到 YAML 文件。返回文件路径。文件名：{date}_{person_slug}.yaml。"""

def load_all_failures() -> list[FailureCase]:
    """加载所有失败案例，返回 FailureCase 对象列表。"""

def find_similar_failures(
    current_stage: str, current_signals: list[str] = None,
) -> list[FailureCase]:
    """查找相似失败案例（按 stage 子串或 signal 重叠匹配）。返回 FailureCase 对象列表。"""

def format_failures(cases: list[FailureCase]) -> str:
    """格式化失败案例列表为 Markdown。"""
```

## 数据流

```
tools.py: note('小溪', '她说喜欢猫')
    ↓
write.py: agent_note → facts/people_archive.py: append_note()
    ↓
写入 data/facts/people/小溪__person_abcd1234.md

tools.py: evidence('小溪', section='notes')
    ↓
evidence.py: agent_evidence → facts/people_archive.py: read_archive()
    ↓
读取 data/facts/people/小溪__person_abcd1234.md
```

## 与 analysis 的区别

> 概念上分两层：**事实档案**（evidence layer，客观事实）和**分析归档**（evaluation layer，主观判断）。`person_evaluate` 虽然写入事实档案文件内，但概念上属于分析归档。

| | 事实档案（evidence layer） | 分析归档（evaluation layer） |
|---|---|---|
| 内容 | 客观事实：备注、事件、约会 | 主观判断：评估、阶段、诊断、策略 |
| 存储 | `data/facts/people/*.md`（notes/events/dates 段落） | `data/facts/people/*.md`（evaluations 段落）+ `data/outputs/analysis/*/latest.yaml` |
| 写入 | `note()` / `date()` / `events()` | `evaluate()` / `save_analysis()` / `save_from_markdown()` |
| 原则 | 只记录，不分析 | Agent 的分析输出，低优先级参考 |
| 冲突裁决优先级 | 2（高，仅次于实时数据） | 5（最低，低于公式） |

## 注意事项

1. **幂等追加**：`append_note`/`append_event` 是追加操作，不会覆盖已有内容。
2. **文件名编码**：display_name 可能含中文，文件系统需要支持 UTF-8。
3. **migration**：`people_archive.py` 包含从旧路径（`data/wiki/people/`）迁移的逻辑。
4. **分析结论存在别处**：`save_from_markdown` 写入 `data/outputs/analysis/`，不在 `data/facts/`。
5. **分析版本管理**：`save_analysis` 会自动备份 `latest.yaml` 到 `previous.yaml`，可用 `compare_analysis(name)` 对比变化。
