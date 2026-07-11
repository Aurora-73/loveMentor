import json
import argparse
from pathlib import Path

LABELS = ["information_exchange", "opinion_expression", "emotion_positive", "emotion_negative", "flirt", "question_asking", "self_disclosure", "invitation", "framing_boundary", "perfunctory"]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", default=None)
    parser.add_argument("--qwen_annotations", default=None)
    parser.add_argument("--gold_annotations", default=None)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    
    project_root = Path(__file__).resolve().parent.parent.parent
    dataset_dir = project_root / "data" / "ml_dataset"
    samples_path = Path(args.samples) if args.samples else dataset_dir / "samples_phase0.jsonl"
    qwen_path = Path(args.qwen_annotations) if args.qwen_annotations else dataset_dir / "annotations_phase1.jsonl"
    gold_path = Path(args.gold_annotations) if args.gold_annotations else dataset_dir / "annotations_150_gold.jsonl"
    output_path = Path(args.output) if args.output else dataset_dir / "training_set.jsonl"
    
    with open(samples_path, "r", encoding="utf-8") as f:
        samples = {s["sample_id"]: s for s in [json.loads(line) for line in f if line.strip()]}
    
    with open(qwen_path, "r", encoding="utf-8") as f:
        qwen_data = {d["sample_id"]: d["labels"] for d in [json.loads(line) for line in f if line.strip()]}
    
    gold_data = {}
    if gold_path.exists():
        with open(gold_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    d = json.loads(line)
                    if "labels" in d:
                        gold_data[d["sample_id"]] = d["labels"]
                    elif "annotation" in d:
                        gold_data[d["sample_id"]] = d["annotation"]
    
    training_set = []
    for sample_id, sample in samples.items():
        if sample_id in qwen_data:
            labels = qwen_data[sample_id].copy()
            
            if sample_id in gold_data:
                gold_labels = gold_data[sample_id]
                for label in LABELS:
                    if label in gold_labels:
                        labels[label] = gold_labels[label]
            
            training_set.append({
                "sample_id": sample_id,
                "contact_wxid": sample.get("contact_wxid", ""),
                "messages": sample["messages"],
                "labels": labels,
            })
    
    with open(output_path, "w", encoding="utf-8") as f:
        for item in training_set:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    
    print(f"Training set created: {len(training_set)} samples")
    print(f"Output: {output_path}")
    
    label_stats = {l: 0 for l in LABELS}
    for item in training_set:
        for l in LABELS:
            if item["labels"].get(l, 0) == 1:
                label_stats[l] += 1
    
    print("\nLabel distribution:")
    for l, count in label_stats.items():
        print(f"  {l}: {count} ({count/len(training_set)*100:.1f}%)")

if __name__ == "__main__":
    main()
