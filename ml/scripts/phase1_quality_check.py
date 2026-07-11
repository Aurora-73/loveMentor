import json
import sys
import argparse
from pathlib import Path
from sklearn.metrics import cohen_kappa_score, classification_report

LABELS = ["information_exchange", "opinion_expression", "emotion_positive", "emotion_negative", "flirt", "question_asking", "self_disclosure", "invitation", "framing_boundary", "perfunctory"]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--qwen_annotations", default=None)
    parser.add_argument("--gold_annotations", default=None)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    
    project_root = Path(__file__).resolve().parent.parent.parent
    dataset_dir = project_root / "data" / "ml_dataset"
    qwen_path = Path(args.qwen_annotations) if args.qwen_annotations else dataset_dir / "annotations_phase1.jsonl"
    gold_path = Path(args.gold_annotations) if args.gold_annotations else dataset_dir / "annotations_150_gold.jsonl"
    output_path = Path(args.output) if args.output else project_root / "ml" / "evaluation" / "qwen_quality_report.json"
    
    with open(qwen_path, "r", encoding="utf-8") as f:
        qwen_data = {d["sample_id"]: d["labels"] for d in [json.loads(line) for line in f if line.strip()]}
    
    with open(gold_path, "r", encoding="utf-8") as f:
        gold_data = {}
        for line in f:
            if line.strip():
                d = json.loads(line)
                if "labels" in d:
                    gold_data[d["sample_id"]] = d["labels"]
                elif "annotation" in d:
                    gold_data[d["sample_id"]] = d["annotation"]
    
    common_ids = set(qwen_data.keys()) & set(gold_data.keys())
    print(f"Qwen samples: {len(qwen_data)}")
    print(f"Gold samples: {len(gold_data)}")
    print(f"Common samples: {len(common_ids)}")
    
    qwen_labels = []
    gold_labels = []
    
    for sample_id in common_ids:
        qwen = qwen_data[sample_id]
        gold = gold_data[sample_id]
        qwen_row = [qwen.get(l, 0) for l in LABELS]
        gold_row = [gold.get(l, 0) for l in LABELS]
        qwen_labels.append(qwen_row)
        gold_labels.append(gold_row)
    
    import numpy as np
    qwen_array = np.array(qwen_labels)
    gold_array = np.array(gold_labels)
    
    report = {
        "summary": {
            "qwen_samples": len(qwen_data),
            "gold_samples": len(gold_data),
            "common_samples": len(common_ids),
        },
        "per_label": {},
        "overall": {},
    }
    
    for i, label in enumerate(LABELS):
        q = qwen_array[:, i]
        g = gold_array[:, i]
        kappa = cohen_kappa_score(g, q)
        cr = classification_report(g, q, zero_division=0, output_dict=True)
        
        report["per_label"][label] = {
            "kappa": kappa,
            "precision": cr["1"]["precision"],
            "recall": cr["1"]["recall"],
            "f1": cr["1"]["f1-score"],
            "support": cr["1"]["support"],
        }
    
    overall_kappa = []
    for i in range(qwen_array.shape[1]):
        overall_kappa.append(cohen_kappa_score(gold_array[:, i], qwen_array[:, i]))
    report["overall"]["mean_kappa"] = np.mean(overall_kappa)
    report["overall"]["min_kappa"] = np.min(overall_kappa)
    report["overall"]["max_kappa"] = np.max(overall_kappa)
    
    print("\nQuality Report:")
    print(f"Mean Kappa: {report['overall']['mean_kappa']:.4f}")
    print(f"Min Kappa: {report['overall']['min_kappa']:.4f}")
    print(f"Max Kappa: {report['overall']['max_kappa']:.4f}")
    
    print("\nPer-label Kappa:")
    for label in LABELS:
        print(f"  {label}: {report['per_label'][label]['kappa']:.4f}")
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\nReport saved to {output_path}")
    
    return report

if __name__ == "__main__":
    main()
