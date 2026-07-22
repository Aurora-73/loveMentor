"""WeChatDataAnalysis HTTP API 客户端。

接口与 WeFlowClient 完全兼容，内部做路径和字段映射。
上层代码（sync_contacts/sync_conversations/sync_messages/sync_moments）零改动。
"""

import json
import logging
import os
import re
import sqlite3
import struct
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from engine.importers.db_init import connect_db

logger = logging.getLogger(__name__)


class WCDError(Exception):
    pass


# 微信进程名（涵盖新旧版本）
_WECHAT_PROCESS_NAMES = ("Weixin.exe", "WeChat.exe")


def is_wechat_running() -> bool:
    """检测微信进程是否正在运行。

    用于智能数据源切换：
    - 微信运行时：WCDB 文件锁被占用，realtime 直读会超时，需用 source="decrypted"
    - 微信未运行：可直接 realtime 直读加密库，无需全量解密

    Returns:
        bool: True 表示微信正在运行
    """
    try:
        import psutil
    except ImportError:
        # psutil 未安装时保守返回 True（走 decrypted 路径，兼容旧逻辑）
        logger.debug("psutil 未安装，假设微信正在运行（使用 decrypted 数据源）")
        return True

    try:
        for p in psutil.process_iter(["name"]):
            if p.info.get("name") in _WECHAT_PROCESS_NAMES:
                return True
    except Exception as e:
        logger.debug(f"检测微信进程失败，保守假设正在运行: {e}")
        return True
    return False


class WCDClient:

    def __init__(self, base_url: str, token: str = "", timeout: int = 30,
                 decrypted_db_dir: str | None = None,
                 decrypt_timeout: int = 120):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self._decrypt_timeout = decrypt_timeout  # 解密操作单独的超时（可能需要几分钟）
        self._decrypted_db_dir = Path(decrypted_db_dir) if decrypted_db_dir else None
        self._label_cache: dict[str, list[str]] | None = None

    def _read_labels(self) -> dict[str, list[str]]:
        """读取标签（带缓存）。需要配置 decrypted_db_dir。"""
        if self._label_cache is not None:
            return self._label_cache
        if not self._decrypted_db_dir:
            self._label_cache = {}
            return self._label_cache
        self._label_cache = _read_contact_labels(self._decrypted_db_dir)
        return self._label_cache

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict:
        url = f"{self.base_url}{path}"
        if params:
            filtered = {k: v for k, v in params.items() if v is not None}
            if filtered:
                url += "?" + urllib.parse.urlencode(filtered)

        headers: dict[str, str] = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise WCDError("WCD API 认证失败 (HTTP 401)") from e
            body_text = ""
            try:
                body_text = e.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            raise WCDError(f"HTTP {e.code}: {body_text}") from e
        except urllib.error.URLError as e:
            raise WCDError(f"连接 WCD API 失败: {e.reason}") from e

    def _post(self, path: str, data: dict | None = None, timeout: int | None = None) -> dict:
        """POST 请求（用于 /api/decrypt 等）。

        Args:
            timeout: 单次请求超时秒数，None 时使用 self._decrypt_timeout
        """
        url = f"{self.base_url}{path}"
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        body = json.dumps(data).encode("utf-8") if data else b""
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout or self._decrypt_timeout) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            body_text = ""
            try:
                body_text = e.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            raise WCDError(f"HTTP {e.code}: {body_text}") from e
        except urllib.error.URLError as e:
            raise WCDError(f"连接 WCD API 失败: {e.reason}") from e

    # ── 解密节流 ──
    _DECRYPT_MARKER = ".last_decrypt"
    _DECRYPT_INTERVAL = 1800  # 30 分钟内不重复解密
    # 方向C：mtime 防抖最小间隔（避免微信持续运行时每秒解密）
    _DECRYPT_MIN_INTERVAL = 300  # 5 分钟防抖

    def _read_last_decrypt_ts(self) -> int:
        """读取上次解密时间戳。返回 0 表示未解密过或标记损坏。"""
        marker_file = self._decrypted_db_dir.parent / self._DECRYPT_MARKER
        if not marker_file.is_file():
            return 0
        try:
            return int(marker_file.read_text(encoding="utf-8").strip())
        except (ValueError, OSError):
            return 0

    def _get_db_storage_path(self) -> str:
        """从 account_keys.json 读取 db_storage 路径。"""
        keys_file = self._decrypted_db_dir.parent / "account_keys.json"
        if not keys_file.is_file():
            return ""
        try:
            data = json.loads(keys_file.read_text(encoding="utf-8"))
            if not data or not isinstance(data, dict):
                return ""
            account = list(data.values())[0]
            return str(account.get("db_key_source_db_storage_path", "") or "")
        except Exception:
            return ""

    def _check_db_storage_changed(self, last_decrypt_ts: int) -> tuple[bool, str]:
        """方向C：基于 db_storage mtime 判断是否需要解密。

        对比上次解密时间与 db_storage 中 .db 文件最新 mtime：
        - mtime > last_decrypt_ts → 有新数据，需要解密
        - mtime <= last_decrypt_ts → 无新数据，可跳过

        Args:
            last_decrypt_ts: 上次解密的 Unix 时间戳

        Returns:
            (need_decrypt, reason): 是否需要解密, 原因说明
        """
        db_storage_path = self._get_db_storage_path()
        if not db_storage_path or not os.path.isdir(db_storage_path):
            # 路径不可用，保守返回需要解密
            return True, "db_storage 路径不可用，保守触发解密"

        # 扫描 db_storage 下所有 .db 文件，找最新 mtime
        latest_mtime = 0
        latest_db = ""
        try:
            for root, _dirs, files in os.walk(db_storage_path):
                for f in files:
                    if f.endswith(".db"):
                        db_file = os.path.join(root, f)
                        try:
                            mtime = int(os.path.getmtime(db_file))
                            if mtime > latest_mtime:
                                latest_mtime = mtime
                                latest_db = f
                        except OSError:
                            pass
        except Exception as e:
            logger.debug(f"扫描 db_storage mtime 失败: {e}")
            return True, f"扫描失败: {e}"

        if latest_mtime == 0:
            return True, "未找到 .db 文件"

        if latest_mtime > last_decrypt_ts:
            return True, f"检测到新数据（{latest_db} mtime={latest_mtime} > 上次解密 {last_decrypt_ts}）"
        return False, f"数据库无变化（最新 mtime={latest_mtime} <= 上次解密 {last_decrypt_ts}）"

    def decrypt_databases(self, *, force: bool = False) -> dict:
        """用缓存密钥重新解密微信数据库（不重启微信，不重新获取密钥）。

        同步流程中自动调用，确保 WCD 数据库快照与微信最新数据同步。
        密钥从 account_keys.json 读取，无需用户交互。

        方向C 优化：基于 db_storage mtime 智能节流（替代固定 30 分钟）：
        - 5 分钟防抖（避免微信持续运行时频繁解密）
        - mtime 未变化则跳过（无新数据时不浪费解密开销）

        Args:
            force: 为 True 时跳过节流检查，强制解密。
        """
        if not self._decrypted_db_dir:
            logger.info("未配置 decrypted_db_dir，跳过数据库解密")
            return {"status": "skipped", "reason": "未配置 decrypted_db_dir"}

        keys_file = self._decrypted_db_dir.parent / "account_keys.json"
        if not keys_file.is_file():
            logger.info(f"密钥文件不存在: {keys_file}，跳过数据库解密")
            return {"status": "skipped", "reason": f"文件不存在: {keys_file}"}

        # 节流检查（方向C：mtime 智能节流 + 防抖）
        if not force:
            last_ts = self._read_last_decrypt_ts()
            elapsed = int(time.time()) - last_ts if last_ts > 0 else 999999

            # 防抖：5 分钟内不重复解密（即使有新数据）
            if 0 <= elapsed < self._DECRYPT_MIN_INTERVAL:
                logger.info(
                    f"数据库解密跳过（{elapsed}s 前刚解密过，防抖阈值 {self._DECRYPT_MIN_INTERVAL}s）"
                )
                return {"status": "fresh", "reason": f"防抖中（{elapsed}s 前解密）"}

            # mtime 检查：无新数据则跳过（替代原固定 30 分钟节流）
            if last_ts > 0:
                need_decrypt, reason = self._check_db_storage_changed(last_ts)
                if not need_decrypt:
                    logger.info(f"数据库解密跳过: {reason}")
                    return {"status": "fresh", "reason": reason}

        try:
            data = json.loads(keys_file.read_text(encoding="utf-8"))
        except Exception as e:
            raise WCDError(f"读取密钥文件失败: {e}") from e

        if not data or not isinstance(data, dict):
            return {"status": "skipped", "reason": "密钥文件为空"}

        # WCD 有多个账号时用相同密钥，只取第一个即可
        account = list(data.values())[0]
        db_key = account.get("db_key", "")
        db_path = account.get("db_key_source_db_storage_path", "")

        if not db_key or not db_path:
            raise WCDError("account_keys.json 中缺少 db_key 或 db_key_source_db_storage_path")

        logger.info("正在重新解密微信数据库（使用缓存密钥）...")
        try:
            result = self._post("/api/decrypt", {
                "key": db_key,
                "db_storage_path": db_path,
            })
        except WCDError:
            raise
        except Exception:
            raise WCDError("解密数据库失败") from None

        success = result.get("success_count", 0)
        failed = result.get("failure_count", 0)
        logger.info(f"数据库解密完成: 成功 {success}, 失败 {failed}")

        # 写入解密时间标记，下次同步跳过重复解密
        if success > 0:
            try:
                marker_file = self._decrypted_db_dir.parent / self._DECRYPT_MARKER
                marker_file.write_text(str(int(time.time())), encoding="utf-8")
            except OSError:
                pass

        return result

    def decrypt_databases_lite(self) -> dict:
        """轻量解密：只解密 contact.db + head_image.db（跳过 GB 级 message_*.db）。

        用于头像快速刷新场景：avatar_fetcher._query_avatar_via_wcd_api 调用。
        比 decrypt_databases(force=True) 快得多（1-3 秒 vs 几分钟），因为：
        - contact.db / head_image.db 通常只有几 MB
        - 跳过 message_0.db / message_1.db 等大文件

        与 decrypt_databases 的差异：
        - 不节流：每次调用都实际解密（因为头像刷新是按需触发，频率低）
        - 不写节流标记：不影响 decrypt_databases 的节流逻辑
        - 调用 /api/decrypt_lite 端点（WCD 项目新增）

        Returns:
            dict: 与 decrypt_databases 返回格式相同
                - status: completed/failed/skipped
                - success_count/failure_count: 解密统计
        """
        if not self._decrypted_db_dir:
            logger.info("[decrypt_lite] 未配置 decrypted_db_dir，跳过")
            return {"status": "skipped", "reason": "未配置 decrypted_db_dir"}

        keys_file = self._decrypted_db_dir.parent / "account_keys.json"
        if not keys_file.is_file():
            logger.info(f"[decrypt_lite] 密钥文件不存在: {keys_file}，跳过")
            return {"status": "skipped", "reason": f"文件不存在: {keys_file}"}

        try:
            data = json.loads(keys_file.read_text(encoding="utf-8"))
        except Exception as e:
            raise WCDError(f"[decrypt_lite] 读取密钥文件失败: {e}") from e

        if not data or not isinstance(data, dict):
            return {"status": "skipped", "reason": "密钥文件为空"}

        account = list(data.values())[0]
        db_key = account.get("db_key", "")
        db_path = account.get("db_key_source_db_storage_path", "")

        if not db_key or not db_path:
            raise WCDError("[decrypt_lite] account_keys.json 中缺少 db_key 或 db_key_source_db_storage_path")

        logger.info("[decrypt_lite] 正在轻量解密（仅 contact.db + head_image.db）...")
        try:
            result = self._post("/api/decrypt_lite", {
                "key": db_key,
                "db_storage_path": db_path,
            })
        except WCDError:
            raise
        except Exception:
            raise WCDError("[decrypt_lite] 轻量解密数据库失败") from None

        success = result.get("success_count", 0)
        failed = result.get("failure_count", 0)
        logger.info(f"[decrypt_lite] 完成: 成功 {success}, 失败 {failed}")

        # 不写节流标记：lite 解密不影响全量解密的节流逻辑
        return result

    def health(self) -> bool:
        try:
            self._get("/api/health")
            return True
        except WCDError:
            return False

    def check_cached_keys(self) -> dict:
        """检查 account_keys.json 中是否已缓存密钥。"""
        if not self._decrypted_db_dir:
            return {"cached": False, "reason": "未配置 decrypted_db_dir"}
        keys_file = self._decrypted_db_dir.parent / "account_keys.json"
        if not keys_file.is_file():
            return {"cached": False, "reason": f"文件不存在: {keys_file}"}
        try:
            data = json.loads(keys_file.read_text(encoding="utf-8"))
            accounts = list(data.keys()) if isinstance(data, dict) else []
            return {"cached": bool(accounts), "accounts": accounts, "path": str(keys_file)}
        except Exception as e:
            return {"cached": False, "reason": f"解析失败: {e}"}

    def fetch_keys(self, wechat_install_path: str | None = None) -> dict:
        """获取微信数据库密钥（需要重启微信 + 扫码登录）。

        ⚠️ 不建议使用此方法：
        - 会强制关闭并重启微信进程
        - 需要用户在 60 秒内完成扫码登录
        - 频繁调用可能导致微信账号异常
        - 密钥应通过 account_keys.json 持久化，无需重复获取

        正确做法：确保 output/account_keys.json 存在且包含有效密钥。
        """
        logger.warning(
            "fetch_keys 被调用 — 这会重启微信进程并要求扫码登录，不建议频繁使用。"
            "密钥应通过 account_keys.json 持久化。"
        )
        params: dict[str, Any] = {}
        if wechat_install_path:
            params["wechat_install_path"] = wechat_install_path
        return self._get("/api/get_keys", params=params)

    def list_contacts(
        self,
        keyword: str | None = None,
        limit: int = 100,
        source: str | None = None,
    ) -> list[dict]:
        """获取联系人列表。返回格式兼容 WeFlowClient。

        Args:
            keyword: 搜索关键词（按名称/微信号/wxid 过滤）
            limit: 返回数量上限
            source: 数据源，可选值：
                - None/auto: 自动选择（默认 realtime，微信运行时可能失败）
                - realtime: 直接读 WCDB（微信运行时会超时）
                - decrypted: 读解密后的 DB 副本（微信运行时也可用，但数据可能不是最新）
                推荐场景：
                - 同步流程：用 auto/realtime（获取最新数据）
                - 头像查询：用 decrypted（先调 decrypt_databases 刷新快照，再读 decrypted）
        """
        params: dict[str, Any] = {"limit": limit}
        if keyword:
            params["keyword"] = keyword
        if source:
            params["source"] = source
        resp = self._get("/api/chat/contacts", params=params)

        raw_contacts = resp.get("contacts", [])

        # 从解密后的 contact.db 读取标签
        labels_map = self._read_labels()

        mapped = []
        for c in raw_contacts:
            contact_type = c.get("contactType") or c.get("type") or ""
            username = c.get("username", "")
            mapped.append({
                "id": username,
                "username": username,
                "nickname": c.get("nickname", ""),
                "remark": c.get("remark", ""),
                "alias": c.get("alias", ""),
                "displayName": c.get("name") or c.get("nickname") or c.get("remark") or username,
                "avatarUrl": c.get("avatar", ""),
                "type": contact_type,
                "labels": labels_map.get(username, []),
            })
        return mapped

    def list_sessions(
        self,
        keyword: str | None = None,
        limit: int = 100,
        source: str | None = None,
    ) -> list[dict]:
        """获取会话列表。返回格式兼容 WeFlowClient。

        Args:
            keyword: 搜索关键词
            limit: 返回数量上限
            source: 数据源（None/auto/realtime/decrypted），同 list_contacts
        """
        params: dict[str, Any] = {"limit": limit}
        if keyword:
            params["keyword"] = keyword
        if source:
            params["source"] = source
        resp = self._get("/api/chat/sessions", params=params)

        raw_sessions = resp.get("sessions", [])
        mapped = []
        for s in raw_sessions:
            username = s.get("id") or s.get("username", "")
            is_group = s.get("isGroup", False)
            # WeFlow 的 type: 1=private, 2=group, 3=channel
            session_type = 2 if is_group else 1
            if username.startswith("gh_"):
                session_type = 3

            # lastMessageTime 格式：WCD 返回 "HH:MM" 或 "MM-DD" 等格式
            # WeFlow 返回 Unix 时间戳（秒）
            last_ts = s.get("lastTimestamp", 0)
            if not last_ts:
                # WCD 可能没有直接返回时间戳，从 lastMessageTime 推断
                last_ts = 0

            mapped.append({
                "username": username,
                "name": s.get("name", ""),
                "displayName": s.get("name", ""),
                "avatarUrl": s.get("avatar", ""),
                "type": session_type,
                "lastMessage": s.get("lastMessage", ""),
                "lastTimestamp": last_ts,
                "unreadCount": s.get("unreadCount", 0),
            })
        return mapped

    def get_messages(
        self,
        talker: str,
        limit: int = 1000,
        offset: int = 0,
        start: str | None = None,
        end: str | None = None,
        source: str | None = None,
    ) -> dict:
        """获取消息。返回格式兼容 WeFlowClient。

        WCD 不支持 start/end 日期参数，改为本地过滤。

        Args:
            source: 数据源（None/auto/realtime/decrypted），同 list_contacts
        """
        params: dict[str, Any] = {
            "username": talker,
            "limit": min(limit, 500),  # WCD 上限 500
            "offset": offset,
        }
        if source:
            params["source"] = source

        resp = self._get("/api/chat/messages", params=params)

        raw_messages = resp.get("messages", [])

        # 本地日期过滤（WCD 不支持 start/end）
        if start or end:
            start_ts = _datestr_to_ts(start) if start else 0
            end_ts = _datestr_to_ts(end) if end else 9999999999
            filtered = []
            for m in raw_messages:
                ts = m.get("createTime", 0)
                if start_ts <= ts <= end_ts:
                    filtered.append(m)
            raw_messages = filtered

        # 字段映射：WCD → WeFlow 格式
        mapped_messages = []
        for m in raw_messages:
            # 媒体 URL：WCD 分散在 imageUrl/videoUrl/emojiUrl
            media_url = m.get("imageUrl") or m.get("videoUrl") or m.get("emojiUrl") or ""

            # 媒体类型推断
            media_type = ""
            render_type = m.get("renderType", "")
            if m.get("voiceLength"):
                media_type = "voice"
            elif m.get("imageUrl"):
                media_type = "image"
            elif m.get("videoUrl"):
                media_type = "video"
            elif m.get("emojiUrl"):
                media_type = "emoji"

            # rawContent：优先用原始内容，表情贴纸构造 XML（兼容 scan_stickers）
            raw_content = m.get("rawContent") or m.get("content", "")
            emoji_md5 = m.get("emojiMd5", "")
            if emoji_md5:
                emoji_url = m.get("emojiUrl", "")
                raw_content = f'<msg><emoji md5="{emoji_md5}" cdnurl="{emoji_url}"/></msg>'

            # 图片消息：WCD 不返回 XML rawContent（只有"[图片]"），从 mediaUrl 提取 md5 构造 XML
            # 否则转写脚本无法获取 md5，图片无法识别
            if str(m.get("type", 0)) == "3" and media_url:
                img_md5_match = re.search(r'md5=([a-f0-9]{32})', media_url, re.IGNORECASE)
                if img_md5_match:
                    img_md5 = img_md5_match.group(1).lower()
                    raw_content = f'<msg><img md5="{img_md5}"/></msg>'

            mapped_messages.append({
                "localId": m.get("localId", 0),
                "serverId": m.get("serverId") or m.get("serverIdStr", ""),
                "localType": m.get("type", 0),
                "createTime": m.get("createTime", 0),
                "isSend": m.get("isSent", False),
                "senderUsername": m.get("senderUsername", ""),
                "content": m.get("content", ""),
                "rawContent": raw_content,
                "parsedContent": m.get("content", ""),
                "replyToMessageId": m.get("quoteServerId") or None,
                "mediaType": media_type,
                "mediaFileName": "",
                "mediaUrl": media_url,
                "mediaLocalPath": "",
                "groupNickname": m.get("groupNickname", ""),
                "accountName": m.get("accountName", ""),
                # 撤回标记：WCD 返回 isRevoked 布尔，或 status==1 表示撤回
                "isRevoked": bool(m.get("isRevoked") or m.get("status", 0) == 1),
            })

        # WCD 没有 hasMore 字段，用消息数量推断
        has_more = len(raw_messages) >= min(limit, 500)

        return {
            "success": resp.get("status") == "success",
            "talker": talker,
            "count": resp.get("total", len(mapped_messages)),
            "hasMore": has_more,
            "messages": mapped_messages,
        }

    def pull_messages(
        self, session_id: str, since: int = 0, limit: int = 5000
    ) -> tuple[list[dict], int, bool]:
        """兼容接口，内部调用 get_messages。"""
        resp = self.get_messages(talker=session_id, limit=limit)
        messages = resp.get("messages", [])
        watermark = since
        for m in messages:
            ts = m.get("createTime", 0)
            if ts > watermark:
                watermark = ts
        return messages, watermark, resp.get("hasMore", False)

    def get_moments_timeline(
        self,
        limit: int = 20,
        offset: int = 0,
        usernames: str | None = None,
        start: str | None = None,
        end: str | None = None,
    ) -> dict:
        """获取朋友圈。返回格式兼容 WeFlowClient。"""
        params: dict[str, Any] = {"limit": limit}
        if offset > 0:
            params["offset"] = offset
        if usernames:
            params["usernames"] = usernames

        resp = self._get("/api/sns/timeline", params=params)

        # WCD 返回格式：{"status": "success", "posts": [...]} 或 {"timeline": [...]}
        # WeFlow 返回 {"posts": [...]}
        posts = resp.get("posts") or resp.get("timeline") or []

        # 日期过滤
        if start or end:
            start_ts = _datestr_to_ts(start) if start else 0
            end_ts = _datestr_to_ts(end) if end else 9999999999
            posts = [p for p in posts if start_ts <= p.get("createTime", 0) <= end_ts]

        return {"posts": posts}

    def get_media_url(self, relative_path: str) -> str:
        """获取媒体下载 URL。WCD 使用分类型端点。"""
        # 根据路径推断类型
        if "/images/" in relative_path or relative_path.endswith((".jpg", ".png", ".gif", ".jpeg")):
            return f"{self.base_url}/api/chat/media/image?md5={urllib.parse.quote(relative_path)}"
        elif "/voices/" in relative_path or relative_path.endswith((".slk", ".amr", ".silk")):
            return f"{self.base_url}/api/chat/media/voice?md5={urllib.parse.quote(relative_path)}"
        elif "/videos/" in relative_path or relative_path.endswith((".mp4", ".mov")):
            return f"{self.base_url}/api/chat/media/video?md5={urllib.parse.quote(relative_path)}"
        else:
            return f"{self.base_url}/api/media/resource/{urllib.parse.quote(relative_path)}"

    def download_media(self, relative_path: str, save_path: str) -> bool:
        """下载媒体文件。"""
        url = self.get_media_url(relative_path)
        headers: dict[str, str] = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        req = urllib.request.Request(url, headers=headers)
        try:
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                with open(save_path, "wb") as f:
                    while True:
                        chunk = resp.read(8192)
                        if not chunk:
                            break
                        f.write(chunk)
            return True
        except Exception as e:
            logger.warning(f"下载媒体失败 {relative_path}: {e}")
            return False


def _datestr_to_ts(datestr: str) -> int:
    """YYYYMMDD 字符串 → Unix 时间戳。"""
    if not datestr:
        return 0
    try:
        from datetime import datetime
        dt = datetime.strptime(datestr, "%Y%m%d")
        return int(dt.timestamp())
    except (ValueError, OSError):
        return 0


# ---------------------------------------------------------------------------
# 标签提取（从解密后的 contact.db 读取）
# ---------------------------------------------------------------------------

def _find_contact_db(decrypted_db_dir: Path) -> Path | None:
    """在解密数据库目录中找到 contact.db。"""
    if not decrypted_db_dir.is_dir():
        return None
    # WeChatDataAnalysis 的解密输出在 output/databases/{account}/contact.db
    for account_dir in decrypted_db_dir.iterdir():
        if not account_dir.is_dir():
            continue
        contact_db = account_dir / "contact.db"
        if contact_db.is_file():
            return contact_db
    # 也检查直接在目录下的 contact.db
    direct = decrypted_db_dir / "contact.db"
    if direct.is_file():
        return direct
    return None


def _read_label_name_map(contact_db_path: Path) -> dict[int, str]:
    """从 contact_label 表读取 {label_id → label_name} 映射。"""
    label_map: dict[int, str] = {}
    try:
        conn = connect_db(contact_db_path)
        # 检查 contact_label 表是否存在
        table_check = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='contact_label'"
        ).fetchone()
        if not table_check:
            conn.close()
            return label_map

        # 获取列名（WeFlow 做了列名探测，这里简化处理）
        columns = {row[1] for row in conn.execute("PRAGMA table_info(contact_label)").fetchall()}

        id_col = None
        name_col = None
        for candidate in ("label_id_", "label_id", "labelId", "id"):
            if candidate in columns:
                id_col = candidate
                break
        for candidate in ("label_name_", "label_name", "labelName", "name"):
            if candidate in columns:
                name_col = candidate
                break

        if id_col and name_col:
            rows = conn.execute(
                f'SELECT "{id_col}" AS lid, "{name_col}" AS lname FROM contact_label'
            ).fetchall()
            for row in rows:
                try:
                    lid = int(row[0])
                    lname = str(row[1] or "").strip()
                    if lid > 0 and lname:
                        label_map[lid] = lname
                except (ValueError, TypeError):
                    pass

        conn.close()
    except Exception as e:
        logger.debug(f"读取 contact_label 失败: {e}")
    return label_map


def _parse_label_ids_from_extra_buffer(raw: bytes) -> list[int]:
    """从 extra_buffer 的 protobuf 中提取 field 30（标签 ID 列表）。

    WeFlow 的 extra_buffer 是 protobuf 编码。field 30 的 wire_type=2（length-delimited），
    内部是 packed repeated varint。
    """
    if not raw:
        return []

    label_ids: list[int] = []
    idx = 0
    n = len(raw)

    while idx < n:
        # 读 tag（varint）
        tag, idx = _pb_read_varint(raw, idx)
        if tag is None:
            break
        field_no = tag >> 3
        wire_type = tag & 0x7

        if wire_type == 0:  # varint
            _, idx = _pb_read_varint(raw, idx)
            if idx is None:
                break
        elif wire_type == 2:  # length-delimited
            size, idx = _pb_read_varint(raw, idx)
            if idx is None or size is None:
                break
            end = idx + int(size)
            if end > n:
                break
            chunk = raw[idx:end]
            idx = end

            if field_no == 30:
                # packed repeated varint
                sub_idx = 0
                while sub_idx < len(chunk):
                    val, sub_idx = _pb_read_varint(chunk, sub_idx)
                    if val is None:
                        break
                    label_ids.append(int(val))
        elif wire_type == 1:  # 64-bit
            idx += 8
        elif wire_type == 5:  # 32-bit
            idx += 4
        else:
            break

    return label_ids


def _pb_read_varint(data: bytes, offset: int) -> tuple[int | None, int]:
    """读取 protobuf varint。返回 (value, new_offset)，失败返回 (None, offset)。"""
    result = 0
    shift = 0
    while offset < len(data):
        b = data[offset]
        offset += 1
        result |= (b & 0x7F) << shift
        if (b & 0x80) == 0:
            return result, offset
        shift += 7
        if shift > 63:
            return None, offset
    return None, offset


def _read_contact_labels(decrypted_db_dir: Path) -> dict[str, list[str]]:
    """读取所有联系人的标签。返回 {username: [label_name, ...]}。"""
    contact_db = _find_contact_db(decrypted_db_dir)
    if not contact_db:
        return {}

    label_map = _read_label_name_map(contact_db)
    if not label_map:
        return {}

    result: dict[str, list[str]] = {}
    try:
        conn = connect_db(contact_db)
        rows = conn.execute("SELECT username, extra_buffer FROM contact").fetchall()
        for row in rows:
            username = str(row[0] or "").strip()
            if not username:
                continue
            raw = row[1]
            if isinstance(raw, memoryview):
                raw = raw.tobytes()
            elif not isinstance(raw, (bytes, bytearray)):
                raw = b""
            ids = _parse_label_ids_from_extra_buffer(raw)
            if ids:
                names = []
                seen = set()
                for lid in ids:
                    name = label_map.get(lid)
                    if name and name not in seen:
                        seen.add(name)
                        names.append(name)
                if names:
                    result[username] = names
        conn.close()
    except Exception as e:
        logger.debug(f"读取联系人标签失败: {e}")

    return result
