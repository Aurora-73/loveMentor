# Tools Cleanup 数据清理与整理

## 概述

数据清理与整理工具集，包括匿名化、去重、编码修复、文件组织等功能。

## 文件列表

### 匿名化工具

| 文件 | 职责 |
|------|------|
| `anonymize_need.py` | 匿名化需求数据 |
| `anonymize_ocr.py` | 匿名化 OCR 数据 |
| `correct_anonymize.py` | 修正匿名化错误 |
| `rebuild_and_anonymize.py` | 重建数据并匿名化 |
| `restore_and_reanonymize.py` | 恢复数据并重做匿名化 |

### 去重工具

| 文件 | 职责 |
|------|------|
| `dedup.py` | 去除重复数据 |
| `dedup_books.py` | 去除重复书籍 |
| `analyze_dsr.py` | DSR 分析 |
| `cross_dir_dedup.py` | 跨目录去重 |
| `dedup_dsr.py` | DSR 文件去重 |
| `dsr2json.py` | DSR → JSON |
| `filedb.py` | 文件索引数据库 |
| `find_dup_folders.py` | 查找重复文件夹 |
| `report_win_rename.py` | 生成 Windows 重命名报告 |

### 文件修复工具

| 文件 | 职责 |
|------|------|
| `fix_encoding.py` | 修复文件编码问题 |
| `fix_filenames.py` | 修复非法文件名 |

### 目录清理工具

| 文件 | 职责 |
|------|------|
| `rmdir_empty.py` | 删除空目录 |
| `clean_empty_dirs.py` | 批量清理空目录 |
| `broad_cleanup.py` | 全面清理项目文件 |
| `clean_and_rebuild.py` | 清理并重建索引 |

### 文件组织工具

| 文件 | 职责 |
|------|------|
| `organize_docs.py` | 整理文档结构 |
| `organize_tier.py` | 按层级整理文档 |
| `copy_selected.py` | 复制选中的文件 |
| `update_selected.py` | 更新选中的文件 |
| `verify_selected.py` | 验证选中的文件 |
| `folder_structure_backup.py` | 备份项目目录结构 |
| `reconstruct_structure.py` | 重建项目目录结构 |
| `map_dataset_names.py` | 映射数据集名称 |

## 使用示例

```bash
# 匿名化 OCR 数据
python tools/cleanup/anonymize_ocr.py forward

# 去重
python tools/cleanup/dedup.py

# 修复编码
python tools/cleanup/fix_encoding.py

# 清理空目录
python tools/cleanup/clean_empty_dirs.py
```