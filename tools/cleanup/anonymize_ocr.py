#!/usr/bin/env python3
"""
Reversibly anonymize docs/文档_ocr — rename Chinese file/dir names to opaque IDs.

Directories → d000001, d000002, …
Files      → f000001.pdf, f000002.doc, … (extensions preserved)

Usage:
    # Preview
    python tools/cleanup/anonymize_ocr.py forward --dry-run

    # Apply
    python tools/cleanup/anonymize_ocr.py forward

    # Check
    python tools/cleanup/anonymize_ocr.py status

    # Restore
    python tools/cleanup/anonymize_ocr.py reverse
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[2] / "docs" / "文档_ocr"
MAPPING_DIR = BASE_DIR.parent / ".name_mapping"
MAPPING_FILE = MAPPING_DIR / "ocr_name_map.json"

_ID_DIR_RE = re.compile(r"^d\d{6,}$")
_ID_FILE_RE = re.compile(r"^f\d{6,}$")
_ID_STEM_RE = re.compile(r"^[df]\d{6,}$")


def _is_mapped(rel: Path) -> bool:
    """Check if any component of rel is already an ID."""
    return any(_ID_STEM_RE.match(p) for p in rel.parts)


def collect(base: Path) -> dict:
    """Scan base dir, build forward/reverse mappings for all files and dirs."""
    dirs: set[str] = set()
    files: set[str] = set()
    if not base.exists():
        return {"dir_forward": {}, "dir_reverse": {}, "file_forward": {}, "file_reverse": {}}

    for path in sorted(base.rglob("*")):
        rel = path.relative_to(base)
        if _is_mapped(rel):
            continue
        if path.name == "desktop.ini":
            continue
        if path.is_dir():
            dirs.add(rel.as_posix())
        elif path.is_file():
            files.add(rel.as_posix())

    df = {k: f"d{i:06d}" for i, k in enumerate(sorted(dirs), 1)}
    ff = {k: f"f{i:06d}" for i, k in enumerate(sorted(files), 1)}
    return {
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "base": str(base),
        "dir_forward": df, "dir_reverse": {v: k for k, v in df.items()},
        "file_forward": ff, "file_reverse": {v: k for k, v in ff.items()},
    }


def load() -> dict | None:
    try:
        return json.loads(MAPPING_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def save(data: dict) -> None:
    MAPPING_DIR.mkdir(parents=True, exist_ok=True)
    MAPPING_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# ── Mapping helpers ────────────────────────────────────────────────────

def _map_dir(rel: Path, df: dict) -> Path | None:
    """Map a relative dir path through dir_forward."""
    parts = []
    for i in range(len(rel.parts)):
        key = Path(*rel.parts[:i + 1]).as_posix()
        if key not in df:
            return None
        parts.append(df[key])
    return Path(*parts) if parts else Path()


def _map_file(rel: Path, df: dict, ff: dict) -> Path | None:
    """Map a relative file path through dir_forward + file_forward."""
    parent = _map_dir(rel.parent, df)
    if parent is None:
        return None
    fid = ff.get(rel.as_posix())
    return (parent / f"{fid}{rel.suffix}") if fid else None


# ── Forward ────────────────────────────────────────────────────────────

def forward(dry_run: bool) -> int:
    data = load()
    if not data:
        data = collect(BASE_DIR)
        if not dry_run:
            save(data)

    df, ff = data["dir_forward"], data["file_forward"]
    count = 0

    # Rename files
    for orig_rel_str in sorted(ff.keys()):
        src = BASE_DIR / orig_rel_str
        if not src.exists():
            continue
        dst_rel = _map_file(Path(orig_rel_str), df, ff)
        if dst_rel is None:
            continue
        dst = BASE_DIR / dst_rel
        if not dry_run:
            dst.parent.mkdir(parents=True, exist_ok=True)
            os.replace(src, dst)
        print(f"MOVE {src}\n    -> {dst}")
        count += 1

    # Remove empty original dirs (deepest first)
    for p in sorted(BASE_DIR.rglob("*"), key=lambda x: -len(x.parts)):
        if p.is_dir() and not _ID_DIR_RE.match(p.name):
            try:
                next(p.iterdir())
            except StopIteration:
                print(f"RMDIR {p}")
                if not dry_run:
                    p.rmdir()

    print(f"\nForward: {count} files mapped")
    return count


# ── Reverse ────────────────────────────────────────────────────────────

def reverse(dry_run: bool) -> int:
    data = load()
    if not data:
        print(f"No mapping file: {MAPPING_FILE}", file=sys.stderr)
        return 0

    dr, fr = data["dir_reverse"], data["file_reverse"]
    restored = 0

    if not BASE_DIR.exists():
        return 0

    # Restore files
    for p in sorted(BASE_DIR.rglob("*")):
        if not p.is_file() or not _ID_FILE_RE.match(p.stem):
            continue
        orig_rel_str = fr.get(p.stem)
        if orig_rel_str is None:
            continue
        dst = BASE_DIR / orig_rel_str
        if dst.exists():
            continue
        if not dry_run:
            dst.parent.mkdir(parents=True, exist_ok=True)
            os.replace(p, dst)
        print(f"MOVE {p}\n    -> {dst}")
        restored += 1

    # Remove empty mapped dirs (bottom-up)
    for p in sorted(BASE_DIR.rglob("*"), key=lambda x: -len(x.parts)):
        if p.is_dir() and _ID_DIR_RE.match(p.name):
            try:
                next(p.iterdir())
            except StopIteration:
                print(f"RMDIR {p}")
                if not dry_run:
                    p.rmdir()

    print(f"\nReverse: {restored} files restored")
    return restored


# ── Status ─────────────────────────────────────────────────────────────

def status() -> None:
    data = load()
    if not data:
        print(f"No mapping file: {MAPPING_FILE}")
        return

    fr = data.get("file_reverse", {})
    print(f"{'File:':20s} {MAPPING_FILE}")
    print(f"{'Created:':20s} {data.get('created_at', '?')}")
    print(f"{'Updated:':20s} {data.get('updated_at', '?')}")
    print(f"{'Dir entries:':20s} {len(data.get('dir_forward', {}))}")
    print(f"{'File entries:':20s} {len(data.get('file_forward', {}))}")

    if not BASE_DIR.exists():
        print(f"\n  ⚠️  {BASE_DIR} does not exist")
        return

    total = sum(1 for _ in BASE_DIR.rglob("*"))
    ids = sum(1 for p in BASE_DIR.rglob("*") if p.is_file() and _ID_FILE_RE.match(p.stem))
    restorable = sum(1 for p in BASE_DIR.rglob("*") if p.is_file() and _ID_FILE_RE.match(p.stem) and p.stem in fr)
    print(f"\n  {BASE_DIR}")
    print(f"    total={total}  id_files={ids}  restorable={restorable}")
    if ids and ids == restorable:
        print(f"    ✅ All ID files can be restored")
    elif ids:
        print(f"    ⚠️  {ids - restorable} ID files have no reverse mapping")


# ── CLI ────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description="Anonymize docs/文档_ocr — map Chinese names to opaque IDs (reversible).")
    ap.add_argument("mode", nargs="?", default="status", choices=["forward", "reverse", "status"])
    ap.add_argument("--dry-run", action="store_true", help="Preview without renaming")
    args = ap.parse_args()

    if args.mode == "status":
        status()
        return 0

    count = forward(args.dry_run) if args.mode == "forward" else reverse(args.dry_run)

    if not args.dry_run:
        data = load()
        if data:
            data["state"] = "mapped" if args.mode == "forward" else "restored"
            data["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            save(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
