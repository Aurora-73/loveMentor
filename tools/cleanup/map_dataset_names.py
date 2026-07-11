#!/usr/bin/env python3
"""
Reversible dataset path mapper.

This script renames files and directories under the configured roots to opaque,
stable ids while preserving reversibility through a global JSON mapping file.

Default roots:
    /home/edalab/Desktop/cme_code/audio/A40
    /home/edalab/Desktop/cme_code/audio/A40_output
    /home/edalab/Desktop/cme_code/audio/input
    /home/edalab/Desktop/cme_code/audio/output
    /home/edalab/Desktop/cme_code/audio/output_all

Default mapping file:
    /home/edalab/Desktop/cme_code/audio/.name_mapping/dataset_name_map_v1.json

Common usage:
    # Preview forward mapping without changing files
    python3 map_dataset_names.py forward --dry-run

    # Apply forward mapping
    python3 map_dataset_names.py forward

    # Restore original names using the saved mapping file
    python3 map_dataset_names.py reverse

    # Use a custom mapping file
    python3 map_dataset_names.py forward --map-file /path/to/map.json

Notes:
    - File identity is based on root-relative path with suffix removed.
    - Different roots with the same relative logical path share the same mapped stem.
    - Running forward again reuses the existing mapping file and appends new entries.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path


BASE_DIR = Path("/home/edalab/Desktop/cme_code/audio")
DEFAULT_ROOTS = [
    BASE_DIR / "A40",
    BASE_DIR / "A40_output",
    BASE_DIR / "input",
    BASE_DIR / "output",
    BASE_DIR / "output_all",
]
DEFAULT_MAP_FILE = BASE_DIR / ".name_mapping" / "dataset_name_map_v1.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reversibly map dataset file/folder names to opaque ids."
    )
    parser.add_argument("mode", choices=["forward", "reverse"])
    parser.add_argument(
        "--roots",
        nargs="*",
        default=[str(path) for path in DEFAULT_ROOTS],
        help="Roots to map. Defaults to A40/A40_output/input/output/output_all.",
    )
    parser.add_argument(
        "--map-file",
        default=str(DEFAULT_MAP_FILE),
        help="JSON mapping file path.",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def rel_without_suffix(path: Path) -> str:
    return path.with_suffix("").as_posix()


def mapped_dir_rel(rel_dir: Path, dir_forward: dict[str, str]) -> Path:
    if rel_dir == Path("."):
        return Path()

    current = Path()
    mapped_parts: list[str] = []
    for part in rel_dir.parts:
        current /= part
        mapped_parts.append(dir_forward[current.as_posix()])
    return Path(*mapped_parts)


def mapped_file_rel(rel_file: Path, dir_forward: dict[str, str], file_forward: dict[str, str]) -> Path:
    mapped_parent = mapped_dir_rel(rel_file.parent, dir_forward)
    mapped_stem = file_forward[rel_without_suffix(rel_file)]
    return mapped_parent / f"{mapped_stem}{rel_file.suffix}"


def collect_snapshot(roots: list[Path]) -> dict:
    dir_keys: set[str] = set()
    file_keys: set[str] = set()
    root_snapshots: dict[str, dict[str, list[str]]] = {}

    for root in roots:
        if not root.exists():
            root_snapshots[str(root)] = {"dirs": [], "files": []}
            continue

        dirs: list[str] = []
        files: list[str] = []

        for path in sorted(root.rglob("*")):
            rel = path.relative_to(root)
            if path.is_dir():
                rel_str = rel.as_posix()
                dirs.append(rel_str)
                dir_keys.add(rel_str)
            elif path.is_file():
                rel_str = rel.as_posix()
                files.append(rel_str)
                file_keys.add(rel_without_suffix(rel))

        root_snapshots[str(root)] = {"dirs": dirs, "files": files}

    dir_forward = {
        key: f"d{i:06d}"
        for i, key in enumerate(sorted(dir_keys), start=1)
    }
    file_forward = {
        key: f"f{i:06d}"
        for i, key in enumerate(sorted(file_keys), start=1)
    }

    dir_reverse = {value: key for key, value in dir_forward.items()}
    file_reverse = {value: key for key, value in file_forward.items()}

    return {
        "version": 1,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        "state": "unmapped",
        "roots": [str(root) for root in roots],
        "root_snapshots": root_snapshots,
        "dir_forward": dir_forward,
        "dir_reverse": dir_reverse,
        "file_forward": file_forward,
        "file_reverse": file_reverse,
    }


def next_numeric_id(values: dict[str, str], prefix: str) -> int:
    max_seen = 0
    for value in values.values():
        if value.startswith(prefix):
            try:
                max_seen = max(max_seen, int(value[len(prefix):]))
            except ValueError:
                continue
    return max_seen + 1


def merge_snapshot(existing: dict, roots: list[Path]) -> dict:
    current = collect_snapshot(roots)

    existing.setdefault("version", 1)
    existing.setdefault("created_at", current["created_at"])
    existing["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    existing["roots"] = sorted({*existing.get("roots", []), *current["roots"]})
    existing.setdefault("root_snapshots", {})
    existing.setdefault("dir_forward", {})
    existing.setdefault("dir_reverse", {})
    existing.setdefault("file_forward", {})
    existing.setdefault("file_reverse", {})

    next_dir = next_numeric_id(existing["dir_forward"], "d")
    next_file = next_numeric_id(existing["file_forward"], "f")

    for key in sorted(current["dir_forward"]):
        if key not in existing["dir_forward"]:
            mapped = f"d{next_dir:06d}"
            next_dir += 1
            existing["dir_forward"][key] = mapped
            existing["dir_reverse"][mapped] = key

    for key in sorted(current["file_forward"]):
        if key not in existing["file_forward"]:
            mapped = f"f{next_file:06d}"
            next_file += 1
            existing["file_forward"][key] = mapped
            existing["file_reverse"][mapped] = key

    for root, snapshot in current["root_snapshots"].items():
        prev = existing["root_snapshots"].get(root, {"dirs": [], "files": []})
        merged_dirs = sorted(set(prev.get("dirs", [])) | set(snapshot.get("dirs", [])))
        merged_files = sorted(set(prev.get("files", [])) | set(snapshot.get("files", [])))
        existing["root_snapshots"][root] = {"dirs": merged_dirs, "files": merged_files}

    return existing


def write_mapping_file(map_file: Path, data: dict) -> None:
    map_file.parent.mkdir(parents=True, exist_ok=True)
    map_file.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_mapping_file(map_file: Path) -> dict:
    return json.loads(map_file.read_text(encoding="utf-8"))


def ensure_parent(path: Path, dry_run: bool) -> None:
    if dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)


def replace_path(src: Path, dst: Path, dry_run: bool) -> None:
    if src == dst:
        return
    ensure_parent(dst, dry_run)
    print(f"MOVE {src} -> {dst}")
    if not dry_run:
        os.replace(src, dst)


def mkdir_if_needed(path: Path, dry_run: bool) -> None:
    print(f"MKDIR {path}")
    if not dry_run:
        path.mkdir(parents=True, exist_ok=True)


def rmdir_if_empty(path: Path, dry_run: bool) -> None:
    if not path.exists():
        return
    try:
        next(path.iterdir())
        return
    except StopIteration:
        print(f"RMDIR {path}")
        if not dry_run:
            path.rmdir()


def apply_forward(data: dict, roots: list[Path], dry_run: bool) -> None:
    dir_forward = data["dir_forward"]
    file_forward = data["file_forward"]

    for root in roots:
        snapshot = data["root_snapshots"].get(str(root), {"dirs": [], "files": []})

        for rel_str in snapshot["files"]:
            rel_file = Path(rel_str)
            src = root / rel_file
            dst = root / mapped_file_rel(rel_file, dir_forward, file_forward)
            if src.exists():
                replace_path(src, dst, dry_run)

        for rel_dir_str in sorted(snapshot["dirs"], key=lambda s: (Path(s).parts, len(Path(s).parts))):
            rel_dir = Path(rel_dir_str)
            mapped_dir = root / mapped_dir_rel(rel_dir, dir_forward)
            mkdir_if_needed(mapped_dir, dry_run)

        for rel_dir_str in sorted(snapshot["dirs"], key=lambda s: len(Path(s).parts), reverse=True):
            rmdir_if_empty(root / rel_dir_str, dry_run)


def apply_reverse(data: dict, roots: list[Path], dry_run: bool) -> None:
    dir_forward = data["dir_forward"]
    file_forward = data["file_forward"]

    for root in roots:
        snapshot = data["root_snapshots"].get(str(root), {"dirs": [], "files": []})

        for rel_dir_str in sorted(snapshot["dirs"], key=lambda s: len(Path(s).parts)):
            mkdir_if_needed(root / rel_dir_str, dry_run)

        for rel_str in snapshot["files"]:
            rel_file = Path(rel_str)
            src = root / mapped_file_rel(rel_file, dir_forward, file_forward)
            dst = root / rel_file
            if src.exists():
                replace_path(src, dst, dry_run)

        for rel_dir_str in sorted(snapshot["dirs"], key=lambda s: len(Path(s).parts), reverse=True):
            mapped_dir = root / mapped_dir_rel(Path(rel_dir_str), dir_forward)
            rmdir_if_empty(mapped_dir, dry_run)


def main() -> int:
    args = parse_args()
    roots = [Path(path).resolve() for path in args.roots]
    map_file = Path(args.map_file).resolve()

    if args.mode == "forward":
        if map_file.exists():
            data = load_mapping_file(map_file)
            data = merge_snapshot(data, roots)
        else:
            data = collect_snapshot(roots)
        if not args.dry_run:
            write_mapping_file(map_file, data)
        apply_forward(data, roots, args.dry_run)
        data["state"] = "mapped"
        data["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        if not args.dry_run:
            write_mapping_file(map_file, data)
        return 0

    if not map_file.exists():
        raise SystemExit(f"Mapping file not found: {map_file}")

    data = load_mapping_file(map_file)
    apply_reverse(data, roots, args.dry_run)
    data["state"] = "restored"
    data["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    if not args.dry_run:
        write_mapping_file(map_file, data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
