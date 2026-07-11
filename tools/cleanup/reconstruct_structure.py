#!/usr/bin/env python3
r"""Reconstruct top-level category structure in 文档/ by matching against 百度网盘/.

Problem:
    After dedup and merge, 文档/ has 229 top-level subdirs (e.g. A04、林老头)
    but lost the category prefix (e.g. 【A01】各大情感导师\).  We want to
    restore the full structure.

Solution:
    1. Walk 百度网盘/ and build mapping: dir_name -> list of parent paths.
    2. For each top-level dir in 文档/, look up its name in the mapping.
    3. If unique match, move/copy the dir under the matched parent path.
    4. If ambiguous or not found, record for manual review.

Usage:
    # Build index from 百度网盘/ and save to JSON (run once)
    python reconstruct_structure.py --save-index baidu_structure.json

    # Reconstruct 文档/ structure using saved JSON index
    python reconstruct_structure.py --load-index baidu_structure.json --dry-run
    python reconstruct_structure.py --load-index baidu_structure.json --apply

    # Legacy: build index on-the-fly (no JSON)
    python reconstruct_structure.py --apply --method move
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path


def build_top_level_index(
    baidu_root: Path,
    audio_uploaded_dir: Path | None = None,
) -> dict[str, list[str]]:
    """Build index: first-level subdir name -> list of full paths.

    Indexes both:
    - Top-level category subdirs under baidu_root (e.g. 【A01】各大情感导师\\A04、林老头)
    - Uploaded audio dirs (e.g. 老佟《短期关系》) if audio_uploaded_dir given
      These are marked with status "ok_uploaded" and placed under _未分类/.
    """
    index: defaultdict[str, list[str]] = defaultdict(list)
    top_dirs = [d for d in baidu_root.iterdir()
                if d.is_dir() and not d.name.startswith("__") and not d.name.startswith(".")]

    for top_dir in top_dirs:
        try:
            for sub_dir in top_dir.iterdir():
                if not sub_dir.is_dir():
                    continue
                if sub_dir.name.startswith("__") or sub_dir.name.startswith("."):
                    continue
                rel = str(sub_dir.relative_to(baidu_root))
                index[sub_dir.name].append(rel)
        except PermissionError:
            continue

    # Also index uploaded audio courses (no category)
    if audio_uploaded_dir and audio_uploaded_dir.is_dir():
        for sub_dir in audio_uploaded_dir.iterdir():
            if not sub_dir.is_dir():
                continue
            if sub_dir.name.startswith("__") or sub_dir.name.startswith("."):
                continue
            # Mark these with a special prefix so caller can distinguish
            rel = "_UPLOADED_/" + sub_dir.name
            index[sub_dir.name].append(rel)

    total = sum(len(v) for v in index.values())
    print(f"  Indexed {len(index)} unique first-level subdirs ({total} total)", file=sys.stderr)
    ambiguous = sum(1 for v in index.values() if len(v) > 1)
    print(f"  Ambiguous names (multiple matches): {ambiguous}", file=sys.stderr)
    return dict(index)


def save_index_to_json(
    baidu_root: Path,
    audio_uploaded_dir: Path | None,
    output_path: Path,
) -> None:
    """Walk 百度网盘/ and save complete structure as JSON.

    JSON schema:
    {
        "version": 1,
        "created_at": "2026-07-03T12:34:56",
        "baidu_root": "E:\\Code\\loveMentor\\docs\\百度网盘",
        "top_level_dirs": ["【A01】各大情感导师", ...],
        "dir_index": {"A04、林老头": ["【A01】各大情感导师\\A04、林老头"], ...},
        "tree": [
            {
                "name": "【A01】各大情感导师",
                "type": "dir",
                "children": [
                    {"name": "A04、林老头", "type": "dir", "children": [...]},
                    ...
                ]
            },
            ...
        ]
    }
    """
    print(f"Building complete directory tree from {baidu_root}...", file=sys.stderr)
    t0 = time.perf_counter()

    # Build dir_index (reuse existing function)
    dir_index = build_top_level_index(baidu_root, audio_uploaded_dir)

    # Collect top-level dir names
    top_level_dirs = sorted([
        d.name for d in baidu_root.iterdir()
        if d.is_dir() and not d.name.startswith("__") and not d.name.startswith(".")
    ])

    # Build complete tree recursively
    def build_tree(path: Path, max_depth: int = 5, current_depth: int = 0) -> list[dict]:
        if current_depth >= max_depth:
            return []
        items = []
        try:
            for child in sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name)):
                if child.name.startswith("__") or child.name.startswith("."):
                    continue
                if child.is_dir():
                    node = {
                        "name": child.name,
                        "type": "dir",
                    }
                    children = build_tree(child, max_depth, current_depth + 1)
                    if children:
                        node["children"] = children
                    items.append(node)
                else:
                    items.append({
                        "name": child.name,
                        "type": "file",
                        "size": child.stat().st_size,
                    })
        except PermissionError:
            pass
        return items

    tree = build_tree(baidu_root, max_depth=5)

    # Also include uploaded audio dir in the tree
    if audio_uploaded_dir and audio_uploaded_dir.is_dir():
        uploaded_node = {
            "name": "_UPLOADED_",
            "type": "dir",
            "children": build_tree(audio_uploaded_dir, max_depth=5),
        }
        tree.append(uploaded_node)

    data = {
        "version": 1,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "baidu_root": str(baidu_root),
        "audio_uploaded_dir": str(audio_uploaded_dir) if audio_uploaded_dir else None,
        "top_level_dirs": top_level_dirs,
        "dir_index": dir_index,
        "tree": tree,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    elapsed = time.perf_counter() - t0
    size_mb = output_path.stat().st_size / 1024 / 1024
    print(f"  Saved to {output_path} ({size_mb:.1f} MB, {elapsed:.1f}s)", file=sys.stderr)
    print(f"  Top-level dirs: {len(top_level_dirs)}", file=sys.stderr)
    print(f"  Dir index entries: {len(dir_index)}", file=sys.stderr)


def load_index_from_json(json_path: Path) -> dict:
    """Load directory structure from JSON file.

    Returns dict with keys: version, created_at, baidu_root,
    audio_uploaded_dir, top_level_dirs, dir_index, tree
    """
    print(f"Loading index from {json_path}...", file=sys.stderr)
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    print(f"  Version: {data.get('version', '?')}", file=sys.stderr)
    print(f"  Created: {data.get('created_at', '?')}", file=sys.stderr)
    print(f"  Top-level dirs: {len(data.get('top_level_dirs', []))}", file=sys.stderr)
    print(f"  Dir index entries: {len(data.get('dir_index', {}))}", file=sys.stderr)
    return data


def match_doc_dirs(
    doc_root: Path,
    dir_index: dict[str, list[str]],
    baidu_top_dirs: set[str],
) -> list[dict]:
    """Match each subdirectory under output_[...]/ in 文档/ against the index.

    Handles two layouts:
    - Flat: 文档/A04、林老头/... (already merged)
    - Nested: 文档/output_[A100_6.27]/A04、林老头/... (original STT output)

    Priority:
      1. Baidu top-level dir name -> keep as-is (status: ok_top_level)
      2. Categorized subdir (unique) -> move under category (status: ok)
      3. Uploaded-only (unique) -> move to _未分类 (status: ok_uploaded)
      4. Multiple categorized matches -> ambiguous
      5. No match -> not_found
    """
    results = []

    # Collect candidate dirs: either top-level or under output_[...]
    candidates: list[tuple[str, Path]] = []  # (display_name, full_path)
    for entry in doc_root.iterdir():
        if not entry.is_dir():
            continue
        if entry.name.startswith("_") or entry.name.startswith("."):
            continue
        if entry.name.startswith("output_"):
            # Nested layout: scan one level deeper
            for sub in entry.iterdir():
                if sub.is_dir() and not sub.name.startswith("_") and not sub.name.startswith("."):
                    candidates.append((f"{entry.name}\\{sub.name}", sub))
        else:
            # Flat layout
            candidates.append((entry.name, entry))

    for display_name, dir_path in sorted(candidates, key=lambda x: x[0]):
        name = dir_path.name

        # Case 1: dir name is itself a baidu top-level category -> keep as-is
        if name in baidu_top_dirs:
            results.append({
                "dir_name": display_name,
                "dir_path": str(dir_path.relative_to(doc_root)),
                "status": "ok_top_level",
                "match_count": 1,
                "matched_paths": name,
                "selected_path": name,
            })
            continue

        matches = dir_index.get(name, [])
        if not matches:
            status = "not_found"
            selected = ""
        else:
            # Separate categorized (baidu) vs uploaded (audio) matches
            categorized = [m for m in matches if not m.startswith("_UPLOADED_/")]
            uploaded = [m for m in matches if m.startswith("_UPLOADED_/")]
            if categorized:
                if len(categorized) == 1:
                    status = "ok"
                    selected = categorized[0]
                else:
                    status = "ambiguous"
                    selected = ""
            elif uploaded:
                status = "ok_uploaded"
                selected = uploaded[0]
            else:
                status = "ambiguous"
                selected = ""

        results.append({
            "dir_name": display_name,
            "dir_path": str(dir_path.relative_to(doc_root)),
            "status": status,
            "match_count": len(matches),
            "matched_paths": "; ".join(matches),
            "selected_path": selected,
        })

    return results


def main():
    ap = argparse.ArgumentParser(
        description="Reconstruct top-level category structure in 文档/"
    )
    ap.add_argument("--baidu-root", default=r"<project_root>\docs\百度网盘",
                    help="Path to 百度网盘 directory")
    ap.add_argument("--doc-root", default=r"<project_root>\docs\文档",
                    help="Path to 文档 directory")
    ap.add_argument("--audio-uploaded-dir", default=r"<project_root>\docs\音频\...已上传",
                    help="Path to uploaded audio directory (unclassified courses)")
    ap.add_argument("--save-index", default=None,
                    help="Build index from 百度网盘/ and save to JSON file, then exit")
    ap.add_argument("--load-index", default=None,
                    help="Load directory index from JSON file (instead of scanning 百度网盘/)")
    ap.add_argument("--method", choices=["copy", "move"], default="move",
                    help="Copy or move directories (default: move)")
    ap.add_argument("--apply", action="store_true",
                    help="Actually perform the operation (default: dry-run)")
    ap.add_argument("--undo", default=None,
                    help="Undo a previous operation using the given log file")
    ap.add_argument("--undo-log", default="reconstruct_undo_log.json",
                    help="Path to save undo log (default: reconstruct_undo_log.json)")
    ap.add_argument("--report-csv", default="reconstruct_report.csv",
                    help="CSV report")
    args = ap.parse_args()

    baidu_root = Path(args.baidu_root)
    doc_root = Path(args.doc_root)
    audio_uploaded_dir = Path(args.audio_uploaded_dir) if args.audio_uploaded_dir else None

    # Mode 0: Undo (no index needed)
    if args.undo:
        print(f"文档 root: {doc_root}", file=sys.stderr)
        print(file=sys.stderr)
        # Fall through to Step 4 undo logic (will return early)
        results = []
        status_counts = {}

    # Mode 1: Save index to JSON and exit
    elif args.save_index:
        print(f"百度网盘 root: {baidu_root}", file=sys.stderr)
        print(f"音频已上传: {audio_uploaded_dir if audio_uploaded_dir else '(none)'}", file=sys.stderr)
        print(file=sys.stderr)
        save_index_to_json(baidu_root, audio_uploaded_dir, Path(args.save_index))
        return

    # Mode 2/3: Load from JSON or build on-the-fly
    if args.load_index:
        print(f"Loading index from JSON: {args.load_index}", file=sys.stderr)
        print(file=sys.stderr)
        data = load_index_from_json(Path(args.load_index))
        dir_index = data["dir_index"]
        baidu_top_dirs = set(data["top_level_dirs"])
        print(f"  Dir index entries: {len(dir_index)}", file=sys.stderr)
        print(f"  Top-level dirs: {len(baidu_top_dirs)}", file=sys.stderr)
    elif not args.undo:
        print(f"百度网盘 root: {baidu_root}", file=sys.stderr)
        print(f"音频已上传: {audio_uploaded_dir if audio_uploaded_dir else '(none)'}", file=sys.stderr)
        print(file=sys.stderr)

        # Step 1: Build index on-the-fly
        print("Building directory index...", file=sys.stderr)
        dir_index = build_top_level_index(baidu_root, audio_uploaded_dir)

        baidu_top_dirs = {
            d.name for d in baidu_root.iterdir()
            if d.is_dir() and not d.name.startswith("__") and not d.name.startswith(".")
        }
        print(f"  Baidu top-level categories: {len(baidu_top_dirs)}", file=sys.stderr)

    if not args.undo:
        print(f"文档 root: {doc_root}", file=sys.stderr)
        print(f"Method: {args.method}", file=sys.stderr)
        print(f"Apply: {args.apply}", file=sys.stderr)
        print(file=sys.stderr)

        # Step 2: Match directories
        print("Matching top-level dirs in 文档/...", file=sys.stderr)
        results = match_doc_dirs(doc_root, dir_index, baidu_top_dirs)

        # Step 3: Summary
        status_counts: dict[str, int] = defaultdict(int)
        for r in results:
            status_counts[r["status"]] += 1

        print(file=sys.stderr)
        print("=" * 60, file=sys.stderr)
        print(f"  Total top-level dirs in 文档/: {len(results)}", file=sys.stderr)
        for status in ("ok_top_level", "ok", "ok_uploaded", "ambiguous", "not_found"):
            count = status_counts.get(status, 0)
            pct = count / len(results) * 100 if results else 0
            print(f"  {status:14s}: {count:4d} ({pct:.1f}%)", file=sys.stderr)
        print("=" * 60, file=sys.stderr)

        # Show samples of each status
        for status in ("ok_top_level", "ok", "ok_uploaded", "ambiguous", "not_found"):
            samples = [r for r in results if r["status"] == status][:5]
            if samples:
                print(f"\n  [{status}] samples:", file=sys.stderr)
                for s in samples:
                    path_info = s["selected_path"] or s["matched_paths"] or "(none)"
                    print(f"    {s['dir_name'][:50]:50s} -> {path_info[:70]}", file=sys.stderr)

    # Step 4: Apply / Undo
    operations_log: list[dict] = []

    if args.undo:
        # ---- Undo mode ----
        undo_log_path = Path(args.undo)
        if not undo_log_path.is_file():
            print(f"Error: undo log not found: {undo_log_path}", file=sys.stderr)
            sys.exit(1)
        with open(undo_log_path, "r", encoding="utf-8") as f:
            undo_data = json.load(f)
        ops = undo_data.get("operations", [])
        print(f"Undoing {len(ops)} operations from {undo_log_path}...", file=sys.stderr)

        undo_count = 0
        skip_count = 0
        # Reverse order: undo last operation first
        for op in reversed(ops):
            op_type = op.get("type")
            try:
                if op_type == "move":
                    src = doc_root / op["dst"]  # swap: move dst back to src
                    dst = doc_root / op["src"]
                    if not src.exists():
                        print(f"  [skip] {op['dst']} (not found)", file=sys.stderr)
                        skip_count += 1
                        continue
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    if dst.exists():
                        # Target already exists, skip (user may have re-run)
                        print(f"  [skip] {op['dst']} (dst exists)", file=sys.stderr)
                        skip_count += 1
                        continue
                    shutil.move(str(src), str(dst))
                    undo_count += 1

                elif op_type == "merge_move":
                    # Complex merge: try to move back items that we know we moved
                    # We recorded moved_items list
                    src_base = doc_root / op["dst"]
                    dst_base = doc_root / op["src"]
                    moved_items = op.get("moved_items", [])
                    if not src_base.exists():
                        print(f"  [skip] {op['dst']} (not found)", file=sys.stderr)
                        skip_count += 1
                        continue
                    dst_base.mkdir(parents=True, exist_ok=True)
                    for item_rel in reversed(moved_items):
                        src_item = src_base / item_rel
                        dst_item = dst_base / item_rel
                        if src_item.exists() and not dst_item.exists():
                            dst_item.parent.mkdir(parents=True, exist_ok=True)
                            shutil.move(str(src_item), str(dst_item))
                    undo_count += 1

                elif op_type == "mkdir":
                    # Remove directory if empty
                    p = doc_root / op["path"]
                    if p.exists() and p.is_dir():
                        try:
                            p.rmdir()  # only removes if empty
                        except OSError:
                            pass
            except Exception as e:
                print(f"  [error] {op.get('type', '?')} {op.get('src', op.get('path', '?'))}: {e}", file=sys.stderr)
                skip_count += 1

        print(f"  Undone: {undo_count}, Skipped: {skip_count}", file=sys.stderr)
        return

    elif args.apply:
        # ---- Apply mode ----
        print(f"\n{'Moving' if args.method == 'move' else 'Copying'} directories...", file=sys.stderr)
        ok_count = 0
        for r in results:
            if r["status"] not in ("ok", "ok_uploaded"):
                continue
            src = doc_root / r["dir_path"]
            if r["status"] == "ok_uploaded":
                dst = doc_root / "_未分类" / Path(r["dir_path"]).name
            else:
                dst = doc_root / r["selected_path"]

            # Record parent dir creation
            parent = dst.parent
            if not parent.exists():
                operations_log.append({
                    "type": "mkdir",
                    "path": str(parent.relative_to(doc_root)),
                })

            dst.parent.mkdir(parents=True, exist_ok=True)

            if args.method == "copy":
                shutil.copytree(src, dst, dirs_exist_ok=True)
                operations_log.append({
                    "type": "copy",
                    "src": str(src.relative_to(doc_root)),
                    "dst": str(dst.relative_to(doc_root)),
                })
            else:
                # Move
                if dst.exists():
                    # Merge: record every item we move
                    moved_items = []
                    for item in src.rglob("*"):
                        if item.is_file():
                            rel = item.relative_to(src)
                            dst_item = dst / rel
                            if not dst_item.exists():
                                moved_items.append(str(rel))
                    # Execute merge move
                    for item in src.iterdir():
                        dst_item = dst / item.name
                        if dst_item.exists():
                            if dst_item.is_dir() and item.is_dir():
                                for sub_item in item.rglob("*"):
                                    rel = sub_item.relative_to(item)
                                    dst_sub = dst_item / rel
                                    if not dst_sub.exists():
                                        dst_sub.parent.mkdir(parents=True, exist_ok=True)
                                        shutil.move(str(sub_item), str(dst_sub))
                        else:
                            shutil.move(str(item), str(dst_item))
                    try:
                        src.rmdir()
                    except OSError:
                        pass
                    operations_log.append({
                        "type": "merge_move",
                        "src": str(src.relative_to(doc_root)),
                        "dst": str(dst.relative_to(doc_root)),
                        "moved_items": moved_items,
                    })
                else:
                    # Simple move
                    shutil.move(str(src), str(dst))
                    operations_log.append({
                        "type": "move",
                        "src": str(src.relative_to(doc_root)),
                        "dst": str(dst.relative_to(doc_root)),
                    })
            ok_count += 1

        print(f"  {'Copied' if args.method == 'copy' else 'Moved'} {ok_count} directories", file=sys.stderr)

        # Save operations log for undo
        log_path = args.undo_log
        log_data = {
            "version": 1,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "doc_root": str(doc_root),
            "method": args.method,
            "operations": operations_log,
        }
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(log_data, f, ensure_ascii=False, indent=2)
        print(f"  Undo log saved to: {log_path}", file=sys.stderr)
        print(f"  To undo: python reconstruct_structure.py --undo {log_path}", file=sys.stderr)
    else:
        print("\n  [Dry-run] No changes made.  Use --apply to execute.", file=sys.stderr)

    # Step 5: Write report
    print(f"\nWriting report: {args.report_csv}", file=sys.stderr)
    with open(args.report_csv, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "dir_name", "dir_path", "status", "match_count",
            "matched_paths", "selected_path",
        ])
        writer.writeheader()
        writer.writerows(results)
    print(f"Report saved to: {args.report_csv}", file=sys.stderr)


if __name__ == "__main__":
    main()
