"""
将视频的音频流无损提取（不重新编码）、音频文件直接复制，
完全重建目录结构到 音频/ 下。

用法：python extract_audio.py
"""

import io
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

# 彻底删除，不进回收站
def _delete_forever(path: str):
    os.remove(path)

# 修复 Windows 终端 GBK 编码问题
if sys.stdout.encoding and sys.stdout.encoding.upper() != "UTF-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# === 配置 ===
SOURCE_DIRS = [
    str(Path(__file__).resolve().parents[2] / "docs" / "文档"),
]
TARGET_ROOT = str(Path(__file__).resolve().parents[2] / "docs" / "音频" / "...待上传")

# 视频扩展名（需要提取音频流）
VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".flv", ".wmv", ".webm", ".f4v", ".rmvb", ".mpg", ".mpeg",
              ".m4v", ".ts", ".mts", ".m2ts", ".3gp", ".ogv", ".vob"}

# 音频扩展名（直接复制）
AUDIO_EXTS = {".mp3", ".wav", ".flac", ".aac", ".ogg", ".wma", ".amr",
              ".m4a", ".opus", ".aiff", ".alac"}

# 需要转码的音频扩展名（原始格式兼容性差，统一转码为 m4a）
TRANSCODE_AUDIO_EXTS = {".amr"}

# 音频编解码器 → 文件扩展名映射
CODEC_EXT_MAP = {
    "aac":  ".m4a",
    "mp3":  ".mp3",
    "opus": ".opus",
    "vorbis": ".ogg",
    "flac": ".flac",
    "ac3":  ".ac3",
    "eac3": ".eac3",
    "pcm_s16le": ".wav",
    "pcm_s16be": ".wav",
    "pcm_u8":    ".wav",
    "wmav2": ".wma",
    "wmalossless": ".wma",
    "truehd": ".mka",
    "dts":  ".dts",
}

# 覆盖已有文件？
OVERWRITE = False

# moviepy 自带的完整 ffmpeg
import imageio_ffmpeg
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()


def ensure_dir(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)


def probe_audio_codec(src: Path) -> str | None:
    """从 ffmpeg -i 输出中解析第一个音频流的编码格式。"""
    try:
        # ffmpeg -i 只打印文件信息就退出（无输出文件时会报错，但信息已在 stderr 中）
        result = subprocess.run(
            [FFMPEG, "-i", str(src)],
            capture_output=True, timeout=30,
        )
        stderr = result.stderr.decode("utf-8", errors="replace")
        for line in stderr.splitlines():
            if " Audio: " in line:
                after = line.split(" Audio: ", 1)[1].strip()
                codec = after.split()[0].strip(",")
                return codec
        return None
    except Exception:
        return None


def get_audio_ext(codec: str) -> str:
    """根据音频编解码器返回推荐的文件扩展名。"""
    return CODEC_EXT_MAP.get(codec, ".mka")


def extract_audio_stream(src: Path, dst: Path) -> bool:
    """无损提取音频流（不重新编码），失败时自动回退转码。"""
    ensure_dir(dst)
    cmd = [
        FFMPEG, "-y",
        "-i", str(src),
        "-vn",              # 丢弃视频流
        "-acodec", "copy",  # 原样复制音频流
        str(dst),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=600)
        return True
    except subprocess.CalledProcessError:
        # copy 失败（常见于 RealAudio / 容器不兼容），回退转码
        print(f"  [转码] {src.name}: 无损复制失败，回退转码为 aac")
        return transcode_audio_stream(src, dst)
    except subprocess.TimeoutExpired:
        print(f"  [超时] {src.name}")
        return False


def transcode_audio_stream(src: Path, dst: Path) -> bool:
    """重新编码音频流为 AAC（兼容性最优）。"""
    ensure_dir(dst)
    # 确保输出是 .m4a
    dst_final = dst.with_suffix(".m4a") if dst.suffix not in (".m4a",) else dst
    cmd = [
        FFMPEG, "-y",
        "-i", str(src),
        "-vn",              # 丢弃视频流
        "-c:a", "aac",      # 重新编码为 AAC
        "-b:a", "128k",     # 固定码率
        "-movflags", "+faststart",
        str(dst_final),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=600)
        if dst_final != dst:
            # 调用侧期望 dst 存在，重命名
            if dst_final.exists():
                dst.unlink(missing_ok=True)
                dst_final.rename(dst)
        return True
    except subprocess.CalledProcessError as e:
        err = e.stderr.decode("utf-8", errors="replace")[-300:]
        print(f"  [转码失败] {src.name}: {err}")
        return False
    except subprocess.TimeoutExpired:
        print(f"  [转码超时] {src.name}")
        return False


def collect_files():
    """收集所有视频和音频文件。"""
    video_files, audio_files = [], []
    for sd in SOURCE_DIRS:
        sd_path = Path(sd)
        if not sd_path.is_dir():
            print(f"[跳过] 目录不存在: {sd}")
            continue
        for fpath in sd_path.rglob("*"):
            if not fpath.is_file():
                continue
            ext = fpath.suffix.lower()
            if ext in VIDEO_EXTS:
                video_files.append(fpath)
            elif ext in AUDIO_EXTS:
                audio_files.append(fpath)
    return video_files, audio_files


def relative_path(fpath: Path) -> Path:
    """返回相对于所在 SOURCE_DIR 的路径。"""
    for sd in SOURCE_DIRS:
        sd_path = Path(sd)
        try:
            return fpath.relative_to(sd_path)
        except ValueError:
            continue
    raise ValueError(f"文件不在任何源目录中: {fpath}")


def remove_source(src: Path):
    """永久删除源文件。"""
    try:
        _delete_forever(str(src))
        print(f"  [删除] {src.name}")
    except Exception as e:
        print(f"  [删除失败] {src.name}: {e}")


def process_video(fpath: Path):
    rel = relative_path(fpath)
    # 先探测音频编码格式，确定扩展名
    codec = probe_audio_codec(fpath)
    if not codec:
        print(f"  [跳过] {fpath.name}: 无音频流")
        remove_source(fpath)
        return
    ext = get_audio_ext(codec)
    dst = Path(TARGET_ROOT) / rel.with_suffix(ext)
    if dst.exists() and not OVERWRITE:
        remove_source(fpath)
        return
    print(f"  [{codec}] {fpath.name} -> {dst.name}")
    sys.stdout.flush()
    if extract_audio_stream(fpath, dst):
        if dst.exists():
            remove_source(fpath)


def process_audio(fpath: Path):
    rel = relative_path(fpath)
    ext = fpath.suffix.lower()
    if ext in TRANSCODE_AUDIO_EXTS:
        # 兼容性差的格式（如 AMR），转码为 m4a
        dst = Path(TARGET_ROOT) / rel.with_suffix(".m4a")
        if dst.exists() and not OVERWRITE:
            remove_source(fpath)
            return
        print(f"  [转码] {fpath.name} -> {dst.name}")
        sys.stdout.flush()
        if transcode_audio_stream(fpath, dst):
            if dst.exists():
                remove_source(fpath)
        return
    # 通用音频格式，直接复制
    dst = Path(TARGET_ROOT) / rel
    if dst.exists() and not OVERWRITE:
        remove_source(fpath)
        return
    ensure_dir(dst)
    shutil.copy2(fpath, dst)
    print(f"  [复制] {fpath.name}")
    sys.stdout.flush()
    if dst.exists():
        remove_source(fpath)


def main():
    t0 = time.time()

    video_files, audio_files = collect_files()
    print(f"找到 {len(video_files)} 个视频文件，{len(audio_files)} 个音频文件")

    if video_files:
        print(f"\n=== 无损提取音频流 ({len(video_files)} 个) ===")
        for i, f in enumerate(video_files, 1):
            print(f"[{i}/{len(video_files)}]", end=" ")
            process_video(f)

    if audio_files:
        print(f"\n=== 复制音频 ({len(audio_files)} 个) ===")
        for i, f in enumerate(audio_files, 1):
            print(f"[{i}/{len(audio_files)}]", end=" ")
            process_audio(f)

    elapsed = time.time() - t0
    print(f"\n完成！耗时 {elapsed:.0f} 秒")


if __name__ == "__main__":
    main()
