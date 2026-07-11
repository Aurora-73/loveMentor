# 去重工具集

将 `.dsr`（文件查重结果，gzip 压缩 XML）解析为易读的 JSON，并执行多级去重。

## 数据流程

```
.dsr (gzip XML) ──→ dsr2json.py ──→ .json (易读)
                                   └──→ filedb.py (内存索引)
                                            │
                     dedup_dsr.py ───────────┤
                     report_win_rename.py ───┤
                     find_dup_folders.py ────┤
                                            ↓
                                     去重决策 + 文件删除
```

## 文件说明

### filedb.py — 核心库

将 `.dsr` 解析为多层索引结构：

| 属性 | 类型 | 用途 |
|------|------|------|
| `.files` | `list[FileRec]` | 按(目录,文件名)排序，同目录连续 |
| `.by_sid` | `dict[str, list]` | 内容分组索引 O(1) |
| `.by_dir` | `dict[str, list]` | 目录索引 O(1) |

**FileRec:**
- `path` — 完整绝对路径
- `dir` — 父目录
- `name` — 文件名
- `sid` — 内容分组 ID（hex）
- `fl` — 文件角色（1=原始, C=副本, 8=[REDACTED]）
- `paren_count` — 路径中 `(1)` 后缀层数
- `name_len` — 文件名长度

**关键方法：**
- `FileDB.from_dsr(path)` — 解析 .dsr
- `.summary()` — 打印概况
- `.rename_dupes()` — 路径仅差 `(1)` 的重复组
- `.dup_folders()` — 完全重叠的目录组
- `.dedup_keep_dir(dir)` — 保留指定目录
- `.dedup_samedir_longest()` — 同目录保留最长名
- `.clean_rename_dupes(execute)` — 清理 `(1)` 副本
- `.apply(to_delete, execute)` — 安全删除并清理索引
- `.save_dsr(path)` — 导出为 .dsr

### dsr2json.py — 格式转换

```
python dsr2json.py <文件.dsr> [-o 输出.json] [--compact]
```

转 JSON 后的结构：

```json
{
  "groups": [{"sid": "1E2", "count": 3, "files": ["path1", "path2", ...]}],
  "dirs": {"目录路径": {"count": N, "files": [...]}}
}
```

### dedup_dsr.py — 多级去重 CLI

```
python dedup_dsr.py <文件.dsr> [--execute] [--trash]
```

内置规则：
1. **[REDACTED] 优先** — 组内如有文件在 `[REDACTED]` 下，删外部所有副本
2. **同目录留长名** — 同目录下不同名，保留文件名最长的

### report_win_rename.py — (1) 后缀清理

```
python report_win_rename.py <文件.dsr> [--execute] [--trash]
```

找出路径仅差 Windows 自动重命名 `(1)` 后缀的重复组。**包含文件夹级和文件级**的 `(1)` 匹配。

### cross_dir_dedup.py — 跨目录优先级去重

```
python cross_dir_dedup.py <文件.dsr> [--execute]
```

按目录路径评分规则（低分优先保留），每个重复组内只保留评分最优目录下的文件。适用于 `(1)` 目录副本、多个目录存放相同内容等跨目录重复场景。

### find_dup_folders.py — 重复文件夹检测

```
python find_dup_folders.py <文件.dsr>
```

找出子文件（内容）完全重叠的目录，汇报不删除。

## 去重策略（优先级从高到低）

| 优先级 | 规则 | 依据 | 代码 |
|--------|------|------|------|
| 1 | [REDACTED] 优先 | 文件夹路径 | `dedup_dsr.py` |
| 2 | (1) 后缀清理 | 路径模式 | `report_win_rename.py --execute` |
| 3 | 同目录留长名 | 同目录下不同文件名 | `dedup_dsr.py --execute` |
| 4 | 模糊同名跨目录 | 归一化文件名相同 | 分析脚本 |
| 5 | 目录优先级 | 路径评分（整理大集合 > 可复制展示面 > 等多个文件 > 其余） | 分析脚本 |

**目录优先级评分（低分优先保留）：**
- `(1)` 路径: +200
- `整理大集合`/`整理合集`: -100
- `高价值展示面`/`高端展示面全`: -50
- `可复制展示面`: +80
- `等多个文件`: +50
- 路径深度: `+depth*2`
- E 盘: -20

## 文件名模糊归一化

用于判断"文件名是否相同"时，先做以下归一化：

1. 去掉首尾引号、括号、破折号、空格
2. 去掉尾部 `...` 或 `…`
3. 去掉开头编号（如 `10.`、`11、`）
4. 去掉营销文字（如 `更多资料添加微信xxx`）
5. 折叠多余空格
6. 转小写

## .dsr 文件格式

- 外层：gzip 压缩
- 内层：UTF-8 XML
- 所有数值属性均为 **hex 编码**
- `d` — 目录索引（1-based, hex）
- `sid` — 内容重复组 ID
- `s` — 内容 hash
- `dt` — 时间戳
- `fl` — 文件角色（1=原始, C=副本, 8=[REDACTED]）
- `fr` — 序号

## dsr 解析要点

```python
d_idx = int(elem.get('d'), 16) - 1    # hex 转 0-based 索引
dir_path = resolve_dir(d_idx, dirs, scan_root)
full_path = os.path.join(dir_path, elem.get('n'))
```

相对路径（`.\xxx`）需要拼接 `scan_root`，由绝对路径公共前缀推断。
