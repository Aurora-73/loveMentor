import json

with open(Path(__file__).resolve().parents[2] / "selected_full.json", 'r', encoding='utf-8') as f:
    data = json.load(f)

selected = [s for s in data['selected'] if s['selected']]
print(f"已勾选: {len(selected)} 个")
for s in selected:
    print(f"  [{s['priority']}] {s['path']}")
