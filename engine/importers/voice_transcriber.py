"""语音消息转文字模块。

从 WCD 解密后的 media_0.db 读取 SILK v3 语音数据，
用 pysilk 解码为 PCM，再用 faster-whisper 识别为文字。

依赖：
- pysilk-mod（SILK v3 解码）
- faster-whisper（基于 CTranslate2 的 Whisper 实现）

数据流：
    media_0.db.VoiceInfo.voice_data (SILK v3 BLOB)
    → pysilk.decode() → PCM 16-bit 24kHz
    → wave 模块封装为 WAV bytes
    → faster-whisper.transcribe() → 文字
    → 写入 messages.voice_text

关联键：messages.id (server_id) == VoiceInfo.svr_id
"""
import io
import logging
import sqlite3
import wave
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── 默认配置 ──
DEFAULT_MODEL_SIZE = "small"      # tiny/base/small/medium/large-v3
DEFAULT_DEVICE = "cpu"            # cpu/cuda
DEFAULT_COMPUTE_TYPE = "int8"     # int8（CPU 推荐）/float16（GPU）
DEFAULT_SAMPLE_RATE = 24000       # 微信语音默认采样率（24kHz）
DEFAULT_LANGUAGE = "zh"           # 中文
DEFAULT_BEAM_SIZE = 5
# initial_prompt 引导模型输出简体中文（测试验证有效）
DEFAULT_INITIAL_PROMPT = "请用简体中文输出："
# 标记识别失败的占位符（避免反复重试失败的消息）
# 用 __FAILED__ 而非空字符串，可区分"识别失败"和"未识别"
# chat.py 的 extract_display_content 会检测此标记并回退为 [语音] 占位
FAILED_MARKER = "__FAILED__"
# 来源标记前缀（用户要求：图片和语音转成的文字需要特殊标记来源）
SOURCE_PREFIX = "[语音转文字] "


class VoiceTranscriber:
    """语音转文字器。

    首次调用 transcribe() 时加载 Whisper 模型（约 3-90s，取决于模型大小）。
    后续调用复用模型实例。

    Example:
        >>> transcriber = VoiceTranscriber(
        ...     media_db_path="path/to/media_0.db",
        ...     model_size="small",
        ... )
        >>> text = transcriber.transcribe("6545484061831403334")
        >>> print(text)
        "我当时那个领导他结过婚了"
    """

    def __init__(
        self,
        media_db_path: str | Path,
        model_size: str = DEFAULT_MODEL_SIZE,
        device: str = DEFAULT_DEVICE,
        compute_type: str = DEFAULT_COMPUTE_TYPE,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        language: str = DEFAULT_LANGUAGE,
        beam_size: int = DEFAULT_BEAM_SIZE,
        initial_prompt: str = DEFAULT_INITIAL_PROMPT,
    ):
        self.media_db_path = Path(media_db_path)
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.sample_rate = sample_rate
        self.language = language
        self.beam_size = beam_size
        self.initial_prompt = initial_prompt
        self._model = None  # 延迟加载
        self._db_conn = None  # 复用 media_0.db 连接

    # ── 模型加载（延迟）──

    @property
    def model(self):
        """延迟加载 Whisper 模型。"""
        if self._model is None:
            from faster_whisper import WhisperModel
            logger.info(
                f"加载 Whisper 模型: {self.model_size} "
                f"({self.device}/{self.compute_type})"
            )
            self._model = WhisperModel(
                self.model_size,
                device=self.device,
                compute_type=self.compute_type,
            )
        return self._model

    # ── 数据库连接（复用）──

    def _get_media_db(self) -> sqlite3.Connection:
        """复用 media_0.db 连接。"""
        if self._db_conn is None:
            if not self.media_db_path.exists():
                raise FileNotFoundError(
                    f"media_0.db 不存在: {self.media_db_path}\n"
                    f"请先运行 WCD 解密（cd _reference/WeChatDataAnalysis && uv run main.py）"
                )
            self._db_conn = sqlite3.connect(
                str(self.media_db_path), check_same_thread=False
            )
        return self._db_conn

    def close(self):
        """释放资源。"""
        if self._db_conn is not None:
            self._db_conn.close()
            self._db_conn = None
        self._model = None

    # ── 核心流程 ──

    def _fetch_voice_data(self, server_id: int) -> Optional[bytes]:
        """从 media_0.db 查询语音数据（SILK v3 BLOB）。

        Args:
            server_id: 消息的 server_id（对应 VoiceInfo.svr_id）

        Returns:
            SILK v3 字节流，查询失败返回 None
        """
        try:
            conn = self._get_media_db()
            cur = conn.execute(
                "SELECT voice_data FROM VoiceInfo "
                "WHERE svr_id = ? ORDER BY create_time DESC LIMIT 1",
                (int(server_id),),
            )
            row = cur.fetchone()
            if not row or row[0] is None:
                logger.debug(f"VoiceInfo 中无 svr_id={server_id} 的记录")
                return None
            data = row[0]
            if isinstance(data, (memoryview, bytearray)):
                data = bytes(data)
            return data
        except sqlite3.Error as e:
            logger.warning(f"查询语音数据失败 (svr_id={server_id}): {e}")
            return None

    def _decode_silk_to_pcm(self, silk_data: bytes) -> Optional[bytes]:
        """用 pysilk 解码 SILK v3 → PCM 16-bit。

        pysilk-mod 需要完整数据（含 \\x02#!SILK_V3 头部），
        不要去头，否则会报 "Not a valid silk_data"。

        Args:
            silk_data: SILK v3 字节流（含头部）

        Returns:
            PCM 16-bit 字节流，解码失败返回 None
        """
        import pysilk
        try:
            pcm = pysilk.decode(silk_data, sample_rate=self.sample_rate)
            return pcm
        except Exception as e:
            logger.warning(f"SILK 解码失败: {e}")
            return None

    def _pcm_to_wav_file(self, pcm: bytes) -> io.BytesIO:
        """PCM 16-bit → WAV file-like object（faster-whisper 需要 file-like）。"""
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self.sample_rate)
            wf.writeframes(pcm)
        # 回到开头供读取
        buf.seek(0)
        return buf

    def decode_to_wav(self, silk_data: bytes) -> Optional[io.BytesIO]:
        """SILK v3 → WAV file-like object（步骤 2-3：解码 + 封装）。

        从 transcribe() 拆分出来，便于批量并行 SILK 解码。
        """
        pcm = self._decode_silk_to_pcm(silk_data)
        if not pcm:
            return None
        return self._pcm_to_wav_file(pcm)

    def transcribe_wav(self, wav_file: io.BytesIO) -> Optional[str]:
        """Whisper 识别 WAV → 带 [语音转文字] 前缀的文字（步骤 4-5）。

        从 transcribe() 拆分出来，确保 Whisper 模型单实例串行调用。
        """
        try:
            transcribe_kwargs = dict(
                language=self.language,
                beam_size=self.beam_size,
                vad_filter=True,  # 过滤静音段，提升精度
            )
            if self.initial_prompt:
                transcribe_kwargs["initial_prompt"] = self.initial_prompt
            segments, _info = self.model.transcribe(wav_file, **transcribe_kwargs)
            text = "".join(seg.text for seg in segments).strip()
            if not text:
                return None
            return f"{SOURCE_PREFIX}{text}"
        except Exception as e:
            logger.warning(f"Whisper 识别失败: {e}")
            return None

    def batch_fetch_voice_data(self, server_ids: list[str]) -> dict[str, bytes]:
        """批量查询语音数据（减少 DB 往返次数）。

        Args:
            server_ids: server_id 列表

        Returns:
            {server_id: voice_data_bytes}，无数据的条目不在 dict 中
        """
        if not server_ids:
            return {}
        result: dict[str, bytes] = {}
        try:
            conn = self._get_media_db()
            ids_int = [int(sid) for sid in server_ids if sid]
            if not ids_int:
                return {}
            placeholders = ",".join("?" * len(ids_int))
            cur = conn.execute(
                f"SELECT svr_id, voice_data FROM VoiceInfo "
                f"WHERE svr_id IN ({placeholders})",
                ids_int,
            )
            for row in cur.fetchall():
                svr_id, data = row
                if data is not None:
                    if isinstance(data, (memoryview, bytearray)):
                        data = bytes(data)
                    result[str(svr_id)] = data
        except sqlite3.Error as e:
            logger.warning(f"批量查询语音数据失败: {e}")
        return result

    def transcribe(self, server_id: str | int) -> Optional[str]:
        """识别单条语音消息，返回带 [语音转文字] 前缀的文字。

        完整流程：
            1. 从 media_0.db 查询 voice_data
            2. pysilk 解码 SILK → PCM
            3. 封装为 WAV bytes
            4. faster-whisper 识别 → 文字
            5. 加 [语音转文字] 前缀

        Args:
            server_id: 消息的 server_id（对应 VoiceInfo.svr_id 和 messages.id）

        Returns:
            "[语音转文字] xxx" 格式的文字，失败返回 None
        """
        # 1. 查询语音数据
        silk_data = self._fetch_voice_data(int(server_id))
        if not silk_data:
            return None

        # 2-3. 解码 SILK → WAV
        wav_file = self.decode_to_wav(silk_data)
        if not wav_file:
            return None

        # 4-5. Whisper 识别 + 加前缀
        return self.transcribe_wav(wav_file)


# ── 批量识别 ──


def transcribe_voice_messages(
    db: sqlite3.Connection,
    transcriber: VoiceTranscriber,
    limit: int = 100,
    session_id: Optional[str] = None,
    verbose: bool = False,
    days_back: int = 30,
    private_only: bool = True,
) -> tuple[int, int]:
    """批量识别未识别的语音消息。

    查询 messages 表中 type=34 且 voice_text IS NULL 的消息，
    逐条识别并更新 voice_text 字段。

    识别失败的消息会被标记为 __FAILED__（避免反复重试）。
    旧的空字符串标记也会被重新处理（自动迁移到 __FAILED__）。
    如需重试失败的消息，可手动执行：
        UPDATE messages SET voice_text=NULL WHERE type=34 AND voice_text='__FAILED__'

    Args:
        db: core.db 连接
        transcriber: VoiceTranscriber 实例
        limit: 最多识别多少条（避免一次跑太久）
        session_id: 指定会话（None = 所有会话）
        verbose: 输出详细日志
        days_back: 只识别最近 N 天的消息（0 = 不限时间）
        private_only: True = 只识别私聊消息（排除群聊）

    Returns:
        (成功识别数, 失败数)
    """
    import time as _time

    # 构建查询条件：未识别 + 旧的空字符串标记（自动迁移到 __FAILED__）
    conditions = ["m.type=34", "(m.voice_text IS NULL OR m.voice_text = '')"]
    params: list = []

    # 时间过滤
    if days_back > 0:
        cutoff_ts = int(_time.time()) - days_back * 86400
        conditions.append(f"m.timestamp >= {cutoff_ts}")

    # 私聊过滤（JOIN conversations 表，type='private' 为私聊）
    if private_only:
        conditions.append("c.type='private'")
    if session_id:
        conditions.append("m.conversation_id=?")
        params.append(session_id)

    where_clause = " AND ".join(conditions)
    sql = (
        f"SELECT m.id FROM messages m "
        f"JOIN conversations c ON m.conversation_id=c.id "
        f"WHERE {where_clause} "
        f"ORDER BY m.timestamp DESC LIMIT ?"
    )
    params.append(limit)

    cursor = db.execute(sql, params)
    msg_ids = [str(row[0]) for row in cursor.fetchall()]
    if not msg_ids:
        logger.info("没有待识别的语音消息")
        return (0, 0)

    if verbose:
        logger.info(f"开始识别 {len(msg_ids)} 条语音消息（days_back={days_back}, private_only={private_only}）...")

    # ── Batch 优化：预取 + 并行 SILK 解码 + 串行 Whisper 识别 ──
    # 1. 批量查询语音数据（一次 DB 查询替代 N 次）
    voice_data_map = transcriber.batch_fetch_voice_data(msg_ids)
    if verbose:
        logger.info(f"  预取语音数据: {len(voice_data_map)}/{len(msg_ids)} 条有数据")

    # 2. 并行 SILK 解码（I/O 密集，ThreadPoolExecutor 加速）
    from concurrent.futures import ThreadPoolExecutor, as_completed
    wav_map: dict[str, io.BytesIO] = {}
    decode_tasks = {
        msg_id: voice_data_map[msg_id]
        for msg_id in msg_ids
        if msg_id in voice_data_map
    }
    if decode_tasks:
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {
                executor.submit(transcriber.decode_to_wav, silk_data): msg_id
                for msg_id, silk_data in decode_tasks.items()
            }
            for future in as_completed(futures):
                msg_id = futures[future]
                try:
                    wav = future.result()
                    if wav is not None:
                        wav_map[msg_id] = wav
                except Exception as e:
                    logger.debug(f"SILK 解码失败 (msg_id={msg_id}): {e}")
    if verbose:
        logger.info(f"  SILK 解码完成: {len(wav_map)}/{len(decode_tasks)} 条成功")

    # 3. 串行 Whisper 识别（模型单实例，必须串行）
    success = 0
    failed = 0
    for i, msg_id in enumerate(msg_ids, 1):
        wav_file = wav_map.get(msg_id)
        if wav_file:
            text = transcriber.transcribe_wav(wav_file)
            if text:
                db.execute(
                    "UPDATE messages SET voice_text=? WHERE id=?",
                    (text, msg_id),
                )
                success += 1
                if verbose:
                    logger.info(f"  [{i}/{len(msg_ids)}] {msg_id}: {text[:50]}")
            else:
                db.execute(
                    "UPDATE messages SET voice_text=? WHERE id=?",
                    (FAILED_MARKER, msg_id),
                )
                failed += 1
                if verbose:
                    logger.info(f"  [{i}/{len(msg_ids)}] {msg_id}: <Whisper 识别失败>")
        else:
            # 无 voice_data 或 SILK 解码失败
            db.execute(
                "UPDATE messages SET voice_text=? WHERE id=?",
                (FAILED_MARKER, msg_id),
            )
            failed += 1
            if verbose:
                logger.info(f"  [{i}/{len(msg_ids)}] {msg_id}: <无语音数据或解码失败>")

        # 每 10 条提交一次，避免长事务
        if i % 10 == 0:
            db.commit()

    db.commit()
    logger.info(f"语音识别完成: 成功 {success}/{len(msg_ids)}，失败 {failed}")
    return (success, failed)


# ── 工厂函数 ──


def find_media_db_path(decrypted_db_dir: str | Path, my_wxid: str) -> Optional[Path]:
    """从 decrypted_db_dir 定位 media_0.db。

    WCD 解密输出结构：{decrypted_db_dir}/{wxid}/media_0.db

    Args:
        decrypted_db_dir: WCD 解密数据库目录（config.weflow.decrypted_db_dir）
        my_wxid: 当前账号的 wxid（config.my_wxid）

    Returns:
        media_0.db 路径，找不到返回 None
    """
    base = Path(decrypted_db_dir)
    if not base.is_dir():
        return None

    # 优先用配置的 wxid 定位
    if my_wxid:
        candidate = base / my_wxid / "media_0.db"
        if candidate.is_file():
            return candidate

    # 回退：扫描所有子目录
    for account_dir in base.iterdir():
        if not account_dir.is_dir():
            continue
        candidate = account_dir / "media_0.db"
        if candidate.is_file():
            return candidate

    return None


def create_transcriber_from_config(config) -> Optional[VoiceTranscriber]:
    """从全局配置创建 VoiceTranscriber。

    Args:
        config: engine.config.Config 实例

    Returns:
        VoiceTranscriber 实例，若 media_0.db 不存在返回 None
    """
    media_db_path = find_media_db_path(
        config.weflow.decrypted_db_dir,
        config.my_wxid,
    )
    if not media_db_path:
        logger.warning(
            f"未找到 media_0.db（decrypted_db_dir={config.weflow.decrypted_db_dir}, "
            f"wxid={config.my_wxid}），语音识别功能不可用"
        )
        return None

    return VoiceTranscriber(media_db_path=media_db_path)
