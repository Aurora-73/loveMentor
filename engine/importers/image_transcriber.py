"""图片消息转文字模块。

从 WCD API 下载图片（用 raw_content 中的 md5 + talker 作为参数），
用 BLIP 多模态模型生成简短英文描述，并翻译为简体中文。

依赖：
- transformers（HuggingFace Transformers）
- torch（PyTorch）
- Pillow（PIL，图片处理）

数据流：
    messages.raw_content (XML 含 md5)
    → WCD API /api/chat/media/image?md5=xxx&username=talker
    → 图片二进制
    → BLIP 生成英文描述
    → 翻译为简体中文（可选，用翻译 pipeline）
    → 加 [图片描述] 前缀写入 messages.image_text

关联键：messages.id (server_id) + messages.conversation_id (talker)

为什么用 BLIP 而不是 Qwen2-VL：
    Qwen2-VL 的 safetensors 权重在 Python 3.13 + Windows 上加载时
    触发 0xC0000005 访问冲突（safetensors native 库 bug）。
    BLIP-base 提供 .bin 格式权重（use_safetensors=False），
    可绕过该问题，且模型体积小（223M 参数，约 1GB）。
    BLIP 输出英文，通过 opus-mt-en-zh 翻译为中文。
"""
import io
import logging
import re
import sqlite3
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── 默认配置 ──
DEFAULT_MODEL_NAME = "Salesforce/blip-image-captioning-base"
DEFAULT_DEVICE = "cpu"            # cpu/cuda
# BLIP 提示词：英文短描述（BLIP 不支持中文输出，故用英文 prompt + 翻译）
DEFAULT_PROMPT = "a photo of"
# 翻译模型（Helsinki-NLP opus-mt，体积小、纯 PyTorch .bin 格式）
DEFAULT_TRANSLATOR_MODEL = "Helsinki-NLP/opus-mt-en-zh"
# 标记识别失败的占位符（避免反复重试失败的消息）
FAILED_MARKER = ""
# 来源标记前缀（用户要求：图片和语音转成的文字需要特殊标记来源）
SOURCE_PREFIX = "[图片描述] "
# 图片下载超时（秒）
IMAGE_DOWNLOAD_TIMEOUT = 30
# 单条图片最大字节数（10MB，超过则跳过避免内存爆掉）
MAX_IMAGE_BYTES = 10 * 1024 * 1024


class ImageTranscriber:
    """图片转文字器。

    首次调用 transcribe() 时加载 BLIP 模型 + 翻译模型（约 30s-3min，取决于网络）。
    后续调用复用模型实例。

    Example:
        >>> transcriber = ImageTranscriber(
        ...     wcd_base_url="http://127.0.0.1:10392",
        ...     wcd_account="wxid_xxx",
        ... )
        >>> text = transcriber.transcribe(md5="abc...", talker="wxid_yyy")
        >>> print(text)
        "[图片描述] 一只狗"
    """

    def __init__(
        self,
        wcd_base_url: str,
        wcd_account: str,
        model_name: str = DEFAULT_MODEL_NAME,
        device: str = DEFAULT_DEVICE,
        prompt: str = DEFAULT_PROMPT,
        token: str = "",
        translator_model: str = DEFAULT_TRANSLATOR_MODEL,
    ):
        self.wcd_base_url = wcd_base_url.rstrip("/")
        self.wcd_account = wcd_account
        self.model_name = model_name
        self.device = device
        self.prompt = prompt
        self.token = token
        self.translator_model = translator_model
        self._model = None            # 延迟加载 BLIP 模型
        self._processor = None        # 延迟加载 BLIP processor
        self._translator = None       # 延迟加载翻译 pipeline

    # ── 模型加载（延迟）──

    def _load_model(self):
        """延迟加载 BLIP 模型 + 翻译 pipeline。"""
        if self._model is not None:
            return
        import torch
        from transformers import (
            BlipForConditionalGeneration,
            BlipProcessor,
            pipeline,
        )
        logger.info(f"加载 BLIP 模型: {self.model_name} (device={self.device})")
        # CPU 用 float32；CUDA 用 float16 节省显存
        torch_dtype = torch.float32 if self.device == "cpu" else torch.float16
        self._processor = BlipProcessor.from_pretrained(self.model_name)
        # use_safetensors=False：避开 safetensors 在 Python 3.13 上的 native bug
        self._model = BlipForConditionalGeneration.from_pretrained(
            self.model_name,
            use_safetensors=False,
            torch_dtype=torch_dtype,
        )
        if self.device == "cpu":
            self._model = self._model.to("cpu")

        # 加载翻译 pipeline（英文→中文）
        logger.info(f"加载翻译模型: {self.translator_model}")
        self._translator = pipeline(
            "translation_en_to_zh",
            model=self.translator_model,
            tokenizer=self.translator_model,
            device=-1 if self.device == "cpu" else 0,
        )

    def close(self):
        """释放资源。"""
        self._model = None
        self._processor = None
        self._translator = None

    # ── 图片下载 ──

    def _download_image(self, md5: str, talker: str) -> Optional[bytes]:
        """通过 WCD API 下载图片。

        WCD API: GET /api/chat/media/image?md5=xxx&account=xxx&username=talker
        必须传 username（talker），否则 hardlink.db 无法定位文件（微信 4.x 用 md5(talker) 作为目录名）。

        Args:
            md5: 图片的 MD5（从 raw_content XML 解析）
            talker: 会话对方的 wxid（用于定位 msg/attach/{md5(talker)}/... ）

        Returns:
            图片二进制数据，失败返回 None
        """
        params = {
            "md5": md5,
            "account": self.wcd_account,
            "username": talker,
        }
        url = f"{self.wcd_base_url}/api/chat/media/image?" + urllib.parse.urlencode(params)

        headers: dict[str, str] = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        try:
            req = urllib.request.Request(url, headers=headers, method="GET")
            with urllib.request.urlopen(req, timeout=IMAGE_DOWNLOAD_TIMEOUT) as resp:
                if resp.status != 200:
                    logger.warning(f"下载图片失败 md5={md5}: HTTP {resp.status}")
                    return None
                data = resp.read()
                if len(data) > MAX_IMAGE_BYTES:
                    logger.warning(
                        f"图片过大 md5={md5}: {len(data)} bytes > {MAX_IMAGE_BYTES}, 跳过"
                    )
                    return None
                return data
        except Exception as e:
            logger.warning(f"下载图片异常 md5={md5}: {e}")
            return None

    # ── md5 解析 ──

    @staticmethod
    def _parse_md5_from_xml(raw_content: str) -> Optional[str]:
        """从图片消息的 raw_content XML 中解析 md5 属性。

        样本：
            <msg><img ... md5="998441c7d138fc0108a9a56ecb8a92ee" .../></msg>

        Args:
            raw_content: messages.raw_content 字段

        Returns:
            md5 字符串，未找到返回 None
        """
        if not raw_content:
            return None
        match = re.search(r'md5="([a-f0-9]{32})"', raw_content, re.IGNORECASE)
        if match:
            return match.group(1).lower()
        # 兼容单引号
        match = re.search(r"md5='([a-f0-9]{32})'", raw_content, re.IGNORECASE)
        if match:
            return match.group(1).lower()
        return None

    # ── 多模态识别 ──

    def _describe_image(self, image_bytes: bytes) -> Optional[str]:
        """用 BLIP 生成英文描述，再用翻译 pipeline 转为中文。

        Args:
            image_bytes: 图片二进制数据

        Returns:
            中文描述（已 strip），失败返回 None
        """
        try:
            import torch
            from PIL import Image

            self._load_model()

            # 字节流 → PIL Image
            image = Image.open(io.BytesIO(image_bytes)).convert("RGB")

            # BLIP 处理：图片 + 英文 prompt
            # conditional image captioning（带 prompt 引导）
            inputs = self._processor(
                images=image,
                text=self.prompt,
                return_tensors="pt",
            ).to(self._model.device)

            # 生成英文描述
            with torch.no_grad():
                output_ids = self._model.generate(
                    **inputs,
                    max_new_tokens=30,    # 英文描述短，30 token 足够
                    do_sample=False,      # 贪心解码，保证可复现
                    num_beams=3,          # beam search 提升质量
                )

            # BLIP 的 generate 输出包含输入 token，需要完整 decode
            # BlipProcessor.decode 会自动处理
            en_text = self._processor.tokenizer.decode(
                output_ids[0], skip_special_tokens=True
            ).strip()

            # 移除 prompt 前缀（BLIP 输出可能包含 "a photo of" 前缀）
            if en_text.lower().startswith(self.prompt.lower()):
                en_text = en_text[len(self.prompt):].strip()

            if not en_text:
                return None

            logger.debug(f"BLIP 英文描述: {en_text}")

            # 翻译为中文
            if self._translator:
                zh_result = self._translator(en_text, max_length=60)
                zh_text = zh_result[0]["translation_text"].strip() if zh_result else ""
                return zh_text or en_text  # 翻译失败时回退到英文

            return en_text
        except Exception as e:
            logger.warning(f"图片描述生成失败: {e}")
            return None

    # ── 核心流程 ──

    def transcribe(self, md5: str, talker: str) -> Optional[str]:
        """识别单条图片消息，返回带 [图片描述] 前缀的文字。

        完整流程：
            1. 通过 WCD API 下载图片（用 md5 + talker 定位）
            2. Qwen2-VL 生成简短描述
            3. 加 [图片描述] 前缀

        Args:
            md5: 图片 MD5（从 raw_content XML 解析）
            talker: 会话对方 wxid（conversation_id）

        Returns:
            "[图片描述] xxx" 格式的文字，失败返回 None
        """
        # 1. 下载图片
        image_bytes = self._download_image(md5, talker)
        if not image_bytes:
            return None

        # 2. 多模态模型生成描述
        description = self._describe_image(image_bytes)
        if not description:
            return None

        # 3. 加来源前缀
        return f"{SOURCE_PREFIX}{description}"


# ── 批量识别 ──


def transcribe_image_messages(
    db: sqlite3.Connection,
    transcriber: ImageTranscriber,
    limit: int = 100,
    session_id: Optional[str] = None,
    verbose: bool = False,
    days_back: int = 30,
    private_only: bool = True,
) -> tuple[int, int]:
    """批量识别未识别的图片消息。

    查询 messages 表中 type=3 且 image_text IS NULL 的消息，
    逐条下载图片并生成描述，更新 image_text 字段。

    识别失败的消息会被标记为空字符串（FAILED_MARKER），避免反复重试。
    如需重试失败的消息，可手动执行：
        UPDATE messages SET image_text=NULL WHERE type=3 AND image_text=''

    Args:
        db: core.db 连接
        transcriber: ImageTranscriber 实例
        limit: 最多识别多少条（避免一次跑太久）
        session_id: 指定会话（None = 所有会话）
        verbose: 输出详细日志
        days_back: 只识别最近 N 天的消息（0 = 不限时间）
        private_only: True = 只识别私聊消息（排除群聊）

    Returns:
        (成功识别数, 失败数)
    """
    import time as _time

    # 构建查询条件
    conditions = ["m.type=3", "m.image_text IS NULL"]
    params: list = []

    # 时间过滤
    if days_back > 0:
        cutoff_ts = int(_time.time()) - days_back * 86400
        conditions.append(f"m.timestamp >= {cutoff_ts}")

    # 私聊过滤
    if private_only:
        conditions.append("c.type='private'")
    if session_id:
        conditions.append("m.conversation_id=?")
        params.append(session_id)

    where_clause = " AND ".join(conditions)
    sql = (
        f"SELECT m.id, m.conversation_id, m.raw_content "
        f"FROM messages m "
        f"JOIN conversations c ON m.conversation_id=c.id "
        f"WHERE {where_clause} "
        f"ORDER BY m.timestamp DESC LIMIT ?"
    )
    params.append(limit)

    cursor = db.execute(sql, params)
    rows = cursor.fetchall()
    if not rows:
        logger.info("没有待识别的图片消息")
        return (0, 0)

    if verbose:
        logger.info(
            f"开始识别 {len(rows)} 条图片消息"
            f"（days_back={days_back}, private_only={private_only}）..."
        )

    success = 0
    failed = 0
    for i, row in enumerate(rows, 1):
        msg_id, talker, raw_content = row
        # 解析 md5
        md5 = ImageTranscriber._parse_md5_from_xml(raw_content or "")
        if not md5:
            # raw_content 中无 md5，标记为失败
            db.execute(
                "UPDATE messages SET image_text=? WHERE id=?",
                (FAILED_MARKER, msg_id),
            )
            failed += 1
            if verbose:
                logger.info(f"  [{i}/{len(rows)}] {msg_id}: <无 md5，跳过>")
            continue

        text = transcriber.transcribe(md5, talker)
        if text:
            db.execute(
                "UPDATE messages SET image_text=? WHERE id=?",
                (text, msg_id),
            )
            success += 1
            if verbose:
                logger.info(f"  [{i}/{len(rows)}] {msg_id}: {text[:60]}")
        else:
            # 标记为识别失败（空字符串），避免反复重试
            db.execute(
                "UPDATE messages SET image_text=? WHERE id=?",
                (FAILED_MARKER, msg_id),
            )
            failed += 1
            if verbose:
                logger.info(f"  [{i}/{len(rows)}] {msg_id}: <识别失败>")

        # 每 10 条提交一次，避免长事务
        if i % 10 == 0:
            db.commit()

    db.commit()
    logger.info(f"图片识别完成: 成功 {success}/{len(rows)}，失败 {failed}")
    return (success, failed)


# ── 工厂函数 ──


def create_transcriber_from_config(config) -> Optional[ImageTranscriber]:
    """从全局配置创建 ImageTranscriber。

    Args:
        config: engine.config.Config 实例

    Returns:
        ImageTranscriber 实例，若 WCD 未配置返回 None
    """
    if config.weflow.backend != "wcd":
        logger.warning(
            f"图片转文字仅支持 WCD 后端（当前 backend={config.weflow.backend}），跳过"
        )
        return None

    if not config.my_wxid:
        logger.warning("未配置 my_wxid（WCD 需要 account 参数定位图片），图片识别不可用")
        return None

    return ImageTranscriber(
        wcd_base_url=config.weflow.base_url,
        wcd_account=config.my_wxid,
        model_name=config.weflow.image_model,
        token=config.weflow.token,
    )
