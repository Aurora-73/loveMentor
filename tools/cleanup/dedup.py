#!/usr/bin/env python3
r"""Deduplicate transcription files across output_[...] directories.

Usage:
    python dedup.py --report quality_report.csv
    python dedup.py --report report.csv --threshold 0.15 --delete-csv dedup_delete.csv --review-csv dedup_review.csv

Logic:
    1. Parse each file path in the report CSV.
    2. Strip the output_[...] prefix to get the relative path.
    3. Group files by relative path.
    4. For groups with multiple files (duplicates):
       - If score difference > threshold: mark lower-scored files for deletion.
       - If score difference <= threshold: record in manual review CSV.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import defaultdict
from pathlib import Path


# Matches output_[A100_6.27], output_[A40_7.2], etc.
OUTPUT_PREFIX_RE = re.compile(r"^output_\[[^\]]+\]\\")


def strip_top_folder(path: str) -> tuple[str, str]:
    """Split a path into (top_folder, relative_path).

    Strips the first path component regardless of pattern:
      output_[A100_6.27]\\课程\\文件.txt  →  (output_[A100_6.27], 课程\\文件.txt)
      【A01】各大情感导师\\课程\\文件.txt  →  (【A01】各大情感导师, 课程\\文件.txt)
    """
    idx = path.find("\\")
    if idx == -1:
        return path, ""
    folder = path[:idx]
    rel = path[idx + 1:]
    return folder, rel


def load_report(csv_path: str) -> list[dict]:
    """Load a quality report CSV and return rows as dicts."""
    rows = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            row["score"] = float(row["score"])
            row["char_count"] = int(row.get("char_count", 0))
            rows.append(row)
    return rows


def find_duplicates(rows: list[dict]) -> dict[str, list[dict]]:
    """Group files by relative path (after stripping top-level folder).

    Returns a dict: relative_path -> list of file rows (only groups with >1 file).
    """
    groups: defaultdict[str, list[dict]] = defaultdict(list)

    for row in rows:
        folder, rel = strip_top_folder(row["path"])
        if not rel:
            continue
        row["_output_folder"] = folder
        row["_relative_path"] = rel
        groups[rel].append(row)

    duplicates = {k: v for k, v in groups.items() if len(v) > 1}
    return duplicates


def classify_duplicates(
    duplicates: dict[str, list[dict]],
    threshold: float,
) -> tuple[list[dict], list[dict]]:
    """Classify duplicate groups into auto-delete and manual-review.

    Returns (delete_rows, review_rows).
    Each row has: relative_path, output_folder, score, char_count, path, issue_types, action, best_score, score_diff
    """
    delete_rows = []
    review_rows = []

    for rel, files in duplicates.items():
        # Sort by score descending
        files_sorted = sorted(files, key=lambda r: r["score"], reverse=True)
        best = files_sorted[0]
        worst = files_sorted[-1]
        score_diff = best["score"] - worst["score"]

        for f in files_sorted[1:]:
            row = {
                "relative_path": rel,
                "output_folder": f["_output_folder"],
                "score": f["score"],
                "char_count": f["char_count"],
                "path": f["path"],
                "issue_types": f.get("issue_types", ""),
                "best_output_folder": best["_output_folder"],
                "best_score": best["score"],
                "best_path": best["path"],
                "score_diff": round(score_diff, 3),
            }

            if score_diff > threshold:
                row["action"] = "delete"
                delete_rows.append(row)
            else:
                row["action"] = "review"
                review_rows.append(row)

    return delete_rows, review_rows


def main():
    ap = argparse.ArgumentParser(
        description="Deduplicate transcription files across output_[...] directories"
    )
    ap.add_argument("--report", required=True,
                    help="Path to quality report CSV")
    ap.add_argument("--threshold", type=float, default=0.15,
                    help="Score difference threshold for auto-delete vs manual review (default: 0.15)")
    ap.add_argument("--delete-csv", default="dedup_delete.csv",
                    help="Output CSV for files to delete (default: dedup_delete.csv)")
    ap.add_argument("--review-csv", default="dedup_review.csv",
                    help="Output CSV for manual review (default: dedup_review.csv)")
    args = ap.parse_args()

    print(f"Loading report: {args.report}", file=sys.stderr)
    rows = load_report(args.report)
    print(f"  Total files: {len(rows)}", file=sys.stderr)

    print("Finding duplicates...", file=sys.stderr)
    duplicates = find_duplicates(rows)
    print(f"  Duplicate groups: {len(duplicates)}", file=sys.stderr)

    total_dup_files = sum(len(v) for v in duplicates.values())
    print(f"  Total duplicate files: {total_dup_files}", file=sys.stderr)

    print(f"Classifying with threshold={args.threshold}...", file=sys.stderr)
    delete_rows, review_rows = classify_duplicates(duplicates, args.threshold)

    # Write delete CSV
    if delete_rows:
        with open(args.delete_csv, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "relative_path", "output_folder", "score", "char_count", "path",
                "issue_types", "best_output_folder", "best_score", "best_path",
                "score_diff", "action",
            ])
            writer.writeheader()
            writer.writerows(delete_rows)

    # Write review CSV
    if review_rows:
        with open(args.review_csv, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "relative_path", "output_folder", "score", "char_count", "path",
                "issue_types", "best_output_folder", "best_score", "best_path",
                "score_diff", "action",
            ])
            writer.writeheader()
            writer.writerows(review_rows)

    # Summary
    print(file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print(f"SUMMARY", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print(f"  Total files in report:     {len(rows)}", file=sys.stderr)
    print(f"  Duplicate groups:          {len(duplicates)}", file=sys.stderr)
    print(f"  Total duplicate files:     {total_dup_files}", file=sys.stderr)
    print(f"  Files to delete (> {args.threshold}):  {len(delete_rows)}", file=sys.stderr)
    print(f"  Files for manual review:   {len(review_rows)}", file=sys.stderr)
    print(f"  Files to keep (best):      {len(duplicates)}", file=sys.stderr)
    print(file=sys.stderr)
    if delete_rows:
        print(f"  Delete list: {args.delete_csv}", file=sys.stderr)
    if review_rows:
        print(f"  Review list: {args.review_csv}", file=sys.stderr)

    # Score diff distribution
    if duplicates:
        print(file=sys.stderr)
        print("  Score difference distribution:", file=sys.stderr)
        diffs = []
        for files in duplicates.values():
            scores = sorted([f["score"] for f in files], reverse=True)
            diffs.append(scores[0] - scores[-1])
        bins = [(0, 0.05), (0.05, 0.1), (0.1, 0.15), (0.15, 0.3), (0.3, 0.5), (0.5, 1.0)]
        for lo, hi in bins:
            count = sum(1 for d in diffs if lo <= d < hi)
            if count:
                print(f"    {lo:.2f}-{hi:.2f}: {count} groups", file=sys.stderr)


if __name__ == "__main__":
    main()
