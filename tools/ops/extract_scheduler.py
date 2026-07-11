"""
流水线调度器：每小时运行一次 extract_audio.py。
如果上一轮还没跑完，则等待它完成后立即开始下一轮。

用法：python extract_scheduler.py
建议在后台运行：python extract_scheduler.py &
"""

import subprocess
import sys
import time
from pathlib import Path

EXTRACT_SCRIPT = Path(__file__).parent / "extract_audio.py"
INTERVAL_SECONDS = 7200  # 2 小时


def run_extract() -> bool:
    """运行 extract_audio.py，返回是否成功。"""
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 开始运行 extract_audio.py")
    sys.stdout.flush()

    proc = subprocess.run(
        [sys.executable, str(EXTRACT_SCRIPT)],
        capture_output=False,  # 实时输出到终端
    )

    ok = proc.returncode == 0
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] extract_audio.py "
          f"{'完成' if ok else f'失败 (exit={proc.returncode})'}")
    sys.stdout.flush()
    return ok


def main():
    print(f"流水线调度器启动，间隔 {INTERVAL_SECONDS}s")
    print(f"脚本: {EXTRACT_SCRIPT}")
    print(f"按 Ctrl+C 停止\n")
    sys.stdout.flush()

    round_num = 0
    while True:
        round_num += 1
        print(f"\n{'='*60}")
        print(f"第 {round_num} 轮  {time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*60}")
        sys.stdout.flush()

        t_start = time.time()
        run_extract()
        elapsed = time.time() - t_start

        # 补齐到 1 小时间隔；如果运行已超过 1 小时则不等待，立即下一轮
        wait = max(0, INTERVAL_SECONDS - elapsed)
        if wait > 0:
            print(f"本轮耗时 {elapsed:.0f}s，等待 {wait:.0f}s 后下一轮")
            sys.stdout.flush()
            time.sleep(wait)
        else:
            print(f"本轮耗时 {elapsed:.0f}s（超过 1 小时），立即开始下一轮")
            sys.stdout.flush()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n调度器已停止")
