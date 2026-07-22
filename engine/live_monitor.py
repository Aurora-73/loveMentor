"""实时消息监听模块。

通过后台线程定时轮询 WCD/WeFlow API，将最新消息写入缓存文件，
供 Agent 在聊天场景中实时读取。

- 不走完整 sync 管道，直接调 API 拉消息
- 不写入 core.db，只写缓存文件
- 轮询间隔可配置（默认 10s），支持多联系人并行监听
- 支持增量读取（只返回上次读取后的新消息）
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path

from engine.config import Config, CACHE_DIR, slug_display_name

logger = logging.getLogger(__name__)

# 延迟导入避免循环依赖
def _smart_wcd_source(config: Config) -> str | None:
    """智能选择 WCD 数据源：微信运行时用 decrypted（需先解密），未运行时用 realtime 直读。"""
    if config.weflow.backend != "wcd":
        return None
    from engine.importers.wcd_client import is_wechat_running
    return "decrypted" if is_wechat_running() else None

LIVE_CACHE_DIR = CACHE_DIR / "live"
DEFAULT_POLL_INTERVAL = 10  # 秒，默认 10s 适合聊天场景
INITIAL_LOOKBACK_MINUTES = 30  # 初始拉取回看分钟数
MIN_INITIAL_MESSAGES = 30  # 初始拉取最少消息条数（时间窗口内不足时扩展到最近 N 条）
DEFAULT_FETCH_LIMIT = 500  # 默认拉取条数
MAX_RETRY = 3  # 最大重试次数
DEFAULT_AUTO_STOP_TIMEOUT = 600  # 默认 10 分钟无读取自动停止


# ---------------------------------------------------------------------------
# 监听管理器
# ---------------------------------------------------------------------------

class _MonitorState:
    """单个联系人的监听状态。"""

    def __init__(self, name: str, wxid: str, display_name: str, cache_path: Path,
                 poll_interval: int, fetch_limit: int,
                 auto_stop_timeout: int = DEFAULT_AUTO_STOP_TIMEOUT):
        self.name = name
        self.wxid = wxid
        self.display_name = display_name
        self.cache_path = cache_path
        self.poll_interval = poll_interval
        self.fetch_limit = fetch_limit
        self.auto_stop_timeout = auto_stop_timeout
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.last_msg_ts: int = 0
        self.new_msg_count: int = 0
        self.started_at: str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.last_poll_at: str = ""
        self.last_error: str = ""
        # 增量读取：文件偏移量，每次 read_cache 后更新
        self.read_offset: int = 0
        # 增量读取：上次读到的消息时间戳
        self.last_read_ts: int = 0
        # 未读消息计数
        self.unread_count: int = 0
        # 心跳 / 自动停止
        self.last_heartbeat: float = time.time()
        # 缓存的 API 客户端（避免每次轮询重建）
        self._client = None
        # 待转写消息跟踪：{msg_id: {type, timestamp, sender, content, time_str}}
        # 用于后续轮询时检查转写是否完成，完成则追加更新到缓存
        self.pending_media: dict[str, dict] = {}

    def _is_stale(self) -> bool:
        """检查是否超过自动停止超时未读取。"""
        return time.time() - self.last_heartbeat > self.auto_stop_timeout


class LiveMonitorManager:
    """管理所有联系人的实时监听。"""

    def __init__(self):
        self._monitors: dict[str, _MonitorState] = {}  # name → state
        self._lock = threading.Lock()

    # ── 公开方法 ──

    def start(self, name: str, wxid: str, display_name: str, config: Config,
              poll_interval: int = DEFAULT_POLL_INTERVAL,
              fetch_limit: int = DEFAULT_FETCH_LIMIT,
              include_brief: bool = False,
              auto_stop_timeout: int = DEFAULT_AUTO_STOP_TIMEOUT) -> dict:
        """开始监听联系人。

        Args:
            poll_interval: 轮询间隔秒数，默认 10s
            fetch_limit: 每次拉取消息上限，默认 500
            include_brief: 是否在返回中附带 person_brief 快照
            auto_stop_timeout: 无读取自动停止秒数，默认 600（10 分钟）。
                               传给 0 或负值禁用自动停止。
        """
        with self._lock:
            if name in self._monitors:
                return {"status": "already_running", "name": name}

            slug = slug_display_name(display_name)
            cache_path = LIVE_CACHE_DIR / f"{slug}_live.md"
            LIVE_CACHE_DIR.mkdir(parents=True, exist_ok=True)

            state = _MonitorState(
                name, wxid, display_name, cache_path,
                poll_interval=poll_interval,
                fetch_limit=fetch_limit,
                auto_stop_timeout=auto_stop_timeout,
            )

            # 初始拉取：最近 INITIAL_LOOKBACK_MINUTES 分钟的消息，且至少 MIN_INITIAL_MESSAGES 条
            now = int(time.time())
            since_ts = now - INITIAL_LOOKBACK_MINUTES * 60
            # 创建客户端一次，后续轮询复用
            client = self._build_client(config)
            state._client = client
            messages = self._fetch_messages(config, wxid, fetch_limit, client=client)
            # 先按时间窗口过滤
            time_window_msgs = [m for m in messages if m.get("createTime", 0) >= since_ts]
            # 时间窗口内不足 MIN_INITIAL_MESSAGES 条时，扩展到最近 N 条（按时间升序取末尾）
            if len(time_window_msgs) < MIN_INITIAL_MESSAGES and messages:
                sorted_msgs = sorted(messages, key=lambda m: m.get("createTime", 0))
                initial_msgs = sorted_msgs[-MIN_INITIAL_MESSAGES:]
            else:
                initial_msgs = time_window_msgs

            # 构建引用查找表（从当前批次中查找被引用消息）
            reply_lookup = self._build_reply_lookup_from_batch(messages, display_name)

            # 批量查询语音/图片转写文字
            media_msg_ids = [
                str(m.get("serverId") or m.get("platformMessageId") or "")
                for m in initial_msgs
                if m.get("mediaType") in ("image", "voice")
            ]
            transcription_lookup = self._batch_query_transcriptions(media_msg_ids)

            # 写入缓存文件
            self._write_cache_header(state, len(initial_msgs))
            for msg in initial_msgs:
                self._append_message(
                    state, msg,
                    reply_lookup=reply_lookup,
                    transcription_lookup=transcription_lookup,
                )

            if initial_msgs:
                state.last_msg_ts = max(m["createTime"] for m in initial_msgs)
            else:
                state.last_msg_ts = now

            # 初始化读取偏移量到文件开头，首次 since_last_read 能读到初始消息
            state.read_offset = 0
            state.last_read_ts = state.last_msg_ts

            # 启动后台线程
            state.thread = threading.Thread(
                target=self._poll_loop,
                args=(state, config, client),
                daemon=True,
                name=f"live-monitor-{slug}",
            )
            state.thread.start()

            self._monitors[name] = state

            result: dict = {
                "status": "started",
                "name": name,
                "display_name": display_name,
                "initial_messages": len(initial_msgs),
                "cache_path": str(cache_path),
                "last_msg_ts": state.last_msg_ts,
                "poll_interval": poll_interval,
                "fetch_limit": fetch_limit,
            }

            # 可选：附带 brief 快照
            if include_brief:
                result["brief"] = self._get_brief_snapshot(config, wxid, display_name)

            return result

    def stop(self, name: str | None = None) -> dict:
        """停止监听。name 为空时停止所有。"""
        with self._lock:
            if name:
                if name not in self._monitors:
                    return {"status": "not_found", "name": name}
                states = [self._monitors.pop(name)]
            else:
                states = list(self._monitors.values())
                self._monitors.clear()

        stopped = []
        for state in states:
            state.stop_event.set()
            if state.thread and state.thread.is_alive():
                state.thread.join(timeout=5)
            stopped.append({
                "name": state.name,
                "new_messages": state.new_msg_count,
                "unread_count": state.unread_count,
                "cache_path": str(state.cache_path),
            })

        return {"status": "stopped", "monitors": stopped}

    def status(self) -> dict:
        """查看监听状态。"""
        with self._lock:
            monitors = []
            for name, state in self._monitors.items():
                monitors.append({
                    "name": name,
                    "display_name": state.display_name,
                    "started_at": state.started_at,
                    "last_msg_ts": state.last_msg_ts,
                    "new_msg_count": state.new_msg_count,
                    "unread_count": state.unread_count,
                    "poll_interval": state.poll_interval,
                    "last_poll_at": state.last_poll_at,
                    "last_error": state.last_error,
                    "cache_path": str(state.cache_path),
                })
            return {"status": "ok", "monitors": monitors, "total": len(monitors)}

    def read_cache(self, name: str, recent: int = 0,
                   since_last_read: bool = False) -> str:
        """读取缓存文件。

        Args:
            recent: 返回最后 N 条消息。0 = 返回全部（或增量）。
            since_last_read: True = 只返回上次读取后的新消息。
                             recent 参数此时被忽略。
        """
        with self._lock:
            state = self._monitors.get(name)
        if not state:
            return f"未在监听: {name}"

        if not state.cache_path.exists():
            return f"缓存文件不存在: {state.cache_path}"

        # 更新心跳
        state.last_heartbeat = time.time()

        # 增量读取模式
        if since_last_read:
            return self._read_incremental(state)

        # 全量/截断模式
        content = state.cache_path.read_text(encoding="utf-8")
        if recent <= 0:
            # 全量读取，更新 offset
            state.read_offset = state.cache_path.stat().st_size
            state.last_read_ts = state.last_msg_ts
            state.unread_count = 0
            return content

        # 返回最后 recent 条消息
        lines = content.split("\n")
        msg_lines = [l for l in lines if l.strip().startswith("[")]
        other_lines = [l for l in lines if not l.strip().startswith("[") and not l.strip().startswith("---")]

        if len(msg_lines) <= recent:
            state.read_offset = state.cache_path.stat().st_size
            state.last_read_ts = state.last_msg_ts
            state.unread_count = 0
            state.last_heartbeat = time.time()
            return content

        header = "\n".join(other_lines[:10])
        tail_msgs = "\n".join(msg_lines[-recent:])
        # 更新 offset（标记已读到末尾）
        state.read_offset = state.cache_path.stat().st_size
        state.last_read_ts = state.last_msg_ts
        state.unread_count = 0
        state.last_heartbeat = time.time()
        return f"{header}\n\n--- (仅显示最后 {recent} 条) ---\n\n{tail_msgs}"

    # ── 内部方法 ──

    def _read_incremental(self, state: _MonitorState) -> str:
        """增量读取：从上次 offset 位置开始读。"""
        file_size = state.cache_path.stat().st_size

        # 如果文件被重写（重新 start），offset 会大于文件大小
        if state.read_offset > file_size:
            state.read_offset = 0

        # 从 offset 读取新内容
        with open(state.cache_path, "r", encoding="utf-8") as f:
            f.seek(state.read_offset)
            new_content = f.read()

        # 更新 offset 和心跳
        state.read_offset = file_size
        state.last_read_ts = state.last_msg_ts
        state.unread_count = 0
        state.last_heartbeat = time.time()

        if not new_content.strip():
            return "（无新消息）"

        return new_content

    def _poll_loop(self, state: _MonitorState, config: Config, client=None):
        """后台轮询线程。"""
        logger.info(
            f"实时监听已启动: {state.name} "
            f"(interval={state.poll_interval}s, wxid={state.wxid[:20]}...)"
        )

        while not state.stop_event.is_set():
            if state.stop_event.wait(timeout=state.poll_interval):
                break

            state.last_poll_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # 指数退避重试
            success = False
            for attempt in range(MAX_RETRY):
                if state.stop_event.is_set():
                    break
                try:
                    messages = self._fetch_messages(
                        config, state.wxid, state.fetch_limit, client=client
                    )
                    new_msgs = [
                        m for m in messages
                        if m.get("createTime", 0) > state.last_msg_ts
                    ]

                    if new_msgs:
                        # 构建引用查找表（从当前批次中查找被引用消息）
                        reply_lookup = self._build_reply_lookup_from_batch(
                            messages, state.display_name
                        )
                        # 批量查询语音/图片转写文字
                        media_msg_ids = [
                            str(m.get("serverId") or m.get("platformMessageId") or "")
                            for m in new_msgs
                            if m.get("mediaType") in ("image", "voice")
                        ]
                        transcription_lookup = self._batch_query_transcriptions(media_msg_ids)
                        for msg in new_msgs:
                            self._append_message(
                                state, msg,
                                reply_lookup=reply_lookup,
                                transcription_lookup=transcription_lookup,
                            )
                        state.last_msg_ts = max(m["createTime"] for m in new_msgs)
                        state.new_msg_count += len(new_msgs)
                        state.unread_count += len(new_msgs)
                        state.last_error = ""
                        logger.info(
                            f"实时监听 {state.name}: 新增 {len(new_msgs)} 条消息 "
                            f"(未读 {state.unread_count})"
                        )
                    else:
                        # 无新消息，更新刷新标记
                        self._append_refresh_marker(state)

                    # 检查待转写消息是否已完成（无论有无新消息都检查）
                    self._check_pending_transcriptions(state)

                    success = True
                    break

                except Exception as e:
                    state.last_error = str(e)
                    if attempt < MAX_RETRY - 1:
                        backoff = (attempt + 1) * state.poll_interval
                        logger.warning(
                            f"轮询 {state.name} 第 {attempt+1} 次失败: {e}, "
                            f"{backoff}s 后重试"
                        )
                        if state.stop_event.wait(timeout=backoff):
                            break
                    else:
                        logger.warning(
                            f"轮询 {state.name} 全部 {MAX_RETRY} 次重试失败: {e}"
                        )

            if not success:
                # 重试全部失败，等待一个正常周期再继续
                continue

            # 自动停止检测：超过 auto_stop_timeout 无读取则自动关闭
            if state.auto_stop_timeout > 0 and state._is_stale():
                stale_min = state.auto_stop_timeout // 60
                logger.info(
                    f"实时监听 {state.name}: 超过 {stale_min} 分钟无读取，自动停止"
                )
                break

        # 从管理器清理（线程退出前）
        with self._lock:
            if state.name in self._monitors:
                del self._monitors[state.name]
        logger.info(f"实时监听已停止: {state.name}")

    def _fetch_messages(self, config: Config, wxid: str, limit: int,
                        client=None) -> list[dict]:
        """直接调 API 拉消息（不走 sync 管道）。

        Args:
            client: 可选的缓存客户端，避免每次轮询重建
        """
        if client is None:
            client = self._build_client(config)
        # 智能数据源切换：微信运行时用 decrypted（需先解密），未运行时用 realtime
        wcd_source = _smart_wcd_source(config)
        if wcd_source == "decrypted":
            # 使用 decrypted 前先刷新解密快照（有 5 分钟防抖，不会重复解密）
            try:
                client.decrypt_databases()
            except Exception as e:
                logger.warning(f"数据库解密失败（使用旧快照）: {e}")
        kwargs: dict = {"talker": wxid, "limit": limit}
        if wcd_source:
            kwargs["source"] = wcd_source
        resp = client.get_messages(**kwargs)
        return resp.get("messages", [])

    def _build_client(self, config: Config):
        """构建 API 客户端。"""
        if config.weflow.backend == "wcd":
            from engine.importers.wcd_client import WCDClient
            return WCDClient(
                base_url=config.weflow.base_url,
                token=config.weflow.token,
                timeout=config.weflow.timeout,
                decrypted_db_dir=config.weflow.decrypted_db_dir or None,
            )
        from engine.importers.weflow_client import WeFlowClient
        return WeFlowClient(
            base_url=config.weflow.base_url,
            token=config.weflow.token,
            timeout=config.weflow.timeout,
        )

    def _get_brief_snapshot(self, config: Config, wxid: str, display_name: str) -> str:
        """获取 person_brief 快照（可选）。"""
        try:
            import sqlite3
            from engine.agent.core import _get_conn, _resolve_person
            from engine.agent.brief import agent_brief

            conn, _ = _get_conn()
            try:
                person = _resolve_person(conn, display_name)
                if person:
                    return agent_brief(conn, config, person, compact=True)
            finally:
                conn.close()
        except Exception as e:
            logger.warning(f"获取 brief 快照失败: {e}")
            return ""
        return ""

    def _write_cache_header(self, state: _MonitorState, msg_count: int):
        """写入缓存文件头部。"""
        state.cache_path.write_text(
            f"# 实时监听: {state.display_name}\n"
            f"> 开始时间: {state.started_at}\n"
            f"> 联系人ID: {state.wxid}\n"
            f"> 轮询间隔: {state.poll_interval}s\n"
            f"> 初始消息: {msg_count} 条\n"
            f"> 最后更新: {state.started_at}\n"
            f"> 新增消息: 0 条\n"
            f"> 未读消息: 0 条\n"
            f"\n---\n\n",
            encoding="utf-8",
        )

    def _batch_query_transcriptions(self, msg_ids: list[str]) -> dict[str, dict]:
        """批量查询 core.db 获取语音/图片转写文字。

        Args:
            msg_ids: 消息 ID 列表

        Returns:
            {msg_id: {"type": "voice"|"image", "text": "转写文字"}}
            只有有转写文字的条目在 dict 中
        """
        if not msg_ids:
            return {}
        try:
            from engine.agent.core import _get_conn
            conn, _ = _get_conn()
            try:
                placeholders = ",".join("?" * len(msg_ids))
                sql = (
                    f"SELECT id, type, voice_text, image_text "
                    f"FROM messages WHERE id IN ({placeholders})"
                )
                rows = conn.execute(sql, msg_ids).fetchall()
                result: dict[str, dict] = {}
                for row in rows:
                    msg_id = str(row["id"])
                    msg_type = row["type"] or 0
                    base_type = int(msg_type) & 0xFF
                    if base_type == 34:  # 语音
                        text = row["voice_text"] or ""
                        if text and text != "__FAILED__":
                            result[msg_id] = {"type": "voice", "text": text}
                    elif base_type == 3:  # 图片
                        text = row["image_text"] or ""
                        if text and text != "__FAILED__":
                            result[msg_id] = {"type": "image", "text": text}
                return result
            finally:
                conn.close()
        except Exception as e:
            logger.debug(f"批量查询转写文字失败: {e}")
            return {}

    def _build_reply_lookup_from_batch(self, messages: list[dict], display_name: str) -> dict[str, dict]:
        """从拉取的消息批次构建引用查找表：serverId -> {content, sender}。

        用于在 _append_message 中查找被引用消息的内容，显示引用关系。
        """
        lookup: dict[str, dict] = {}
        for msg in messages:
            msg_id = str(msg.get("serverId") or msg.get("platformMessageId") or "")
            if not msg_id:
                continue
            is_send = msg.get("isSend", False)
            sender = "我" if is_send else display_name
            content = msg.get("content", "") or msg.get("parsedContent", "")

            # 处理特殊消息类型（与 _append_message 一致）
            media_type = msg.get("mediaType", "")
            if media_type == "image":
                content = "[图片]"
            elif media_type == "voice":
                voice_len = msg.get("voiceLength", "")
                content = f"[语音] {voice_len}s" if voice_len else "[语音]"
            elif media_type == "video":
                content = "[视频]"
            elif media_type == "emoji":
                content = "[表情]"

            lookup[msg_id] = {
                "content": content or "",
                "sender": sender,
            }
        return lookup

    def _append_message(self, state: _MonitorState, msg: dict,
                        reply_lookup: dict[str, dict] | None = None,
                        transcription_lookup: dict[str, dict] | None = None):
        """追加一条消息到缓存文件。

        Args:
            reply_lookup: 引用查找表（从当前批次构建），用于显示被引用消息内容
            transcription_lookup: 转写文字查找表 {msg_id: {type, text}}，
                                  用于显示语音/图片的转写内容
        """
        ts = msg.get("createTime", 0)
        time_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S") if ts else "?"
        is_send = msg.get("isSend", False)
        sender = "我" if is_send else state.display_name
        content = msg.get("content", "") or msg.get("parsedContent", "")
        msg_id = str(msg.get("serverId") or msg.get("platformMessageId") or "")

        # 处理特殊消息类型
        media_type = msg.get("mediaType", "")
        is_media_msg = False
        if media_type == "image":
            # 优先用转写文字
            if transcription_lookup and msg_id in transcription_lookup:
                content = transcription_lookup[msg_id]["text"]
            else:
                url = msg.get("mediaUrl", "")
                content = f"[图片] {url}" if url else "[图片]"
                is_media_msg = True
        elif media_type == "voice":
            # 优先用转写文字
            if transcription_lookup and msg_id in transcription_lookup:
                content = transcription_lookup[msg_id]["text"]
            else:
                voice_len = msg.get("voiceLength", "")
                content = f"[语音] {voice_len}s" if voice_len else "[语音]"
                is_media_msg = True
        elif media_type == "video":
            url = msg.get("mediaUrl", "")
            content = f"[视频] {url}" if url else "[视频]"
        elif media_type == "emoji":
            url = msg.get("mediaUrl", "")
            content = f"[表情] {url}" if url else "[表情]"

        # 引用回复：显示被引用消息的内容
        reply_to = msg.get("replyToMessageId")
        if reply_to:
            reply_id_str = str(reply_to)
            if reply_lookup and reply_id_str in reply_lookup:
                ref = reply_lookup[reply_id_str]
                ref_content = ref["content"]
                if len(ref_content) > 50:
                    ref_content = ref_content[:50] + "..."
                content = f"↩回复[{ref['sender']}: {ref_content}] {content}"
            else:
                # 被引用消息不在当前批次中，用简略标记
                content = f"↩回复 {content}"

        # 截断过长内容
        if len(content) > 500:
            content = content[:500] + "...(截断)"

        with open(state.cache_path, "a", encoding="utf-8") as f:
            f.write(f"[{time_str}] {sender}: {content}\n")

        # 跟踪待转写的语音/图片消息（后续轮询检查转写是否完成）
        if is_media_msg and msg_id:
            state.pending_media[msg_id] = {
                "type": media_type,
                "timestamp": ts,
                "sender": sender,
                "time_str": time_str,
            }

    def _check_pending_transcriptions(self, state: _MonitorState):
        """检查待转写消息是否已完成转写，完成则追加更新到缓存。

        在每次轮询时调用，检查 state.pending_media 中的消息是否在 core.db 中
        已有转写文字。如果有，追加一条 [转写完成] 更新行到缓存文件。
        """
        if not state.pending_media:
            return
        pending_ids = list(state.pending_media.keys())
        transcriptions = self._batch_query_transcriptions(pending_ids)
        if not transcriptions:
            return
        # 追加转写完成更新
        with open(state.cache_path, "a", encoding="utf-8") as f:
            for msg_id, info in transcriptions.items():
                if msg_id not in state.pending_media:
                    continue
                pending = state.pending_media[msg_id]
                text = info["text"]
                if len(text) > 200:
                    text = text[:200] + "..."
                f.write(
                    f"[转写完成] {pending['time_str']} {pending['sender']}: {text}\n"
                )
                del state.pending_media[msg_id]
        logger.info(
            f"实时监听 {state.name}: {len(transcriptions)} 条消息转写完成，"
            f"剩余待转写 {len(state.pending_media)} 条"
        )

    def _append_refresh_marker(self, state: _MonitorState):
        """追加刷新标记（无新消息时更新头部时间）。"""
        now_str = datetime.now().strftime("%H:%M:%S")
        content = state.cache_path.read_text(encoding="utf-8")
        lines = content.split("\n")
        updated = []
        for line in lines:
            if line.startswith("> 最后更新:"):
                updated.append(f"> 最后更新: {now_str}")
            elif line.startswith("> 新增消息:"):
                updated.append(f"> 新增消息: {state.new_msg_count} 条")
            elif line.startswith("> 未读消息:"):
                updated.append(f"> 未读消息: {state.unread_count} 条")
            else:
                updated.append(line)
        state.cache_path.write_text("\n".join(updated), encoding="utf-8")


# 全局单例
_manager = LiveMonitorManager()


def get_manager() -> LiveMonitorManager:
    """获取全局监听管理器。"""
    return _manager
