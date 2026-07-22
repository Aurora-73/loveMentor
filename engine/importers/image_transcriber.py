"""图片消息转文字模块。

从 WCD API 下载图片（用 raw_content 中的 md5 + talker 作为参数），
**BLIP 多模态模型 + PaddleOCR 智能组合**生成图片描述。

依赖：
- transformers（HuggingFace Transformers）
- torch（PyTorch）
- Pillow（PIL，图片处理）
- paddleocr（中文 OCR，3.6.0+）

数据流：
    messages.raw_content (XML 含 md5)
    → WCD API /api/chat/media/image?md5=xxx&username=talker
    → 图片二进制
    → 并行/串行调用 BLIP（实物描述）+ OCR（文字提取）
    → 智能组合结果：
        - BLIP 有描述 + OCR 无文字 → 照片：用 BLIP 描述
        - BLIP 描述泛化（"a photo of a computer screen"等）+ OCR 有文字 → 截图：用 OCR 文字
        - BLIP 有描述 + OCR 有文字 → meme/混合：组合描述
        - BLIP 无描述 + OCR 有文字 → 截图：用 OCR 文字
        - BLIP 无描述 + OCR 无文字 → 失败
    → 加 [图片描述] 前缀写入 messages.image_text

关联键：messages.id (server_id) + messages.conversation_id (talker)

为什么用 BLIP 而不是 Qwen2-VL：
    Qwen2-VL 的 safetensors 权重在 Python 3.13 + Windows 上加载时
    触发 0xC0000005 访问冲突（safetensors native 库 bug）。
    BLIP-base 提供 .bin 格式权重（use_safetensors=False），
    可绕过该问题，且模型体积小（223M 参数，约 1GB）。
    BLIP 输出英文，通过 opus-mt-en-zh 翻译为中文。

为什么加 OCR：
    BLIP 对截图/表情包/meme 类图片描述不准（如"黑色背景的计算机屏幕"），
    但这类图片通常包含关键文字信息。PaddleOCR 提取文字作为补充，
    智能组合后能覆盖所有图片类型。

PaddleOCR 3.6.0 + Python 3.13 注意事项：
    - 必须传 enable_mkldnn=False，否则 OneDNN 触发 NotImplementedError
    - 使用 predict() 方法（旧 ocr() 已弃用）
    - use_textline_orientation 替代 use_angle_cls
"""
import io
import logging
import re
import sqlite3
import time
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
# 用 __FAILED__ 而非空字符串，可区分"识别失败"和"未识别"
# chat.py 的 extract_display_content 会检测此标记并回退为 [图片] 占位
FAILED_MARKER = "__FAILED__"
# 来源标记前缀（用户要求：图片和语音转成的文字需要特殊标记来源）
SOURCE_PREFIX = "[图片描述] "
# 图片下载超时（秒）
IMAGE_DOWNLOAD_TIMEOUT = 30
# 单条图片最大字节数（10MB，超过则跳过避免内存爆掉）
MAX_IMAGE_BYTES = 10 * 1024 * 1024
# 下载重试次数（网络错误时指数退避重试）
IMAGE_DOWNLOAD_RETRIES = 3
# 图片缓存目录（按 md5 缓存，避免重复下载）
try:
    from engine.config import CACHE_DIR
    IMAGE_CACHE_DIR = CACHE_DIR / "images"
except ImportError:
    IMAGE_CACHE_DIR = Path("data/cache/images")

# ── OCR 配置 ──
# OCR 置信度阈值：低于此值的文字行被视为噪声丢弃
OCR_CONFIDENCE_THRESHOLD = 0.7
# OCR 提取的最大文字行数（避免过长描述）
OCR_MAX_LINES = 10
# OCR 单行最大字符数（避免长文本）
OCR_MAX_CHARS_PER_LINE = 80
# OCR 总文字最大字符数
OCR_MAX_TOTAL_CHARS = 300

# ── BLIP 描述泛化关键词 ──
# 当 BLIP 输出包含这些词时，说明它没真正理解图片内容（通常是截图/文字类）
# 此时若 OCR 有文字，应优先用 OCR 结果
# 包含英文（BLIP 原始输出）和中文（翻译后输出）两种关键词
GENERIC_BLIP_PATTERNS = [
    # 英文（BLIP 原始输出）
    "computer screen",
    "monitor",
    "black background",
    "white background",
    "black screen",
    "white screen",
    "close up of a screen",
    "a screen with",
    "a photo of a screen",
    "a photo of a tv",
    "a television",
    "text on a",
    "a piece of paper",
    "a book",
    "a page of",
    # 中文（翻译后输出）
    "计算机屏幕",
    "电脑屏幕",
    "黑白文字",
    "白背景",
    "黑背景",
    "白色背景",
    "黑色背景",
    "白纸",
    "黑纸",
    "屏幕",
    "电视",
    "显示器",
    "一张纸",
    "一页纸",
]


def _is_generic_blip_description(text: str) -> bool:
    """判断 BLIP 描述是否泛化（未真正理解图片内容）。

    Args:
        text: BLIP 输出的描述（英文或已翻译的中文）

    Returns:
        True 如果描述泛化，应优先用 OCR
    """
    text_lower = text.lower()
    for pattern in GENERIC_BLIP_PATTERNS:
        if pattern in text_lower:
            return True
    return False


def _truncate_ocr_text(lines: list[str]) -> str:
    """截断 OCR 文字到合理长度。

    Args:
        lines: OCR 识别到的文字行列表

    Returns:
        截断后的文字（用空格分隔）
    """
    truncated_lines = []
    total_chars = 0
    for line in lines[:OCR_MAX_LINES]:
        line = line.strip()
        if not line:
            continue
        if len(line) > OCR_MAX_CHARS_PER_LINE:
            line = line[:OCR_MAX_CHARS_PER_LINE] + "..."
        if total_chars + len(line) > OCR_MAX_TOTAL_CHARS:
            remaining = OCR_MAX_TOTAL_CHARS - total_chars
            if remaining > 10:
                truncated_lines.append(line[:remaining] + "...")
            break
        truncated_lines.append(line)
        total_chars += len(line) + 1  # +1 for separator
    return " ".join(truncated_lines)


class ImageTranscriber:
    """图片转文字器。

    首次调用 transcribe() 时加载 BLIP + OCR 模型（约 30s-3min，取决于网络）。
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
        use_ocr: bool = True,
        ocr_model: str = "mobile",
    ):
        self.wcd_base_url = wcd_base_url.rstrip("/")
        self.wcd_account = wcd_account
        self.model_name = model_name
        self.device = device
        self.prompt = prompt
        self.token = token
        self.translator_model = translator_model
        self.use_ocr = use_ocr
        # OCR 模型选择：mobile（PP-OCRv5_mobile，快 2.5 倍）或 server（PP-OCRv5_server，精度略高）
        self.ocr_model = ocr_model
        self._model = None            # 延迟加载 BLIP 模型
        self._processor = None        # 延迟加载 BLIP processor
        self._translator = None       # 延迟加载翻译 pipeline
        self._ocr = None              # 延迟加载 PaddleOCR

    # ── 模型加载（延迟）──

    def _load_model(self):
        """延迟加载 PaddleOCR + BLIP 模型 + 翻译 pipeline。

        加载顺序：PaddleOCR → BLIP → 翻译 pipeline
        原因：PaddleOCR 的 paddle native 库与 torch 的 native 库在 Python 3.13 上
        同时加载时会触发 0xC0000005 访问冲突。先加载 PaddleOCR，让 paddle 完成所有
        native 库初始化，再加载 torch/transformers，可避免冲突。
        """
        if self._model is not None:
            return

        # 1. 先加载 PaddleOCR（paddle native 库先初始化）
        if self.use_ocr:
            ocr_model_name = "server" if self.ocr_model == "server" else "mobile"
            logger.info(f"加载 PaddleOCR（中文 OCR，模型={ocr_model_name}）")
            try:
                from paddleocr import PaddleOCR
                # PaddleOCR 3.x API：关闭 OneDNN 避免 Python 3.13 兼容性问题
                # mobile 模型（PP-OCRv5_mobile）比 server 快 2.5 倍，精度相似
                if self.ocr_model == "server":
                    ocr_kwargs = {}  # 默认 server 模型
                else:
                    ocr_kwargs = {
                        "text_detection_model_name": "PP-OCRv5_mobile_det",
                        "text_recognition_model_name": "PP-OCRv5_mobile_rec",
                    }
                self._ocr = PaddleOCR(
                    use_textline_orientation=True,
                    lang='ch',
                    enable_mkldnn=False,
                    **ocr_kwargs,
                )
                logger.info(f"PaddleOCR 加载成功（模型={ocr_model_name}）")
            except Exception as e:
                logger.warning(f"PaddleOCR 加载失败（OCR 不可用）: {e}")
                self._ocr = None

        # 2. 后加载 BLIP + 翻译 pipeline（torch native 库后初始化）
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
        self._ocr = None

    # ── 图片下载 ──

    def _download_image(self, md5: str, talker: str) -> Optional[bytes]:
        """通过 WCD API 下载图片（带 md5 缓存 + 网络重试）。

        优化：
        - 缓存：按 md5 缓存到 IMAGE_CACHE_DIR，避免同一图片重复下载
        - 重试：网络错误时指数退避重试（最多 IMAGE_DOWNLOAD_RETRIES 次）

        WCD API: GET /api/chat/media/image?md5=xxx&account=xxx&username=talker
        必须传 username（talker），否则 hardlink.db 无法定位文件（微信 4.x 用 md5(talker) 作为目录名）。

        Args:
            md5: 图片的 MD5（从 raw_content XML 解析）
            talker: 会话对方的 wxid（用于定位 msg/attach/{md5(talker)}/... ）

        Returns:
            图片二进制数据，失败返回 None
        """
        # 1. 检查缓存
        cache_path = IMAGE_CACHE_DIR / f"{md5}.bin"
        if cache_path.exists():
            try:
                data = cache_path.read_bytes()
                if data and len(data) <= MAX_IMAGE_BYTES:
                    logger.debug(f"图片缓存命中 md5={md5}")
                    return data
                # 缓存文件异常（空或过大），删除后重新下载
                cache_path.unlink(missing_ok=True)
            except Exception:
                pass

        # 2. 网络下载（带重试）
        params = {
            "md5": md5,
            "account": self.wcd_account,
            "username": talker,
        }
        url = f"{self.wcd_base_url}/api/chat/media/image?" + urllib.parse.urlencode(params)

        headers: dict[str, str] = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        last_error = None
        for attempt in range(IMAGE_DOWNLOAD_RETRIES):
            try:
                req = urllib.request.Request(url, headers=headers, method="GET")
                with urllib.request.urlopen(req, timeout=IMAGE_DOWNLOAD_TIMEOUT) as resp:
                    if resp.status != 200:
                        last_error = f"HTTP {resp.status}"
                        if attempt < IMAGE_DOWNLOAD_RETRIES - 1:
                            time.sleep(2 ** attempt)  # 指数退避：1s, 2s
                            continue
                        logger.warning(f"下载图片失败 md5={md5}: {last_error}")
                        return None
                    data = resp.read()
                    if len(data) > MAX_IMAGE_BYTES:
                        logger.warning(
                            f"图片过大 md5={md5}: {len(data)} bytes > {MAX_IMAGE_BYTES}, 跳过"
                        )
                        return None
                    # 3. 写入缓存
                    try:
                        IMAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
                        cache_path.write_bytes(data)
                    except Exception as e:
                        logger.debug(f"写入图片缓存失败 md5={md5}: {e}")
                    return data
            except Exception as e:
                last_error = str(e)
                if attempt < IMAGE_DOWNLOAD_RETRIES - 1:
                    wait = 2 ** attempt  # 指数退避：1s, 2s
                    logger.debug(f"下载图片重试 md5={md5} (第{attempt+1}次): {e}, {wait}s 后重试")
                    time.sleep(wait)
                else:
                    logger.warning(f"下载图片失败 md5={md5} (重试{IMAGE_DOWNLOAD_RETRIES}次): {e}")
                    return None
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

    # ── BLIP 多模态识别 ──

    def _describe_image_blip(self, image_bytes: bytes) -> Optional[str]:
        """用 BLIP 生成英文描述，再用翻译 pipeline 转为中文。

        Args:
            image_bytes: 图片二进制数据

        Returns:
            中文描述（已 strip），失败返回 None
        """
        try:
            import torch
            from PIL import Image

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
            logger.warning(f"BLIP 图片描述生成失败: {e}")
            return None

    # ── OCR 文字提取 ──

    # OCR 处理的最大图片尺寸（超过则等比缩小，避免 PaddleOCR 大图崩溃）
    # 1024px 是安全值：2048px 在某些大图上会触发 0xC0000005 崩溃
    OCR_MAX_IMAGE_DIMENSION = 1024

    def _extract_text_ocr(self, image_bytes: bytes) -> Optional[str]:
        """用 PaddleOCR 提取图片中的文字。

        Args:
            image_bytes: 图片二进制数据

        Returns:
            提取到的文字（已截断），无文字或失败返回 None
        """
        if not self._ocr:
            return None

        try:
            import numpy as np
            from PIL import Image

            # 字节流 → PIL Image → numpy array（PaddleOCR 3.x 接受 numpy）
            image = Image.open(io.BytesIO(image_bytes)).convert("RGB")

            # 图片预处理：限制最大尺寸（避免 PaddleOCR 处理大图时崩溃）
            max_dim = max(image.width, image.height)
            if max_dim > self.OCR_MAX_IMAGE_DIMENSION:
                scale = self.OCR_MAX_IMAGE_DIMENSION / max_dim
                new_size = (int(image.width * scale), int(image.height * scale))
                image = image.resize(new_size, Image.LANCZOS)
                logger.debug(
                    f"OCR 预处理：图片缩小 {image.size} (原 {max_dim}px > {self.OCR_MAX_IMAGE_DIMENSION}px)"
                )

            img_array = np.array(image)

            # PaddleOCR 3.x：predict 返回 list of OCRResult
            results = self._ocr.predict(img_array)
            if not results:
                return None

            lines = []
            for res in results:
                # OCRResult 是 dict-like，有 rec_texts 和 rec_scores
                if isinstance(res, dict) or hasattr(res, 'get'):
                    texts = res.get('rec_texts', []) if hasattr(res, 'get') else getattr(res, 'rec_texts', [])
                    scores = res.get('rec_scores', []) if hasattr(res, 'get') else getattr(res, 'rec_scores', [])
                else:
                    # 直接访问属性
                    texts = getattr(res, 'rec_texts', []) or []
                    scores = getattr(res, 'rec_scores', []) or []

                for text, score in zip(texts, scores):
                    if not text or not text.strip():
                        continue
                    # 置信度过滤
                    if score < OCR_CONFIDENCE_THRESHOLD:
                        continue
                    lines.append(text.strip())

            if not lines:
                return None

            logger.debug(f"OCR 提取到 {len(lines)} 行文字: {lines[:3]}...")
            return _truncate_ocr_text(lines)
        except Exception as e:
            logger.warning(f"OCR 文字提取失败: {e}")
            return None

    # ── 智能组合 ──

    def _combine_results(
        self,
        blip_desc: Optional[str],
        ocr_text: Optional[str],
    ) -> Optional[str]:
        """智能组合 BLIP 描述和 OCR 文字。

        策略：
            1. BLIP 有描述 + OCR 无文字 → 照片：用 BLIP 描述
            2. BLIP 描述泛化 + OCR 有文字 → 截图：用 OCR 文字
            3. BLIP 有描述 + OCR 有文字 → meme/混合：组合描述
            4. BLIP 无描述 + OCR 有文字 → 截图：用 OCR 文字
            5. BLIP 无描述 + OCR 无文字 → 失败

        Args:
            blip_desc: BLIP 生成的描述（已翻译为中文），失败返回 None
            ocr_text: OCR 提取到的文字，无文字返回 None

        Returns:
            组合后的描述文字，失败返回 None
        """
        # 情况 5：都失败
        if not blip_desc and not ocr_text:
            return None

        # 情况 1：只有 BLIP 描述（照片）
        if blip_desc and not ocr_text:
            return blip_desc

        # 情况 4：只有 OCR 文字（截图，BLIP 失败）
        if not blip_desc and ocr_text:
            return f"[截图] {ocr_text}"

        # 情况 2 & 3：BLIP + OCR 都有
        # 检查 BLIP 描述是否泛化
        if _is_generic_blip_description(blip_desc):
            # 情况 2：BLIP 泛化 → 优先用 OCR
            return f"[截图] {ocr_text}"
        else:
            # 情况 3：BLIP 有效描述 + OCR 文字 → meme/混合
            return f"{blip_desc}（图中文字：{ocr_text}）"

    # ── 核心流程 ──

    def transcribe(self, md5: str, talker: str) -> Optional[str]:
        """识别单条图片消息，返回带 [图片描述] 前缀的文字。

        完整流程：
            1. 通过 WCD API 下载图片（用 md5 + talker 定位）
            2. BLIP 生成描述 + OCR 提取文字（并行/串行）
            3. 智能组合结果
            4. 加 [图片描述] 前缀

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

        # 2. 加载模型（延迟）
        self._load_model()

        # 3. BLIP 生成描述
        blip_desc = self._describe_image_blip(image_bytes)

        # 4. OCR 提取文字（可选）
        ocr_text = None
        if self.use_ocr and self._ocr is not None:
            ocr_text = self._extract_text_ocr(image_bytes)

        # 5. 智能组合
        description = self._combine_results(blip_desc, ocr_text)
        if not description:
            return None

        # 6. 加来源前缀
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

    识别失败的消息会被标记为 __FAILED__（避免反复重试）。
    旧的空字符串标记也会被重新处理（自动迁移到 __FAILED__）。
    如需重试失败的消息，可手动执行：
        UPDATE messages SET image_text=NULL WHERE type=3 AND image_text='__FAILED__'

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

    # 构建查询条件：未识别 + 旧的空字符串标记（自动迁移到 __FAILED__）
    conditions = ["m.type=3", "(m.image_text IS NULL OR m.image_text = '')"]
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
        use_ocr=getattr(config.weflow, 'image_ocr', True),
        ocr_model=getattr(config.weflow, 'image_ocr_model', 'mobile'),
    )
