# 隐私排查工具

从数据库和配置导出隐私字典，扫描项目文件与 git 历史中的隐私泄露，并提供 git 历史篡改能力。

## 快速开始

```bash
# 1. 生成隐私字典库（从 core.db + config.yaml 自动导出）
python -X utf8 tools/private/build_dictionary.py

# 2. 编辑字典库，手动添加手机号/邮箱等
#    文件位置: data/private/dictionary.yaml → custom 区

# 3. 扫描当前项目文件
python -X utf8 tools/private/scan_files.py

# 4. 扫描 git 历史（排查过去的泄露）
python -X utf8 tools/private/scan_git_history.py

# 5. 如需从历史中去除隐私（先预览）
python -X utf8 tools/private/rewrite_git_history.py --dry-run
#    确认后执行
python -X utf8 tools/private/rewrite_git_history.py --force
```

## 文件结构

```
tools/private/
├── __init__.py
├── build_dictionary.py      # 导出隐私字典库
├── scan_files.py            # 扫描当前文件
├── scan_git_history.py      # 扫描 git 历史
├── rewrite_git_history.py   # 篡改 git 历史
└── README.md                # 本文件

data/private/                # 输出目录（在 data/ 下，已被 .gitignore）
├── dictionary.yaml          # 隐私字典库（自动生成 + 用户扩展）
├── scan_report.csv          # 当前文件扫描报告
└── git_scan_report.csv      # git 历史扫描报告
```

## 各脚本说明

### build_dictionary.py — 导出隐私字典库

**数据源：**
- `data/raw/core.db` → contacts 表 (nickname, remark, alias, wxid)
- `data/system/config.yaml` → my_name, my_wxid
- `data/facts/self/` → 文件名中的自我昵称

**输出：** `data/private/dictionary.yaml`

```yaml
my_identity:
  nickname: "茶"
  wxid: "wxid_xxx"
  remark: ""

contacts:
  - nickname: "测试联系人A"
    remark: ""
    alias: ""
    wxid: "wxid_xxx"

custom:          # ← 用户自定义区，手动新增
  - "138xxxx1234"
  - "xxx@gmail.com"
```

**注意：** 重复运行只刷新 `my_identity` 和 `contacts`，`custom` 区内容保留。

**参数：**
- `--db` 指定 core.db 路径
- `--config` 指定 config.yaml 路径
- `--output` 指定输出路径

### scan_files.py — 扫描当前文件

默认扫描 git 跟踪的文件（自动遵守 .gitignore）。逐行检查是否包含字典中的隐私内容。

**输出：** `data/private/scan_report.csv`

| 字段 | 说明 |
|------|------|
| file | 文件相对路径 |
| line | 行号 |
| match | 匹配的隐私内容 |
| source | 来源（my_identity.nickname / contacts.remark / custom） |
| context | 匹配行内容（截断200字符） |

**参数：**
- `--all` 扫描所有文件（含未跟踪）
- `--min-len` 最小匹配长度（默认2，避免单字符误报）

### scan_git_history.py — 扫描 git 历史

流式遍历 `git log --all -p`，检查每个提交的新增行是否包含隐私。
按 (file, match) 去重，只记录首次引入隐私的提交。

**输出：** `data/private/git_scan_report.csv`

| 字段 | 说明 |
|------|------|
| commit | 提交哈希（前12位） |
| file | 文件路径 |
| line | 行号 |
| match | 匹配内容 |
| source | 来源 |
| context | 匹配行内容 |

**参数：**
- `--max-commits` 最多扫描的提交数（0=全部）

### rewrite_git_history.py — 篡改 git 历史

⚠️ **高风险操作**：会重写所有提交哈希。

优先使用 `git filter-repo`（推荐，需 `pip install git-filter-repo`），回退到 `git filter-branch`。

**安全措施：**
- 默认 dry-run 模式
- 执行前自动备份 .git 到 `.git.backup-{timestamp}`
- 需 `--force` 才真正执行
- 替换隐私内容为 `[REDACTED]`

**执行后：**
```bash
git push --force --all
git push --force --tags
# 通知协作者重新 clone
# 确认无误后删除备份: rm -rf .git.backup-*
```

## 典型工作流

1. **首次使用**：运行 build → 编辑 custom → 运行 scan_files → 查看报告
2. **定期排查**：运行 build（刷新联系人）→ scan_files + scan_git_history
3. **历史清理**：scan_git_history 确认范围 → rewrite --dry-run → rewrite --force

## 注意事项

- `data/` 已在 .gitignore 中，字典库和报告不会被提交
- `scan_files.py` 默认只扫描 git 跟踪文件（会推送到远程的文件）
- `--min-len 2` 避免单字符误报，可根据需要调整
- git 历史篡改不可逆，务必先 dry-run 确认
