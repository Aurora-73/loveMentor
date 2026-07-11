# Tools Convert 文档格式转换

## 概述

文档格式转换工具集，用于将各种格式的文档转换为 Markdown 格式，便于后续处理和 Wiki 入库。

## 文件列表

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

## 使用示例

```bash
# 转换单本 PDF
python tools/convert/pdf2md.py input.pdf output.md

# 批量转换书籍
python tools/convert/batch_convert_books.py "docs/百度网盘/[REDACTED]/泡妞231本"

# 移动文件到 OCR 目录
python tools/convert/move_to_ocr.py --workers 4
```