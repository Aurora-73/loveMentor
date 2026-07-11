#!/usr/bin/env python3
"""Broad structural cleanup for docs/文档."""
from __future__ import annotations
import os, shutil, sys
from pathlib import Path

BASE = Path(r"<project_root>\docs\文档")
DRY_RUN = "--dry-run" in sys.argv


def log(msg: str = "") -> None:
    print(msg)


def move_to_jiangyi(d: Path, depth: int = 1) -> int:
    """Move all txt files in d into d/讲义/. depth controls how deep to scan."""
    if not d.exists():
        return 0
    moved = 0
    jiangyi = d / "讲义"
    for item in sorted(d.iterdir()):
        if not item.is_file() or not item.name.endswith(".txt"):
            continue
        if item.parent.name == "讲义":
            continue
        if DRY_RUN:
            log(f"  讲义/ {d.name}/{item.name}")
            moved += 1
        else:
            jiangyi.mkdir(exist_ok=True)
            shutil.move(str(item), str(jiangyi / item.name))
            moved += 1
    return moved


# ── Step 1: Fix all exposed txt at second level of A* dirs ──
log("=== Step 1: 讲义/ move for exposed txt ===")
total_moved = 0
for d in sorted(BASE.iterdir()):
    if not d.is_dir() or not d.name.startswith("【A"):
        continue
    for s in sorted(d.iterdir()):
        if not s.is_dir():
            continue
        txts = [f for f in s.iterdir() if f.is_file() and f.name.endswith(".txt")]
        has_jiangyi = (s / "讲义").exists()
        if txts and not has_jiangyi:
            cnt = move_to_jiangyi(s)
            if cnt:
                total_moved += cnt

log(f"  总移动: {total_moved} files")

# ── Step 2: Handle A07 chat records ──
log("\n=== Step 2: A07 聊天记录整理 ===")
a07 = BASE / "【A07】几百套聊天案例合集"
for s in sorted(a07.iterdir()):
    if not s.is_dir():
        continue
    cnt = move_to_jiangyi(s)
    if cnt:
        log(f"  A07/{s.name}: {cnt} files -> 讲义/")

# ── Step 3: Organize A18 松散目录 ──
log("\n=== Step 3: A18 松散目录整理 ===")
a18 = BASE / "【A18】朋友圈高逼格照片＋文案"
# 整理大集合 has lots of loose files
collections = a18 / "整理大集合"
if collections.exists():
    cnt = move_to_jiangyi(collections)
    if cnt:
        log(f"  整理大集合: {cnt} files -> 讲义/")

# 最新发朋友圈配文
peiwenz = a18 / "最新发朋友圈配文"
if peiwenz.exists():
    cnt = move_to_jiangyi(peiwenz)
    if cnt:
        log(f"  最新发朋友圈配文: {cnt} files -> 讲义/")

# 朋友圈文案
wenan = a18 / "朋友圈文案"
if wenan.exists():
    cnt = move_to_jiangyi(wenan)
    if cnt:
        log(f"  朋友圈文案: {cnt} files -> 讲义/")

# 豪车+炫富视频等多个文件
haoche = a18 / "豪车+炫富视频等多个文件"
if haoche.exists():
    cnt = move_to_jiangyi(haoche)
    if cnt:
        log(f"  豪车+炫富视频: {cnt} files -> 讲义/")

# 700多小视频
video = a18 / "700多小视频"
if video.exists():
    cnt = move_to_jiangyi(video)
    if cnt:
        log(f"  700多小视频: {cnt} files -> 讲义/")

# 可复制展示面
kefuzhi = a18 / "可复制展示面"
if kefuzhi.exists():
    cnt = move_to_jiangyi(kefuzhi)
    if cnt:
        log(f"  可复制展示面: {cnt} files -> 讲义/")

# 高价值展示面
gjz = a18 / "高价值展示面"
if gjz.exists():
    cnt = move_to_jiangyi(gjz)
    if cnt:
        log(f"  高价值展示面: {cnt} files -> 讲义/")

# 5000+张分开保存
img5000 = a18 / "5000+张分开保存"
if img5000.exists():
    cnt = move_to_jiangyi(img5000)
    if cnt:
        log(f"  5000+张分开保存: {cnt} files -> 讲义/")

# 男哥《展示面三月库》 - organize by moving txt into 讲义
zhanshimian = a18 / '男哥《展示面三月库》'
if zhanshimian.exists():
    cnt = move_to_jiangyi(zhanshimian)
    if cnt:
        log(f"  男哥《展示面三月库》: {cnt} files -> 讲义/")

# 1、朋友圈打造教程
pengyouquan1 = a18 / "1、朋友圈打造教程"
if pengyouquan1.exists():
    cnt = move_to_jiangyi(pengyouquan1)
    if cnt:
        log(f"  1、朋友圈打造教程: {cnt} files -> 讲义/")

# 2、朋友圈黑科技
pengyouquan2 = a18 / "2、朋友圈黑科技"
if pengyouquan2.exists():
    cnt = move_to_jiangyi(pengyouquan2)
    if cnt:
        log(f"  2、朋友圈黑科技: {cnt} files -> 讲义/")

# 3、朋友圈打造素材
pengyouquan3 = a18 / "3、朋友圈打造素材"
if pengyouquan3.exists():
    cnt = move_to_jiangyi(pengyouquan3)
    if cnt:
        log(f"  3、朋友圈打造素材: {cnt} files -> 讲义/")

# 朋友圈打造系列
pengyouquan_series = a18 / "朋友圈打造系列"
if pengyouquan_series.exists():
    cnt = move_to_jiangyi(pengyouquan_series)
    if cnt:
        log(f"  朋友圈打造系列: {cnt} files -> 讲义/")


# ── Step 4: A17 手机摄影 ──
log("\n=== Step 4: A17 手机摄影整理 ===")
a17 = BASE / "【A17】手机摄影合集"
for s in sorted(a17.iterdir()):
    if not s.is_dir():
        continue
    cnt = move_to_jiangyi(s)
    if cnt:
        log(f"  A17/{s.name}: {cnt} files -> 讲义/")

# ── Step 5: Fix A05 私密空间 dirs ──
log("\n=== Step 5: A05 整理 ===")
a05 = BASE / "【A05】私密-空间操作课程"
for s in sorted(a05.iterdir()):
    if not s.is_dir():
        continue
    txts = [f for f in s.iterdir() if f.is_file() and f.name.endswith(".txt")]
    has_jiangyi = (s / "讲义").exists()
    if txts and not has_jiangyi:
        cnt = move_to_jiangyi(s)
        if cnt:
            log(f"  A05/{s.name}: {cnt} files -> 讲义/")

# ── Step 6: Fix A06 ──
log("\n=== Step 6: A06 整理 ===")
a06 = BASE / "【A06】女杏情感专属"
for s in sorted(a06.iterdir()):
    if not s.is_dir():
        continue
    txts = [f for f in s.iterdir() if f.is_file() and f.name.endswith(".txt")]
    has_jiangyi = (s / "讲义").exists()
    if txts and not has_jiangyi:
        cnt = move_to_jiangyi(s)
        if cnt:
            log(f"  A06/{s.name}: {cnt} files -> 讲义/")

# ── Step 7: Fix A02 ──
log("\n=== Step 7: A02 整理 ===")
a02 = BASE / "【A02】RSD国外顶尖合集"
for s in sorted(a02.iterdir()):
    if not s.is_dir():
        continue
    txts = [f for f in s.iterdir() if f.is_file() and f.name.endswith(".txt")]
    has_jiangyi = (s / "讲义").exists()
    if txts and not has_jiangyi:
        cnt = move_to_jiangyi(s)
        if cnt:
            log(f"  A02/{s.name}: {cnt} files -> 讲义/")

# ── Step 8: Fix A04 ──
log("\n=== Step 8: A04 整理 ===")
a04 = BASE / "【A04】实z视频搭讪"
for s in sorted(a04.iterdir()):
    if not s.is_dir():
        continue
    txts = [f for f in s.iterdir() if f.is_file() and f.name.endswith(".txt")]
    has_jiangyi = (s / "讲义").exists()
    if txts and not has_jiangyi:
        cnt = move_to_jiangyi(s)
        if cnt:
            log(f"  A04/{s.name}: {cnt} files -> 讲义/")

# ── Step 9: Fix 浪迹/KoLiSi/RuiEn ──
log("\n=== Step 9: 专区整理 ===")
for zname in ["浪迹情感专区", "柯李思Chris、良叔专区", "瑞恩RYAN专区"]:
    zp = BASE / zname
    for s in sorted(zp.iterdir()):
        if not s.is_dir():
            continue
        txts = [f for f in s.iterdir() if f.is_file() and f.name.endswith(".txt")]
        has_jiangyi = (s / "讲义").exists()
        if txts and not has_jiangyi:
            cnt = move_to_jiangyi(s)
            if cnt:
                log(f"  {zname}/{s.name}: {cnt} files -> 讲义/")

log("\nDone!")
if DRY_RUN:
    log("Run without --dry-run to apply")
