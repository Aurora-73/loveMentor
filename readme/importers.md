# 数据同步管道

## 概述

`engine/importers/` 负责从 WeFlow 或 WeChatDataAnalysis (WCD) 同步微信数据，以及从截图 OCR 导入非微信平台的聊天记录。

## 核心文件

| 文件 | 行数 | 功能 |
|------|------|------|
| `__init__.py` | 17 | 包导出（统一对外接口：WeFlowClient/WCDClient/run_sync/show_status 等） |
| `weflow_client.py` | 169 | WeFlow HTTP API 客户端（纯 urllib，无第三方依赖） |
| `wcd_client.py` | ~720 | WCD HTTP API 客户端（兼容 WeFlowClient 接口）+ `is_wechat_running()` + mtime 智能解密节流 |
| `sync.py` | ~345 | 同步编排器：health check → 智能数据源选择 → contacts → conversations → 私聊消息 → moments，含 `show_status()` |
| `sync_contacts.py` | 52 | 联系人同步（list_contacts → UPSERT contacts 表） |
| `sync_conversations.py` | 65 | 会话同步（list_sessions → UPSERT conversations 表） |
| `sync_messages.py` | 220 | 消息同步（get_messages → UPSERT messages 表） |
| `sync_moments.py` | 144 | 朋友圈同步（get_moments_timeline → UPSERT moments 表） |
| `checkpoint.py` | 171 | 同步水位记录（增量同步的断点续传） |
| `db_init.py` | 361 | 数据库初始化（建表、索引、迁移） |
| `voice_transcriber.py` | ~250 | 语音消息转写（SILK v3 → PCM → faster-whisper） |
| `image_transcriber.py` | ~300 | 图片消息转写（BLIP 描述 + PaddleOCR 文字） |
| `async_transcriber.py` | 525 | 异步转写管理器（单例 + daemon worker + 内存队列） |
| `screenshot_import.py` | 583 | 截图 OCR 导入主流程（含 `prepare_import`/`confirm_and_import`/`import_from_file`） |
| `screenshot_parser.py` | 408 | 截图消息解析（识别发送者、时间、内容） |
| `ocr_engine.py` | 214 | RapidOCR 封装（ONNX Runtime，带 MD5 缓存） |

> 按人同步的 `sync_person()` 不在本包内，位于 `engine/agent/sync_agent.py`，作为 Agent 层入口调用本包的同步原语。
>
> **转写与同步关系**：`sync_person()` 同步完成后自动调用 `async_transcriber.trigger_transcription()`，对每个 account 的 wxid 启动语音/图片转写（默认 `transcribe_mode="async"` 异步执行，详见下方"语音/图片转写机制"章节）。

## 数据后端选择

通过 `config.yaml` 的 `weflow.backend` 字段切换：

| 值 | 客户端 | 默认端口 | 说明 |
|----|--------|---------|------|
| `"wcd"` | WCDClient | 10392 | WeChatDataAnalysis（推荐） |
| `"weflow"` | WeFlowClient | 5031 | WeFlow（旧方案） |

```python
# sync.py 中的自动选择逻辑
if config.weflow.backend == "wcd":
    client = WCDClient(base_url, token, timeout, decrypted_db_dir)
else:
    client = WeFlowClient(base_url, token, timeout)
```

两个客户端接口完全兼容，上层同步代码零改动。

## WCD 启动方式

使用 WeChatDataAnalysis (WCD) 作为后端时，需要先启动 API 服务：

```bash
cd _reference/WeChatDataAnalysis
uv run main.py
```

默认在 `127.0.0.1:10392` 启动，可以通过以下方式验证：

```bash
curl http://127.0.0.1:10392/api/health
# {"status":"healthy","service":"微信解密工具"}
```

**常见问题**：

| 问题 | 处理 |
|------|------|
| `uv` 命令不存在 | 先安装 uv：`pip install uv` 或 `winget install uv` |
| 端口被占用 | 修改 `output/runtime_settings.json` 中的端口配置 |
| 启动后 API 返回 404 | 确认 `main.py` 在工作目录 `_reference/WeChatDataAnalysis/` 下执行 |
| 密钥不存在 | 首次使用需获取密钥，见下方"密钥管理" |

**注意**：WCD 会在启动时自动加载 `account_keys.json` 中的缓存密钥。如果密钥文件不存在，首次需要调用 `/api/get_keys`（会重启微信并要求扫码），之后密钥会持久化。

## WCDClient 字段映射

WCD API 返回格式与 WeFlow 不同，WCDClient 内部做映射：

| WCD 字段 | WeFlow 字段 | 说明 |
|----------|------------|------|
| `username` | `id` | 联系人 ID |
| `type` | `localType` | 消息类型 |
| `isSent` | `isSend` | 是否自己发送 |
| `quoteServerId` | `replyToMessageId` | 引用消息 ID |
| `emojiMd5` + `emojiUrl` | (构造 XML) | 贴纸 → `<msg><emoji md5="..." cdnurl="..."/></msg>` |

**关键**：`list_contacts()` 返回的 dict 必须同时包含 `id` 和 `username` 字段（值相同）。`sync_contacts` 用 `c.get("username", "")` 作为联系人 ID 写入数据库。`list_sessions()` 只需 `username` 字段。

标签提取：WCD API 不返回 labels，WCDClient 直接读取解密后的 `contact.db`，通过 protobuf 解析 `extra_buffer` field 30 获取标签 ID，再查 `contact_label` 表得到标签名。

## 同步流程

```
run_sync(config, mode='incremental')  # 默认增量，仅私聊
    │
    ├─ 1. health check（API 是否在线）
    ├─ 2. 智能数据源选择（WCD 后端）：
    │      is_wechat_running() → 运行中: source=decrypted + mtime 节流解密
    │                          → 未运行: source=realtime（跳过全量解密）
    ├─ 3. sync_contacts（联系人 UPSERT）
    ├─ 4. sync_conversations（会话 UPSERT，自动判断 private/group/official）
    ├─ 5. 遍历所有私聊 session（WHERE type='private'）：
    │      sync_one_session(client, conn, session_id, since)
    │      ├─ 检查 checkpoint 水位（增量模式从上次继续）
    │      ├─ get_messages(talker, limit=500, offset=...)
    │      ├─ upsert_message()（ON CONFLICT 更新）
    │      ├─ 遇到空结果自动缩小 limit 重试（500→200→100，最多 3 次）
    │      └─ 更新 checkpoint
    └─ 6. sync_moments（朋友圈 timeline → moments + moment_interactions 表）
```

**数据库快照刷新（智能数据源切换）**：WCD 后端在同步前根据微信进程状态动态选择数据源（`sync.py` 调用 `is_wechat_running()` 判断）：

| 微信状态 | 数据源 | 解密行为 | 开销 |
|---------|--------|---------|------|
| **运行中** | `source=decrypted` | 调用 `/api/decrypt` 刷新解密快照（缓存密钥，不重启微信） | 几分钟（首次）/ 跳过（无新数据） |
| **未运行** | `source=realtime`（默认） | 跳过全量解密，native 直读加密库 | 毫秒级 |

**`is_wechat_running()`**（`wcd_client.py`）：用 `psutil` 扫描进程名 `Weixin.exe` / `WeChat.exe`。psutil 未安装时保守返回 True（走 decrypted 路径，兼容旧逻辑）。

**mtime 智能解密节流**（替代原固定 30 分钟节流）：`decrypt_databases()` 现采用两层节流：
1. **5 分钟防抖**（`_DECRYPT_MIN_INTERVAL=300`）：刚解密过则跳过，避免微信持续运行时频繁解密
2. **db_storage mtime 检测**（`_check_db_storage_changed()`）：扫描 `db_storage` 下所有 `.db` 文件的 mtime，与上次解密时间戳对比：
   - mtime > 上次解密时间 → 有新数据，触发解密
   - mtime ≤ 上次解密时间 → 无新数据，跳过解密

`force=True` 可跳过所有节流检查强制解密。标记文件 `output/.last_decrypt` 记录上次解密时间戳。WeFlow 后端跳过此步骤。

**`source` 参数（WCD 后端关键）**：所有 WCD 读取调用（`list_contacts` / `list_sessions` / `get_messages`）都支持 `source` 参数：
- `None`/`auto`：默认 realtime，微信未运行时可用（毫秒级）
- `realtime`：直读 WCDB，微信运行时会超时（`open_account timed out after 5s`，WCDB 文件锁被占用）
- `decrypted`：读解密后的 DB 副本，不受 WeChat 锁影响（微信运行时推荐）

项目内统一约定：`backend=wcd` 时由 `is_wechat_running()` 动态决定 source——微信运行时 `wcd_source="decrypted"`，未运行时 `wcd_source=None`（realtime）。涉及文件：`sync.py` / `sync_agent.py` / `screenshot_import.py` / `live_monitor.py` / `wechat_e2e_run.py` / `avatar_fetcher.py`（`_smart_wcd_source()` 辅助函数）。

**`/api/decrypt_lite` 端点（头像快速刷新）**：全量 `decrypt_databases(force=True)` 会解密所有数据库（含 GB 级 `message_*.db`），耗时几分钟。`/api/decrypt_lite` 只解密 `contact.db` + `head_image.db`（几 MB），**1-3 秒完成**，性能提升 30-100 倍。

- 端点位置：`_reference/WeChatDataAnalysis/src/wechat_decrypt_tool/routers/decrypt.py`
- 客户端方法：`WCDClient.decrypt_databases_lite()`
- 调用方：`avatar_fetcher._query_avatar_via_wcd_api`（头像匹配失败时触发刷新）
- 智能跳过：微信未运行时跳过 lite 解密，直接 realtime 直读
- 不写节流标记：lite 解密不影响全量解密的节流逻辑
- 与 WeFlow CDP `refreshContactAvatar` 速度相当（几秒级）

**仅私聊**：消息同步默认只处理 `type='private'` 的会话（`wxid_` 开头或不含 `@` 的个人聊天）。群聊（`@chatroom`）和公众号（`gh_`）不会同步消息。

### 增量 vs 全量

- **incremental**（**默认**）：从 checkpoint 水位继续拉取，只拉新消息。日常使用此模式。
- **full**：忽略 checkpoint，从 offset=0 重新拉取全部。仅在数据修复时使用。

**原则：默认增量，尽量少用全量。** 全量同步耗时长（3000+ 秒），且数据通常不需要全量刷新。

### meta_only 模式

`run_sync(config, meta_only=True)` 只同步联系人和会话列表，不同步消息。用于快速刷新联系人搜索索引（约 1 秒）。

### 按人同步

`sync_person(name, mode='incremental')` 只同步指定联系人的消息。适合关注特定对象的增量更新。注意：按人同步不受私聊限制影响，可以同步任意指定会话。

> **位置**：`sync_person()` 定义在 `engine/agent/sync_agent.py`（Agent 层），不在 `engine/importers/`（同步原语层）。`engine/tools.py` 从 `sync_agent` 导入并对外暴露。

## 密钥管理

### WCD 密钥缓存机制

密钥存储在 `output/account_keys.json`（WCD 解密输出目录的父目录）。

1. **首次获取**：通过 `wx_key` 工具获取数据库密钥（需要微信扫码登录），或调用 WCD API `/api/get_keys`（会重启微信）
2. **持久化**：密钥保存到 `account_keys.json`，字段包括 `db_key`、`db_storage_path`、`image_xor_key`、`image_aes_key`
3. **重新解密**：当 WCD 联系人列表过期（新增好友不显示）时，用缓存密钥调用 `/api/decrypt` 重新解密

### 联系人列表过期的处理

WCD 的联系人来自解密后的数据库。新增微信好友后，WCD API 不会自动更新，需要手动重新解密：

```python
import json, urllib.request

# 读取缓存密钥
with open("output/account_keys.json") as f:
    keys = json.load(f)
account = list(keys.values())[0]

# 调用解密 API（不重启微信，不重新获取密钥）
data = json.dumps({
    "key": account["db_key"],
    "db_storage_path": account["db_key_source_db_storage_path"]
}).encode()
req = urllib.request.Request(
    "http://127.0.0.1:10392/api/decrypt",
    data=data, headers={"Content-Type": "application/json"}, method="POST"
)
with urllib.request.urlopen(req, timeout=120) as resp:
    result = json.loads(resp.read())
# result: {"status": "completed", "success_count": 20, ...}
```

**判断是否需要重新解密**：WCD API `/api/chat/contacts` 返回的 `total` 少于微信实际好友数 → 需要重新解密。

**不要用 `/api/get_keys`**：该接口会重启微信并要求扫码，有封号风险。`/api/decrypt` 只用缓存密钥重新解密数据库文件，不影响微信运行。

### 配置示例

```yaml
weflow:
  backend: "wcd"
  base_url: "http://127.0.0.1:10392"
  decrypted_db_dir: "E:/Code/loveMentor/_reference/WeChatDataAnalysis/output/databases"
```

`decrypted_db_dir` 指向 WCD 的解密输出目录，WCDClient 从中读取 `contact.db` 提取标签。

## 截图 OCR 导入

用于导入非微信平台（小红书、探探等）的聊天截图。

### 函数清单

| 函数 | 签名 | 作用 |
|------|------|------|
| `ensure_wechat_data` | `(conn, wxid) → (contact_info \| None, error \| None)` | 确保该联系人在本地数据库中且已有微信消息，返回联系人信息 |
| `prepare_import` | `(conn, wxid, screenshot_dir, platform="wechat", contact_info=None) → ImportPreview` | 执行 OCR 与解析，返回预览结果（不写入数据库） |
| `export_preview_json` | `(preview, output_path) → Path` | 将 ImportPreview 导出为 JSON 文件供用户编辑 |
| `confirm_and_import` | `(conn, preview) → ImportResult` | 用户确认预览后直接导入（程序内调用，无需 JSON 中转） |
| `import_from_file` | `(conn, preview_file) → ImportResult` | 从用户修改后的 JSON 预览文件导入消息 |
| `load_preview_json` | `(file_path) → (list[ParsedMessage], base_ts, wxid, platform)` | 解析用户编辑后的 JSON 预览文件 |

### 导入流程

```
Step 1: ensure_wechat_data(conn, wxid)
    │  确保该联系人在本地数据库中 + 已有微信消息
    │  内部自动：查本地 → 没找到 → sync_contacts + sync_conversations → 再查
    │  → 找到后检查是否有微信消息，没有则 sync_one_session
    │  → 返回 (contact_info, error)
    │
    │  ⚠️ 联系人找不到？
    │  → 检查 WCD 联系人数量是否与微信一致
    │  → 不一致：用缓存密钥调 /api/decrypt 重新解密（见"密钥管理"）
    │  → 仍然找不到：确认微信号是否正确
    │
Step 2: 截图放到 data/input/<名字>/ 目录下
    │
Step 3: prepare_import(conn, wxid, screenshot_dir, platform, contact_info)
    │  → OCR → 解析 → ImportPreview
    │  → export_preview_json(preview, output_path)
    │
Step 4: 用户编辑 JSON 预览文件
    │  → 修正 OCR 错字、删除 UI 元素、修正 sender
    │
Step 5: import_from_file(conn, preview_path)
    │  → 写入 messages 表（platform 字段标记来源）
    │
    │  或者：confirm_and_import(conn, preview)
    │  → 不经过 JSON 中转，直接用 ImportPreview 对象写入
```

**关键契约**：
1. 文件名排序 = 聊天时间顺序
2. 外部导入消息放在微信第一条消息之前 2 小时
3. 先导出 JSON 预览，用户编辑确认后才写入
4. 通过 wxid 唯一标识联系人
5. `prepare_import` 的 `contact_info` 参数由 `ensure_wechat_data` 返回，用于提取 display_name

**长截图处理**：OCR 引擎自动分片（高度 > 30000px 时按 30000px 切片），无需手动处理。

## 数据库表

| 表 | 主键 | 说明 |
|---|------|------|
| `contacts` | id (TEXT) | 联系人（nickname/remark/alias/display_name/labels） |
| `conversations` | id (TEXT) | 会话（type: private/group/official） |
| `messages` | id (TEXT) | 消息（conversation_id/sender_id/content/timestamp/type/voice_text/image_text）。`voice_text`/`image_text` 由转写模块异步写入，`upsert_message` 不覆盖这两个字段 |
| `attachments` | id (TEXT) | 附件（message_id/media_path） |
| `moments` | id (TEXT) | 朋友圈动态 |
| `moment_interactions` | id (TEXT) | 朋友圈互动（likes/comments） |
| `sync_state` | - | 同步水位记录 |
| `sync_log` | auto | 同步日志 |
| `contact_excludes` | wxid (TEXT) | 手动排除记录 |
| `contact_merges` | canonical_wxid (TEXT) | 账号合并记录 |
| `people` | id (TEXT) | 身份目录-自然人 |
| `contact_accounts` | id (TEXT) | 身份目录-微信号 |
| `contact_aliases` | person_id+type+value | 身份目录-别名 |
| `contact_identity_log` | id (TEXT) | 身份操作日志 |
| `schema_version` | version (INTEGER) | 数据库迁移版本记录 |

## 注意事项

1. **API 必须在线**：同步前会 health check，失败则抛 `SyncError`。
2. **仅同步私聊**：`run_sync()` 只处理 `type='private'` 的会话（个人聊天）。群聊和公众号的消息不会被同步。如需同步非私聊会话，直接调用 `sync_one_session()`。
3. **消息 ID 兜底**：如果 API 没返回 `serverId`，用内容 MD5 生成 ID。
4. **空结果重试**：WeFlow API 不稳定，相同参数有时返回 0 条消息有时返回数据。`sync_messages._fetch_messages_with_retry` 会自动缩小 limit（500→200→100）重试最多 3 次，只要某次返回非空即停止。
5. **会话类型判断**：`sync_conversations.py` 不信任 API 的 type 字段（全为 0），改用 session_id 模式判断：
   - `@chatroom` 在 session_id 中 → `group`
   - `gh_` 开头 → `official`
   - `wxid_` 开头 **或** session_id 不含 `@` → `private`
   - 其他 → 回退到 API type 字段映射
6. **OCR 缓存**：OCR 结果按图片 MD5 缓存在 `data/cache/ocr/`，避免重复识别。缓存超过 500MB 时自动清理最旧文件。
7. **WCD 联系人过期**：WCD 的联系人列表来自解密后的数据库快照，新增好友不会自动出现。需要调用 `/api/decrypt` 用缓存密钥重新解密。不要调用 `/api/get_keys`（会重启微信）。
8. **WCDClient 字段兼容**：`list_contacts()` 返回的 dict 必须包含 `username` 字段（`sync_contacts` 用它作为联系人 ID）。`list_sessions()` 同理。

## 语音/图片转写机制

微信消息中的语音（type=34）和图片（type=3）原始内容只是占位符（如 `[语音 4.9秒]`、`[图片]`），无法被 Agent 直接理解。本模块负责将这两种非文本消息转写为文字，存入 `messages.voice_text` / `messages.image_text` 字段。

### 整体架构

```
sync_person 完成
    │
    ▼
trigger_transcription(db_path, conv_id, config, mode)
    │
    ├── mode="async"（默认）→ AsyncTranscriber 入队 → daemon worker 后台串行处理
    ├── mode="sync"          → _sync_transcribe 同步执行（阻塞）
    └── mode="off"           → 不转写
    │
    ▼
查询 messages 表 type=34 voice_text IS NULL / type=3 image_text IS NULL
    │
    ├── 语音 → VoiceTranscriber（SILK v3 → PCM → faster-whisper）
    └── 图片 → ImageTranscriber（WCD 下载 → BLIP 描述 + PaddleOCR 文字）
    │
    ▼
UPDATE messages SET voice_text=? / image_text=?
```

### 三个文件职责

| 文件 | 行数 | 职责 |
|------|------|------|
| [voice_transcriber.py](../engine/importers/voice_transcriber.py) | ~390 | 语音转写：SILK v3 解码 + faster-whisper 识别 |
| [image_transcriber.py](../engine/importers/image_transcriber.py) | ~714 | 图片转写：BLIP 描述 + PaddleOCR 文字 + 智能组合 |
| [async_transcriber.py](../engine/importers/async_transcriber.py) | 525 | 异步管理：单例 + daemon worker + 内存队列 |

### 语音转写（VoiceTranscriber）

**数据流**：
```
media_0.db.VoiceInfo.voice_data (SILK v3 BLOB)
    → pysilk.decode()  → PCM 16-bit 24kHz
    → wave 模块封装为 WAV bytes
    → faster-whisper.transcribe() → 中文文字
    → 加 [语音转文字] 前缀
    → 写入 messages.voice_text
```

**关联键**：`messages.id (server_id) == VoiceInfo.svr_id`

**模型**：faster-whisper `small` 模型，CPU + int8 量化，首次加载约 30s，识别速度约 2-3 倍实时时长

**配置项**（`config.yaml` 无显式配置，使用代码默认值）：
| 配置 | 默认值 | 说明 |
|------|--------|------|
| `model_size` | `"small"` | Whisper 模型大小（tiny/base/small/medium/large-v3） |
| `device` | `"cpu"` | cpu/cuda |
| `compute_type` | `"int8"` | int8（CPU 推荐）/float16（GPU） |
| `sample_rate` | `24000` | 微信语音默认采样率 |
| `language` | `"zh"` | 中文识别 |
| `initial_prompt` | `"请用简体中文输出："` | 引导模型输出简体中文 |

### 图片转写（ImageTranscriber）

**数据流**：
```
messages.raw_content (XML 含 md5)
    → WCD API /api/chat/media/image?md5=xxx&username=talker → 图片二进制
    → 并行/串行调用 BLIP（实物描述）+ PaddleOCR（文字提取）
    → 智能组合结果
    → 加 [图片描述] 前缀
    → 写入 messages.image_text
```

**关联键**：`messages.id (server_id)` + `messages.conversation_id (talker)`

**智能组合策略**（`_combine_results` 方法）：

| 情况 | BLIP 描述 | OCR 文字 | 组合结果 |
|------|----------|---------|---------|
| 1 | ✅ 有效 | ❌ 无 | 用 BLIP 描述（照片类） |
| 2 | ✅ 泛化 | ✅ 有 | 用 OCR 文字（截图类，BLIP 描述含"computer screen"等关键词） |
| 3 | ✅ 有效 | ✅ 有 | 组合：`BLIP描述（图中文字：OCR文字）`（meme/混合） |
| 4 | ❌ 无 | ✅ 有 | 用 `[截图] OCR文字` |
| 5 | ❌ 无 | ❌ 无 | 失败，标记为空字符串 |

**模型选择**：
- **BLIP**：`Salesforce/blip-image-captioning-base`（223M 参数，约 1GB）
  - 输出英文，通过 `Helsinki-NLP/opus-mt-en-zh` 翻译为中文
  - 用 `.bin` 格式权重（`use_safetensors=False`），避开 Python 3.13 + Windows 上的 safetensors native bug
- **PaddleOCR**：`PP-OCRv5_mobile`（默认，快 2.5 倍）或 `PP-OCRv5_server`（精度略高）
  - 必须传 `enable_mkldnn=False`，否则 OneDNN 触发 NotImplementedError

**模型加载顺序**：PaddleOCR 先于 BLIP，让 paddle native 库先初始化，避免与 torch native 库冲突触发 0xC0000005 访问冲突。

**配置项**（`config.yaml` 的 `weflow` 段）：
```yaml
weflow:
  image_model: "Salesforce/blip-image-captioning-base"  # BLIP 模型
  image_ocr: true                                        # 是否启用 OCR
  image_ocr_model: "mobile"                              # OCR 模型：mobile/server
```

### 异步转写管理器（AsyncTranscriber）

**单例模式**：`AsyncTranscriber.get_instance()` 全局唯一，跨多次 sync_person 调用复用 transcriber 实例（模型加载耗时，避免重复初始化）

**队列约束**：
| 约束 | 值 | 说明 |
|------|----|----|
| `MAX_QUEUE_SIZE` | 50 | 队列最多 50 个任务，超过则丢弃（避免无限增长） |
| `MAX_MESSAGES_PER_TASK` | 100 | 单次任务最多处理 100 条消息 |

**Worker 线程**：
- `daemon=True`，进程退出时自动结束
- 单 worker 串行处理（避免 CPU 过载）
- 失败任务不重试（幂等设计，下次 sync_person 会重新触发 NULL 消息）

**状态查询**：`AsyncTranscriber.get_instance().get_status()` 返回：
```python
{
    "queue_size": 3,                  # 当前队列长度
    "worker_alive": True,             # worker 线程是否存活
    "voice_transcriber_ready": True,  # 语音 transcriber 是否初始化成功
    "image_transcriber_ready": True,  # 图片 transcriber 是否初始化成功
    "voice_init_failed": False,       # 语音 transcriber 是否初始化失败（永久标记）
    "image_init_failed": False,       # 图片 transcriber 是否初始化失败（永久标记）
    "total_processed": 150,           # 累计处理消息数
    "total_success": 120,             # 累计成功数
    "total_failed": 30,               # 累计失败数
}
```

### 关键约束（用户明确要求）

1. **不阻塞同步主流程**：`async` 模式下 `trigger_transcription()` 入队后立即返回，sync_person 几秒完成；`sync` 模式才会阻塞等待转写完成
2. **转写结果不被下次同步覆盖**：`sync_messages.upsert_message()` 的 `ON CONFLICT(id) DO UPDATE SET` 只更新 `content/raw_content/sender_name/media_path/raw_json/synced_at`，**不包含** `voice_text/image_text` 字段，转写结果持久保留
3. **async/sync/off 开关**：通过 `person_sync(name, transcribe_mode=...)` 参数控制，默认 `async`

### 失败处理

- **失败标记**：识别失败的消息 `voice_text` / `image_text` 标记为空字符串（`FAILED_MARKER = ""`），避免反复重试
- **重置失败消息**：如需重试，手动执行 SQL：
  ```sql
  UPDATE messages SET voice_text=NULL WHERE type=34 AND voice_text='';
  UPDATE messages SET image_text=NULL WHERE type=3 AND image_text='';
  ```
- **永久失败场景**：
  - 语音：`media_0.db` 中无对应 `svr_id` 的 `voice_data`
  - 图片：`raw_content` 无 md5 / WCD API 404（图片在服务器找不到）

### MCP 工具集成

`person_sync(name, mode="incremental", transcribe_mode="async")` 工具新增 `transcribe_mode` 参数：

| 模式 | 行为 | 适用场景 |
|------|------|---------|
| `async`（默认） | 入队后立即返回，后台 worker 串行处理 | 日常使用，不阻塞 Agent |
| `sync` | 阻塞等待转写完成 | 需要立即拿到转写结果的场景 |
| `off` | 不触发转写 | 已知无语音/图片，或仅元数据同步 |

返回值新增"异步转写已入队 N 条"或"同步转写完成（语音 X/Y，图片 A/B，耗时 Ts）"摘要。

### 批量补转写脚本

历史已同步但未转写的消息，可用 `scripts/` 下的批量脚本补转写（`scripts/` 在 `.gitignore` 中，不提交 git）：

| 脚本 | 用途 | 典型用法 |
|------|------|---------|
| `scripts/batch_transcribe_voice.py` | 批量转写语音 | `python -X utf8 scripts/batch_transcribe_voice.py --days-back 90 --limit 500` |
| `scripts/batch_transcribe_images.py` | 批量转写图片 | `python -X utf8 scripts/batch_transcribe_images.py --days-back 30 --limit 500` |

**注意事项**：
- 首次运行会下载模型（BLIP 约 1GB，Whisper small 约 500MB），耗时 1-2 分钟
- 图片转写典型成功率约 25%（受图片质量、md5 缺失、WCD 404 影响）
- 语音转写典型成功率 >95%（只要 media_0.db 有数据，几乎都能识别）
