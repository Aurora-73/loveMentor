import json
import shutil
import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description='Copy or move selected folders by priority')
    parser.add_argument('--priority', type=int, required=True, help='Priority level to process (1, 2, etc.)')
    parser.add_argument('--json', default='selected.json', help='Path to selected.json')
    parser.add_argument('--output', default=r'<project_root>\docs\选中', help='Output directory')
    parser.add_argument('--mode', choices=['copy', 'move'], default='copy', help='Operation mode: copy (default) or move')
    args = parser.parse_args()

    json_path = Path(args.json)
    output_dir = Path(args.output)

    if not json_path.exists():
        print(f"Error: {json_path} not found")
        return

    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    parent_dir = Path(data['parent_dir'])
    selected_items = data['selected']

    priority_items = [item for item in selected_items if item.get('priority') == args.priority]

    if not priority_items:
        print(f"No items found with priority {args.priority}")
        return

    op = "move" if args.mode == "move" else "copy"
    label = "MOVE" if args.mode == "move" else "COPY"

    print(f"Found {len(priority_items)} items with priority {args.priority} (mode: {op}):")
    for item in priority_items:
        print(f"  {item['path']}")

    output_dir.mkdir(parents=True, exist_ok=True)

    success = 0
    skipped = 0
    for item in priority_items:
        src_path = Path(item['path'])
        rel_path = src_path.relative_to(parent_dir)
        dst_path = output_dir / rel_path

        if not src_path.exists():
            print(f"  [SKIP] Source not found: {src_path}")
            skipped += 1
            continue

        try:
            if dst_path.exists():
                shutil.rmtree(dst_path)

            if args.mode == 'move':
                shutil.move(str(src_path), str(dst_path))
            else:
                shutil.copytree(src_path, dst_path)
            print(f"  [{label}] {rel_path} -> {dst_path}")
            success += 1
        except Exception as e:
            print(f"  [ERROR] Failed to {op} {src_path}: {e}")
            skipped += 1

    print(f"\nSummary: {success} {op}d, {skipped} skipped/error")


if __name__ == '__main__':
    main()
