"""异步转写管理器。

在 person_sync 完成后触发，后台线程处理新同步消息的语音/图片转写。

设计目标：
1. 不阻塞同步主流程（async 模式）
2. 转写完成后 UPDATE 数据库，下次同步不覆盖 voice_text/image_text 字段
3. 支持 async/sync/off 三种模式开关

依赖：
- VoiceTranscriber（faster-whisper + pysilk）
- ImageTranscriber（BLIP + PaddleOCR）

工作流程：
    sync_person 完成
    → 查询本次同步的未转写消息（type=34 voice_text IS NULL / type=3 image_text IS NULL）
    → 入队到 AsyncTranscriber
    → worker 线程串行处理（避免 CPU 过载）
    → 调用 transcribe_voice_messages / transcribe_image_messages
    → UPDATE messages.voice_text / image_text

幂等性：
- 失败的消息标记为空字符串（FAILED_MARKER），不会反复重试
- 同步流程不会覆盖 voice_text/image_text 字段（upsert_message 的 UPDATE SET 不包含这两个字段）
"""
import logging
import sqlite3
import threading
from pathlib import Path
from typing import Literal, Optional

from engine.importers.db_init import connect_db

logger = logging.getLogger(__name__)

TranscribeMode = Literal["async", "sync", "off"]

# 队列最大长度（超过则丢弃，避免无限增长）
MAX_QUEUE_SIZE = 50
# 单次任务最多处理的消息数（避免一次跑太久）
MAX_MESSAGES_PER_TASK = 100


class AsyncTranscriber:
    """异步转写管理器（单例）。

    使用方式：
        transcriber = AsyncTranscriber.get_instance()
        transcriber.enqueue(
            db_path=Path("data/raw/core.db"),
            conv_id="wxid_xxx",
            decrypted_db_dir=Path("..."),
            my_wxid="wxid_yyy",
            wcd_base_url="http://127.0.0.1:10392",
            wcd_token="",
        )

    工作线程：
    - daemon=True，进程退出时自动结束
    - 单 worker 串行处理（避免 CPU 过载）
    - 失败任务不重试（idempotent 设计，下次 sync_person 会重新触发）
    """

    _instance: Optional["AsyncTranscriber"] = None
    _lock = threading.Lock()

    def __init__(self):
        self._queue: list[dict] = []
        self._queue_lock = threading.Lock()
        self._worker: Optional[threading.Thread] = None
        # 复用 transcriber 实例（模型加载耗时）
        self._voice_transcriber = None
        self._image_transcriber = None
        self._voice_init_failed = False
        self._image_init_failed = False
        # 统计
        self._total_processed = 0
        self._total_success = 0
        self._total_failed = 0

    @classmethod
    def get_instance(cls) -> "AsyncTranscriber":
        """获取全局单例。"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def enqueue(
        self,
        db_path: Path,
        conv_id: str,
        decrypted_db_dir: Path,
        my_wxid: str,
        wcd_base_url: str = "",
        wcd_token: str = "",
    ) -> int:
        """入队转写任务。

        查询 conv_id 下未转写的语音/图片消息，入队异步转写。

        Args:
            db_path: core.db 路径
            conv_id: 会话 ID
            decrypted_db_dir: WCD 解密数据库目录（用于定位 media_0.db）
            my_wxid: 当前账号 wxid
            wcd_base_url: WCD API 地址（图片转写需要）
            wcd_token: WCD API token

        Returns:
            入队的消息数量
        """
        # 查询未转写的语音/图片消息
        try:
            db = connect_db(db_path)
            try:
                cursor = db.execute(
                    """
                    SELECT id, type FROM messages
                    WHERE conversation_id = ?
                    AND (
                        (type = 34 AND voice_text IS NULL)
                        OR (type = 3 AND image_text IS NULL)
                    )
                    ORDER BY timestamp DESC
                    LIMIT ?
                    """,
                    (conv_id, MAX_MESSAGES_PER_TASK),
                )
                msg_ids = []
                msg_types = []
                for row in cursor:
                    msg_ids.append(str(row[0]))
                    msg_types.append(int(row[1]))
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"查询未转写消息失败 (conv={conv_id}): {e}")
            return 0

        if not msg_ids:
            return 0

        with self._queue_lock:
            if len(self._queue) >= MAX_QUEUE_SIZE:
                logger.warning(
                    f"转写队列已满（{len(self._queue)}/{MAX_QUEUE_SIZE}），"
                    f"丢弃 conv={conv_id} 的 {len(msg_ids)} 条消息"
                )
                return 0
            self._queue.append({
                "db_path": db_path,
                "conv_id": conv_id,
                "msg_ids": msg_ids,
                "msg_types": msg_types,
                "decrypted_db_dir": decrypted_db_dir,
                "my_wxid": my_wxid,
                "wcd_base_url": wcd_base_url,
                "wcd_token": wcd_token,
            })

        logger.info(
            f"已入队 {len(msg_ids)} 条消息进行异步转写 "
            f"(conv={conv_id}, 语音={sum(1 for t in msg_types if t == 34)}, "
            f"图片={sum(1 for t in msg_types if t == 3)})"
        )
        self._ensure_worker()
        return len(msg_ids)

    def _ensure_worker(self):
        """确保 worker 线程在运行。"""
        if self._worker is None or not self._worker.is_alive():
            self._worker = threading.Thread(
                target=self._run,
                daemon=True,
                name="async-transcriber",
            )
            self._worker.start()
            logger.info("异步转写 worker 线程已启动")

    def _run(self):
        """worker 主循环。"""
        while True:
            with self._queue_lock:
                if not self._queue:
                    break
                task = self._queue.pop(0)

            try:
                self._process_task(task)
            except Exception as e:
                logger.error(f"转写任务失败 (conv={task.get('conv_id')}): {e}", exc_info=True)

        logger.info("异步转写 worker 线程退出（队列为空）")

    def _process_task(self, task: dict):
        """处理单个转写任务。"""
        db_path = task["db_path"]
        msg_ids = task["msg_ids"]
        msg_types = task["msg_types"]
        decrypted_db_dir = task["decrypted_db_dir"]
        my_wxid = task["my_wxid"]
        wcd_base_url = task["wcd_base_url"]
        wcd_token = task["wcd_token"]

        # 分离语音和图片 ID
        voice_ids = [mid for mid, mt in zip(msg_ids, msg_types) if mt == 34]
        image_ids = [mid for mid, mt in zip(msg_ids, msg_types) if mt == 3]

        db = connect_db(db_path)
        try:
            if voice_ids:
                self._transcribe_voices(db, voice_ids, decrypted_db_dir, my_wxid)
                db.commit()

            if image_ids:
                self._transcribe_images(db, image_ids, wcd_base_url, wcd_token)
                db.commit()
        finally:
            db.close()

    def _transcribe_voices(
        self,
        db: sqlite3.Connection,
        msg_ids: list[str],
        decrypted_db_dir: Path,
        my_wxid: str,
    ):
        """语音转写。"""
        if not my_wxid:
            logger.warning("未配置 my_wxid，跳过语音转写")
            return

        if self._voice_transcriber is None and not self._voice_init_failed:
            try:
                from engine.importers.voice_transcriber import (
                    VoiceTranscriber,
                    find_media_db_path,
                )
                media_db_path = find_media_db_path(decrypted_db_dir, my_wxid)
                if not media_db_path:
                    logger.warning(f"未找到 media_0.db（decrypted_db_dir={decrypted_db_dir}）")
                    self._voice_init_failed = True
                    return
                self._voice_transcriber = VoiceTranscriber(
                    media_db_path=media_db_path,
                    model_size="small",
                    device="cpu",
                    compute_type="int8",
                )
                logger.info(f"VoiceTranscriber 初始化成功: {media_db_path}")
            except Exception as e:
                logger.error(f"初始化 VoiceTranscriber 失败: {e}", exc_info=True)
                self._voice_init_failed = True
                return

        if self._voice_transcriber is None:
            return

        # 逐条转写（复用已加载的模型）
        success = 0
        failed = 0
        from engine.importers.voice_transcriber import FAILED_MARKER, SOURCE_PREFIX
        for i, msg_id in enumerate(msg_ids, 1):
            try:
                text = self._voice_transcriber.transcribe(msg_id)
                if text:
                    db.execute(
                        "UPDATE messages SET voice_text=? WHERE id=?",
                        (text, msg_id),
                    )
                    success += 1
                    logger.info(f"  语音 [{i}/{len(msg_ids)}] {msg_id}: {text[:60]}")
                else:
                    db.execute(
                        "UPDATE messages SET voice_text=? WHERE id=?",
                        (FAILED_MARKER, msg_id),
                    )
                    failed += 1
                    logger.info(f"  语音 [{i}/{len(msg_ids)}] {msg_id}: <识别失败>")
            except Exception as e:
                logger.warning(f"  语音 {msg_id} 转写异常: {e}")
                failed += 1

            # 每 10 条提交一次
            if i % 10 == 0:
                db.commit()

        db.commit()
        self._total_processed += len(msg_ids)
        self._total_success += success
        self._total_failed += failed
        logger.info(f"语音转写完成: 成功 {success}/{len(msg_ids)}，失败 {failed}")

    def _transcribe_images(
        self,
        db: sqlite3.Connection,
        msg_ids: list[str],
        wcd_base_url: str,
        wcd_token: str,
    ):
        """图片转写。"""
        if not wcd_base_url:
            logger.warning("未配置 wcd_base_url，跳过图片转写")
            return

        if self._image_transcriber is None and not self._image_init_failed:
            try:
                from engine.importers.image_transcriber import ImageTranscriber
                self._image_transcriber = ImageTranscriber(
                    wcd_base_url=wcd_base_url,
                    wcd_account="",  # 将在每条消息时用 talker 查询
                    token=wcd_token,
                    use_ocr=True,
                    ocr_model="mobile",
                )
                logger.info("ImageTranscriber 初始化成功")
            except Exception as e:
                logger.error(f"初始化 ImageTranscriber 失败: {e}", exc_info=True)
                self._image_init_failed = True
                return

        if self._image_transcriber is None:
            return

        # 逐条转写
        success = 0
        failed = 0
        from engine.importers.image_transcriber import (
            FAILED_MARKER, ImageTranscriber as _IT,
        )
        for i, msg_id in enumerate(msg_ids, 1):
            try:
                row = db.execute(
                    "SELECT raw_content, conversation_id FROM messages WHERE id=?",
                    (msg_id,),
                ).fetchone()
                if not row:
                    continue
                raw_content = row[0] or ""
                talker = row[1]

                md5 = _IT._parse_md5_from_xml(raw_content)
                if not md5:
                    db.execute(
                        "UPDATE messages SET image_text=? WHERE id=?",
                        (FAILED_MARKER, msg_id),
                    )
                    failed += 1
                    logger.info(f"  图片 [{i}/{len(msg_ids)}] {msg_id}: <无 md5，跳过>")
                    continue

                text = self._image_transcriber.transcribe(md5, talker)
                if text:
                    db.execute(
                        "UPDATE messages SET image_text=? WHERE id=?",
                        (text, msg_id),
                    )
                    success += 1
                    logger.info(f"  图片 [{i}/{len(msg_ids)}] {msg_id}: {text[:60]}")
                else:
                    db.execute(
                        "UPDATE messages SET image_text=? WHERE id=?",
                        (FAILED_MARKER, msg_id),
                    )
                    failed += 1
                    logger.info(f"  图片 [{i}/{len(msg_ids)}] {msg_id}: <识别失败>")
            except Exception as e:
                logger.warning(f"  图片 {msg_id} 转写异常: {e}")
                failed += 1

            # 每 5 条提交一次（图片转写慢）
            if i % 5 == 0:
                db.commit()

        db.commit()
        self._total_processed += len(msg_ids)
        self._total_success += success
        self._total_failed += failed
        logger.info(f"图片转写完成: 成功 {success}/{len(msg_ids)}，失败 {failed}")

    def get_status(self) -> dict:
        """获取转写器状态。"""
        with self._queue_lock:
            queue_size = len(self._queue)
            worker_alive = self._worker is not None and self._worker.is_alive()
        return {
            "queue_size": queue_size,
            "worker_alive": worker_alive,
            "voice_transcriber_ready": self._voice_transcriber is not None,
            "image_transcriber_ready": self._image_transcriber is not None,
            "voice_init_failed": self._voice_init_failed,
            "image_init_failed": self._image_init_failed,
            "total_processed": self._total_processed,
            "total_success": self._total_success,
            "total_failed": self._total_failed,
        }


def trigger_transcription(
    db_path: Path,
    conv_id: str,
    config,
    mode: TranscribeMode = "async",
) -> dict:
    """触发转写（sync_person 完成后调用）。

    Args:
        db_path: core.db 路径
        conv_id: 会话 ID
        config: engine.config.Config 实例
        mode: 转写模式
            - "async": 异步转写（默认，不阻塞）
            - "sync": 同步转写（阻塞直到完成）
            - "off": 不转写

    Returns:
        dict 含 mode/queued/sync_result 字段
    """
    if mode == "off":
        return {"mode": "off", "queued": 0}

    decrypted_db_dir = Path(config.weflow.decrypted_db_dir) if config.weflow.decrypted_db_dir else None
    if decrypted_db_dir is None:
        logger.warning("未配置 decrypted_db_dir，无法转写")
        return {"mode": mode, "queued": 0, "error": "未配置 decrypted_db_dir"}

    if mode == "async":
        transcriber = AsyncTranscriber.get_instance()
        queued = transcriber.enqueue(
            db_path=db_path,
            conv_id=conv_id,
            decrypted_db_dir=decrypted_db_dir,
            my_wxid=config.my_wxid or "",
            wcd_base_url=config.weflow.base_url if config.weflow.backend == "wcd" else "",
            wcd_token=config.weflow.token,
        )
        return {"mode": "async", "queued": queued}

    if mode == "sync":
        # 同步执行：直接调用批量转写函数
        return _sync_transcribe(db_path, conv_id, config)

    return {"mode": mode, "queued": 0, "error": f"未知 mode: {mode}"}


def _sync_transcribe(
    db_path: Path,
    conv_id: str,
    config,
) -> dict:
    """同步转写（阻塞直到完成）。"""
    import time as _time

    decrypted_db_dir = Path(config.weflow.decrypted_db_dir)
    t0 = _time.time()

    # 语音转写
    voice_success = 0
    voice_failed = 0
    if config.my_wxid:
        try:
            from engine.importers.voice_transcriber import (
                VoiceTranscriber,
                transcribe_voice_messages,
                find_media_db_path,
            )
            media_db_path = find_media_db_path(decrypted_db_dir, config.my_wxid)
            if media_db_path:
                db = connect_db(db_path)
                try:
                    transcriber = VoiceTranscriber(
                        media_db_path=media_db_path,
                        model_size="small",
                        device="cpu",
                        compute_type="int8",
                    )
                    voice_success, voice_failed = transcribe_voice_messages(
                        db, transcriber,
                        limit=MAX_MESSAGES_PER_TASK,
                        session_id=conv_id,
                        days_back=0,  # 不限时间（已经按 conv_id 过滤）
                        private_only=False,
                    )
                    transcriber.close()
                finally:
                    db.close()
        except Exception as e:
            logger.error(f"同步语音转写失败: {e}", exc_info=True)

    # 图片转写
    image_success = 0
    image_failed = 0
    if config.weflow.backend == "wcd":
        try:
            from engine.importers.image_transcriber import (
                ImageTranscriber,
                transcribe_image_messages,
                create_transcriber_from_config,
            )
            transcriber = create_transcriber_from_config(config)
            if transcriber:
                db = connect_db(db_path)
                try:
                    image_success, image_failed = transcribe_image_messages(
                        db, transcriber,
                        limit=MAX_MESSAGES_PER_TASK,
                        session_id=conv_id,
                        days_back=0,
                        private_only=False,
                    )
                    transcriber.close()
                finally:
                    db.close()
        except Exception as e:
            logger.error(f"同步图片转写失败: {e}", exc_info=True)

    elapsed = _time.time() - t0
    return {
        "mode": "sync",
        "voice_success": voice_success,
        "voice_failed": voice_failed,
        "image_success": image_success,
        "image_failed": image_failed,
        "elapsed_seconds": round(elapsed, 1),
    }
