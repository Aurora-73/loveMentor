# Wiki 知识库

## 概述

`engine/knowledge/` 提供 Wiki 知识库的检索能力。Wiki 内容存储在 `docs/wiki/` 目录下，本模块负责索引、搜索、格式化输出。

## 核心文件

| 文件 | 行数 | 功能 |
|------|------|------|
| `wiki_index.py` | 311 | Wiki 索引（加载 search-index.json 或扫描 frontmatter） |
| `wiki_retriever.py` | 291 | 检索器（关键词匹配 + 评分 + 预算裁剪） |
| `wiki_context.py` | ~80 | 格式化输出（提取关键步骤，适配 prompt 注入） |

## Wiki 内容结构

```
docs/wiki/
├── search-index.json      # 预构建索引（快速加载）
├── .wiki-schema.md        # 别名表（同义词扩展）
└── wiki/
    ├── entities/          # 概念/框架
    │   ├── IOI（兴趣指标）.md
    │   ├── 推拉.md
    │   └── 需求感控制.md
    ├── scenarios/         # 场景决策页
    │   ├── 从线上到第一次见面.md
    │   ├── 被发好人卡她说做朋友.md
    │   └── 她不回消息了怎么办.md
    ├── comparisons/       # 跨源对比
    ├── queries/           # 主题综述
    └── overview.md
```

每个 Markdown 文件有 YAML frontmatter：

```yaml
---
title: IOI（兴趣指标）
type: entity
tags: [IOI, 兴趣指标, 信号识别, 核心概念]
keywords: [IOI, interest, indicator, 信号]
stages: [初识, 有基本互动, 高频聊天, 暧昧推进]
skills: [聊天技巧, 推拉]
---
```

## WikiIndex（索引）

```python
class WikiIndex:
    def __init__(self, wiki_root: Path):
        """加载索引。优先从 search-index.json 加载，不存在则扫描 frontmatter。"""

    def search(self, query: str) -> list[WikiPage]:
        """按关键词搜索。"""
```

### WikiPage

```python
@dataclass
class WikiPage:
    id: str                    # 页面唯一标识
    title: str                 # "IOI（兴趣指标）"
    path: str                  # 相对 Wiki 根目录的路径
    page_type: str             # "entity" / "topic" / "synthesis" / "scenario"
    summary: str               # 页面摘要
    tags: list[str]            # frontmatter tags
    keywords: list[str]        # frontmatter keywords
    search_terms: list[str]    # 全文搜索词
    scenarios: list[str]       # 适用场景
```

### 别名扩展

`expand_query()` 使用 `.wiki-schema.md` 中的别名表扩展搜索词。例如搜"好人卡"会自动扩展为"friendzone""友谊区""被拒绝"。

## WikiRetriever（检索器）

```python
class WikiRetriever:
    def __init__(self, index: WikiIndex):
        """初始化检索器。"""

    def retrieve(self, query: str, task_type: str = "default",
                 max_pages: int = 5, max_chars: int = 5000) -> list[WikiSnippet]:
        """搜索 + 评分 + 裁剪。"""
```

### 评分逻辑

每个 WikiPage 的得分基于多维度匹配：

| 维度 | 权重 | 说明 |
|------|------|------|
| title 精确匹配 | 高 | 标题包含搜索词 |
| keyword 匹配 | 中 | frontmatter keywords 匹配 |
| tag 匹配 | 中 | frontmatter tags 匹配 |
| search_term 匹配 | 低 | 全文搜索 |
| stage 匹配 | 中 | 与当前关系阶段匹配 |
| skill 匹配 | 低 | 与推荐 skill 匹配 |

### task_type 预算

不同场景有不同的页面数和字数预算：

| task_type | max_pages | max_chars | 典型场景 |
|-----------|-----------|-----------|---------|
| `default` | 5 | 5000 | 一般分析 |
| `reply` | 3 | 2500 | 紧急回复（要快） |
| `deep` | 8 | 10000 | 深度分析 |
| `search` | 10 | 8000 | 用户主动搜索 |

### WikiSnippet

```python
@dataclass
class WikiSnippet:
    title: str
    path: str
    page_type: str
    summary: str              # 页面摘要
    content: str              # 裁剪后的内容
    tags: list[str]           # 页面标签
    source_tier: list[str]    # 来源层级
    confidence: str           # 置信度标注
    score: float              # 匹配分数
```

## 格式化输出（wiki_context.py）

```python
def format_wiki_for_prompt(snippets: list[WikiSnippet]) -> str:
    """将 WikiSnippet 列表格式化为可注入 prompt 的 Markdown。"""
```

输出格式：

```markdown
## Wiki: IOI（兴趣指标）
> 来源: docs/wiki/wiki/entities/IOI（兴趣指标）.md | 类型: entity

（关键步骤提取后的内容）

## Wiki: 推拉
> 来源: docs/wiki/wiki/entities/推拉.md | 类型: entity

（关键步骤提取后的内容）
```

`_extract_key_steps()` 从长文档中提取关键步骤（限制 1500 字），避免注入过长内容。

## 数据流

```
tools.py: wiki_search('IOI')
    ↓
material.py: WikiIndex → WikiRetriever.retrieve('IOI')
    ↓
1. expand_query('IOI') → ['IOI', '兴趣指标', 'interest indicator']
2. search() → 匹配 WikiPage 列表
3. 评分排序
4. 裁剪到预算内
    ↓
返回 Markdown（标题 + 路径 + 摘要）

tools.py: wiki_show('docs/wiki/wiki/entities/IOI（兴趣指标）.md')
    ↓
直接读取文件内容，返回 str
```

## 注意事项

1. **search-index.json 是预构建的**：新增 Wiki 页面后需要运行 `tools/generate_wiki_index.py` 更新索引。如果索引不存在，会回退到扫描 frontmatter（较慢）。
2. **别名表在 `.wiki-schema.md`**：同义词扩展依赖这个文件。如果搜索结果不理想，检查别名表是否覆盖了相关词。
3. **wiki_show 只读文件**：不做任何评分或裁剪，直接返回文件全部内容（受 max_chars 限制）。
4. **wiki_search 不需要 person**：只需要 conn 和 config（用于定位 wiki 根目录），不涉及具体联系人。
5. **内容不进 git**：`docs/` 目录有独立的二级 git 仓库，不推远程。
