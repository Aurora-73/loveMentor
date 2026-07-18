# Importers 数据同步管道

## 概述

`engine/importers/` 负责**从外部数据源同步微信数据到本地 SQLite 数据库**。支持 WCD（WeChatDataAnalysis）和 WeFlow 两个后端，通过 `config.yaml` 的 `weflow.backend` 配置自动切换。

## 架构定位

```
WCD API (http://127.0.0.1:10392) 或 WeFlow API (http://127.0.0.1:5031)
    │
    └── engine/importers/（同步管道）
            │
            ├── wcd_client.py / weflow_client.py → HTTP API 客户端
            ├── sync.py → 同步主入口
            ├── sync_contacts.py → 联系人同步
            ├── sync_conversations.py → 会话同步
            ├── sync_messages.py → 消息增量同步
            ├── sync_moments.py → 朋友圈同步
            ├── checkpoint.py → 同步水位管理
            ├── db_init.py → SQLite schema 初始化
            └── ocr_engine.py / screenshot_parser.py / screenshot_import.py → 截图 OCR 导入
                    │
                    ▼
            data/raw/core.db（SQLite）
```

## 模块清单

| 文件 | 职责 | 核心功能 |
|------|------|---------|
| `sync.py` | 同步主入口 | 全量/增量同步调度 |
| `sync_contacts.py` | 联系人同步 | 拉取联系人信息（昵称/备注/头像/标签） |
| `sync_conversations.py` | 会话同步 | 拉取会话列表（私聊/群聊） |
| `sync_messages.py` | 消息同步 | 增量拉取消息（基于 watermark） |
| `sync_moments.py` | 朋友圈同步 | 拉取朋友圈动态和互动 |
| `wcd_client.py` | WCD HTTP API 客户端 | 调用 WCD API |
| `weflow_client.py` | WeFlow HTTP API 客户端 | 调用 WeFlow API，与 WCD 接口兼容 |
| `checkpoint.py` | 同步水位管理 | 基于 watermark 的增量同步，不重复拉取 |
| `db_init.py` | SQLite schema 初始化 | 创建数据库表结构 |
| `ocr_engine.py` | OCR 引擎 | 使用 RapidOCR 识别截图文字 |
| `screenshot_parser.py` | 截图解析 | 解析截图中的聊天记录 |
| `screenshot_import.py` | 截图导入管道 | 将截图 OCR 结果导入数据库 |

## 同步流程

### 全量同步

```
sync(mode='full')
    ├── sync_contacts() → contacts 表
    ├── sync_conversations() → conversations 表
    ├── sync_messages(session_id=None) → messages 表（所有会话）
    └── sync_moments() → moments + moment_interactions 表
```

### 增量同步（默认）

```
sync(mode='incremental')
    ├── sync_contacts(meta_only=True) → 更新联系人列表
    ├── sync_messages(session_id=None) → 基于 watermark 增量拉取
    └── sync_moments() → 增量拉取朋友圈
```

### 单联系人同步

```
sync_person(name)
    ├── 通过身份目录找到对应的 wxid
    ├── sync_messages(session_id=该联系人会话)
    └── sync_moments(person_id=该联系人)
```

## 数据库表

| 表名 | 用途 |
|------|------|
| `contacts` | 联系人基础信息（wxid, nickname, remark, avatar） |
| `conversations` | 会话元数据（session_id, type, name） |
| `messages` | 聊天消息（msg_id, session_id, sender_id, content, timestamp） |
| `attachments` | 附件记录 |
| `moments` | 朋友圈动态 |
| `moment_interactions` | 朋友圈互动（点赞/评论） |
| `sync_state` | 同步水位（每个会话独立的 watermark） |
| `sync_log` | 同步日志 |
| `contact_excludes` | 排除列表 |
| `contact_merges` | 合并记录 |

## 核心设计原则

### checkpoint 机制

基于 watermark 的增量同步，每个会话维护独立的同步水位：

1. 首次同步：拉取全部消息，记录最高 watermark
2. 后续同步：只拉取 watermark 大于上次记录的消息
3. 不重复拉取：确保每条消息只入库一次

### 后端自动切换

通过 `config.yaml` 的 `weflow.backend` 配置：

- `"wcd"`：使用 WCD 后端（推荐）
- `"weflow"`：使用 WeFlow 后端

两个客户端接口兼容，上层代码无需感知差异。

### 仅同步私聊

`sync()` 默认只处理 `type='private'` 的会话（个人聊天），群聊和公众号消息不会被同步。`sync_person()` 不受此限制。

### 自动解密

`sync()` 和 `sync_person()` 使用 WCD 后端时，自动调用 `/api/decrypt` 刷新数据库快照（用缓存密钥，不重启微信）。30 分钟内重复同步自动跳过解密。

### 同步原则

- 默认增量同步：`mode='incremental'`
- 全量同步仅在数据修复时使用：`mode='full'`
- 少用 `fetch_keys`：会重启微信并要求扫码登录

## 截图 OCR 导入

支持从小红书/探探等平台截图导入聊天记录：

```
data/input/（用户手动放置截图）
    └── screenshot_import.py
            ├── ocr_engine.py → 识别文字
            ├── screenshot_parser.py → 解析消息结构
            └── 写入 messages 表
```

## 外部依赖

| 依赖 | 用途 | 是否必须 |
|------|------|---------|
| rapidocr-onnxruntime | 截图 OCR | 仅 import-chat |
| Pillow | 图片尺寸读取 | 仅 import-chat |

同步管道使用 Python 标准库（urllib、json）。

## 参考文档

- 同步管道详细文档：`readme/importers.md`
