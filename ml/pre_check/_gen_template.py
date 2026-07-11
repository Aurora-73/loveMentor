﻿import json
import random

samples_path = r"<project_root>\data\ml_dataset\samples_phase0.jsonl"
baseline_path = r"<project_root>\data\ml_outputs\baseline_results.jsonl"
output_path = r"<project_root>\data\pre_check\annotation_template.md"

samples = []
with open(samples_path, "r", encoding="utf-8") as f:
    for line in f:
        if line.strip():
            samples.append(json.loads(line))

baseline = {}
with open(baseline_path, "r", encoding="utf-8") as f:
    for line in f:
        if line.strip():
            d = json.loads(line)
            baseline[d["sample_id"]] = d.get("labels", {})

precheck_labels = ["question_asking", "flirt", "perfunctory"]

selected_ids = set()

for label in precheck_labels:
    pos_ids = [s["sample_id"] for s in samples if baseline.get(s["sample_id"], {}).get(label) and s["sample_id"] not in selected_ids]
    neg_ids = [s["sample_id"] for s in samples if not baseline.get(s["sample_id"], {}).get(label) and s["sample_id"] not in selected_ids]
    
    random.seed(42)
    random.shuffle(pos_ids)
    random.shuffle(neg_ids)
    
    for sid in pos_ids[:15]:
        selected_ids.add(sid)
    for sid in neg_ids[:15]:
        selected_ids.add(sid)

selected_samples = [s for s in samples if s["sample_id"] in selected_ids]
random.shuffle(selected_samples)
selected_samples = selected_samples[:50]

with open(output_path, "w", encoding="utf-8") as f:
    f.write("# 语义分析 Pre-check 标注模板\n\n")
    f.write("> 标注规范：ml/docs/annotation_guideline.md\n")
    f.write("> 标签：question_asking, flirt, perfunctory\n\n")
    f.write("---\n\n")
    
    for i, s in enumerate(selected_samples, 1):
        sample_id = s["sample_id"]
        contact = s.get("contact_remark", s.get("contact_wxid", "?"))
        bl = baseline.get(sample_id, {})
        
        f.write(f"## 样本 {i}: {sample_id}  ({contact})\n\n")
        f.write(f"- 轮数: {s['turn_count']}\n")
        f.write(f"- 规则预测: ")
        for label in precheck_labels:
            f.write(f"{label}={'是' if bl.get(label) else '否'} ")
        f.write("\n\n")
        
        f.write("**对话内容：**\n\n")
        for msg in s["messages"]:
            role = "她" if msg["role"] == "her" else "我"
            content = msg["content"].replace("\n", " / ")
            if len(content) > 100:
                content = content[:100] + "..."
            f.write(f"- [{role}] {content}\n")
        
        f.write("\n**标注：**\n\n")
        for label in precheck_labels:
            f.write(f"- {label}: [ ]  \n")
        f.write("\n---\n\n")

print(f"Saved {len(selected_samples)} samples to: {output_path}")

