# Engine Stickers 贴纸模块

## 概述

贴纸模块提供贴纸词典管理、自动检测和人工标注功能。从消息中提取贴纸 md5，建立全局词典，支持自动检测和人工标注。

## 目录结构

```
engine/stickers/
├── __init__.py       # 导出公共接口
├── core.py           # 贴纸词典核心逻辑
├── label.py          # 贴纸标注工具（生成 HTML 标注页面 + 导入标注结果）
└── README.md
```

## 核心功能

| 功能 | 说明 |
|------|------|
| 贴纸扫描 | 从消息 raw_content XML 提取贴纸 md5 |
| 贴纸词典 | SQLite 表存储 md5/label/emotion/content_type/frequency |
| 情绪标注 | 按对对方态度分类：好感/敌意/中性/暧昧 |
| 镜像检测 | 她用了你用过的贴纸 = 正向信号（强/中/弱三级） |
| HTML 标注工具 | 生成浏览器标注页面 |

## 使用方式

```python
# 在代码中使用
from engine.stickers import scan_stickers, list_stickers, label_sticker

# 扫描贴纸
result = scan_stickers(conn)

# 列出贴纸
stickers = list_stickers(conn, limit=50, unlabeled_only=True)

# 标注贴纸
label_sticker(conn, md5="abc123", label="开心大笑", emotion="positive")
```

```bash
# 生成 HTML 标注页面
python -m engine.stickers.label generate [--limit 100]

# 从 JSON 导入标注结果
python -m engine.stickers.label import
```

## 数据模型

```python
@dataclass
class Sticker:
    md5: str                    # 唯一标识
    label: str = ""             # 描述标签
    emotion: str = ""           # positive / negative / neutral / ambiguous
    content_type: str = ""      # animal / text / reaction / meme / abstract
    width: int = 0              # 宽度
    height: int = 0             # 高度
    cdn_url: str = ""           # CDN URL
    product_id: str = ""        # 贴纸包 ID
    frequency: int = 0          # 使用频率
    first_seen: int = 0         # 首次出现时间
    auto_detected: str = ""     # 自动检测结果（JSON）
    user_verified: int = 0      # 是否已人工验证
```

## 数据库表

```sql
CREATE TABLE stickers (
    md5 TEXT PRIMARY KEY,
    label TEXT DEFAULT '',
    emotion TEXT DEFAULT '',
    content_type TEXT DEFAULT '',
    width INTEGER DEFAULT 0,
    height INTEGER DEFAULT 0,
    cdn_url TEXT DEFAULT '',
    product_id TEXT DEFAULT '',
    frequency INTEGER DEFAULT 0,
    first_seen INTEGER DEFAULT 0,
    auto_detected TEXT DEFAULT '',
    user_verified INTEGER DEFAULT 0
)
```