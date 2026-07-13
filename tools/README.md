# Tools 辅助工具

## 概述

`tools/` 存放用于**文档处理、数据清理、Wiki 维护等一次性或低频操作的辅助脚本**。这些脚本不参与核心业务流程，但在数据准备、Wiki 构建、质量检查等场景中发挥重要作用。

## 目录结构

```
tools/
├── convert/              # 文档格式转换
├── cleanup/              # 数据清理与整理（含匿名化）
├── wiki/                 # Wiki 维护
├── ops/                  # 运维脚本（定时任务、数据导出）
├── misc/                 # 其他杂项
└── README.md
```

## 文件分类

### convert/ - 文档格式转换

| 文件 | 职责 | 使用场景 |
|------|------|---------|
| `pdf2md.py` | PDF → Markdown | 将 PDF 文档转换为 Markdown |
| `epub2md.py` | EPUB → Markdown | 将 EPUB 电子书转换为 Markdown |
| `doc2md.py` | DOC/DOCX → Markdown | 将 Word 文档转换为 Markdown |
| `convert_book.py` | 书籍转换 | 转换单本电子书 |
| `batch_convert_books.py` | 批量书籍转换 | 批量转换多本电子书 |
| `convert_to_md.py` | 通用格式转换 | 转换多种格式为 Markdown |
| `split_pdf_to_md.py` | PDF 拆分转换 | 将 PDF 按章节拆分为多个 Markdown 文件 |
| `batch_ocr_chat.py` | 批量 OCR 聊天截图 | 批量识别聊天截图 |
| `move_to_ocr.py` | 移动到 OCR 目录 | 将文件移动到 OCR 处理目录 |
| `fix_mapping.py` | 修复映射 | 修复身份映射问题（一次性脚本） |

### cleanup/ - 数据清理与整理

| 文件 | 职责 | 使用场景 |
|------|------|---------|
| `anonymize_need.py` | 匿名化需求数据 | 去除敏感信息 |
| `anonymize_ocr.py` | 匿名化 OCR 数据 | 去除 OCR 结果中的敏感信息 |
| `correct_anonymize.py` | 修正匿名化 | 修复匿名化错误 |
| `rebuild_and_anonymize.py` | 重建并匿名化 | 重建数据并匿名化 |
| `restore_and_reanonymize.py` | 恢复并重匿名化 | 恢复数据并重做匿名化 |
| `dedup.py` | 去重 | 去除重复数据 |
| `dedup_books.py` | 书籍去重 | 去除重复书籍 |
| `fix_encoding.py` | 修复编码 | 修复文件编码问题 |
| `fix_filenames.py` | 修复文件名 | 修复非法文件名 |
| `rmdir_empty.py` | 删除空目录 | 清理空目录 |
| `clean_empty_dirs.py` | 清理空目录 | 批量清理空目录 |
| `broad_cleanup.py` | 全面清理 | 全面清理项目文件 |
| `clean_and_rebuild.py` | 清理重建 | 清理并重建索引 |
| `organize_docs.py` | 组织文档 | 整理文档结构 |
| `organize_tier.py` | 按层级组织 | 按层级整理文档 |
| `copy_selected.py` | 复制选中文件 | 复制选中的文件 |
| `update_selected.py` | 更新选中文件 | 更新选中的文件 |
| `verify_selected.py` | 验证选中文件 | 验证选中的文件 |
| `folder_structure_backup.py` | 备份目录结构 | 备份项目目录结构 |
| `reconstruct_structure.py` | 重建目录结构 | 重建项目目录结构 |
| `map_dataset_names.py` | 映射数据集名称 | 映射数据集名称 |
| `analyze_dsr.py` | DSR 分析 | 分析重复文件 |
| `cross_dir_dedup.py` | 跨目录去重 | 跨目录去重 |
| `dedup_dsr.py` | DSR 去重 | DSR 文件去重 |
| `dsr2json.py` | DSR → JSON | 转换 DSR 为 JSON |
| `filedb.py` | 文件数据库 | 文件索引数据库 |
| `find_dup_folders.py` | 查找重复文件夹 | 查找重复文件夹 |
| `report_win_rename.py` | Windows 重命名报告 | 生成 Windows 重命名报告 |

### wiki/ - Wiki 维护

| 文件 | 职责 | 使用场景 |
|------|------|---------|
| `generate_wiki_index.py` | 生成 Wiki 索引 | 生成 search-index.json |
| `wiki_lint.py` | Wiki 语法检查 | 检查 Wiki 页面语法错误 |
| `wiki_to_okf.py` | Wiki → OKF 格式 | 将旧格式转换为 OKF 格式 |
| `fix_okf_links.py` | 修复 OKF 链接 | 修复 OKF 格式中的链接 |
| `test_wiki_quality.py` | Wiki 质量测试 | 测试 Wiki 页面质量 |
| `check_quality.py` | 质量检查 | 检查 Wiki 质量 |

### ops/ - 运维脚本

| 文件 | 职责 | 使用场景 |
|------|------|---------|
| `export_chats.py` | 导出聊天记录 | 将聊天记录导出为文件 |
| `extract_audio.py` | 提取音频 | 从消息中提取音频文件 |
| `extract_scheduler.py` | 提取调度器数据 | 提取调度器相关数据 |
| `picker_folder.py` | 文件夹选择器 | 选择文件夹的辅助工具 |
| `daily_sync.ps1` | 每日同步 | 每日数据同步任务 |
| `register_tasks.ps1` | 注册任务 | 注册定时任务 |
| `start_wcd.ps1` | 启动 WCD | 启动 WeChatDataAnalysis |

### misc/ - 其他杂项

| 文件 | 职责 | 使用场景 |
|------|------|---------|
| `list_contacts.py` | 列出联系人 | 列出所有联系人 |
| `list_second_level.py` | 列出二级目录 | 列出二级目录内容 |
| `batch_zip_extract.py` | 批量解压 ZIP | 批量解压 ZIP 文件 |
| `punctuate_check.py` | 标点检查 | 检查标点使用 |
| `punctuate_docs.py` | 文档标点处理 | 处理文档标点 |
| `test_slope.py` | composite_slope 指标验证 | 验证 composite_slope 计算正确性（依赖 engine.backtest.load_cases） |
| `test_slope_window.py` | composite_slope 窗口区分力验证 | 验证不同窗口长度下 slope 的区分力 |

## 使用建议

### Wiki 维护流程

1. 添加新文档 → 使用 `convert/pdf2md.py` 或 `convert/convert_book.py` 转换
2. 生成索引 → `python tools/wiki/generate_wiki_index.py`
3. 质量检查 → `python tools/wiki/check_quality.py`
4. 语法检查 → `python tools/wiki/wiki_lint.py`

### 数据清理流程

1. 匿名化 → `python tools/cleanup/anonymize_need.py`
2. 去重 → `python tools/cleanup/dedup.py`
3. 修复编码 → `python tools/cleanup/fix_encoding.py`
4. 清理空目录 → `python tools/cleanup/clean_empty_dirs.py`

### 贴纸标注流程

1. 启动标注页面 → `python -m engine.stickers.label generate`
2. 在浏览器中打开生成的 HTML 文件
3. 标注贴纸的情感和类型

## 注意事项

- 脚本大多是一次性使用，不纳入核心测试
- 部分脚本需要外部依赖（如 rapidocr-onnxruntime、Pillow）
- 操作前建议备份数据，特别是清理和转换类脚本
- 跨项目同步脚本（`copy_to_SalesCRM.sh`）已移至 `exchange/tools/`

## 参考文档

- `readme/tools.md` - 工具详细文档
- `plan/目录重组方案.md` - 目录重组方案