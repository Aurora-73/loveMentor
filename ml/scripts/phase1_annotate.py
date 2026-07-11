# -*- coding: utf-8 -*-
import json
import sys
import time
import argparse
from pathlib import Path

LABELS = ["information_exchange", "opinion_expression", "emotion_positive", "emotion_negative", "flirt", "question_asking", "self_disclosure", "invitation", "framing_boundary", "perfunctory"]

LABEL_DESC = {
    "information_exchange": "她陈述事实信息",
    "opinion_expression": "她表达观点或评价",
    "emotion_positive": "她表现出正向情绪",
    "emotion_negative": "她表现出负向情绪",
    "flirt": "她有暧昧、调侃或撒娇",
    "question_asking": "她主动提问",
    "self_disclosure": "她主动分享个人信息",
    "invitation": "她邀约或积极回应邀约",
    "framing_boundary": "她使用朋友/兄弟等关系框架词汇",
    "perfunctory": "她敷衍回应",
}

LABEL_INDEX = "\n".join(f"{i+1}. {l}: {LABEL_DESC[l]}" for i, l in enumerate(LABELS))

BATCH_SIZE = 10


def build_batch_prompt(batch_samples):
    """构建一个 batch 的 prompt，包含多段对话。"""
    role_map = {"her": "她", "me": "我"}

    dialogues = []
    for idx, sample in enumerate(batch_samples):
        dialog = "\n".join(
            "- [" + role_map.get(m["role"], m["role"]) + "] " + m["content"].replace(chr(10), " ")
            for m in sample["messages"]
        )
        dialogues.append(f"对话{idx+1}：\n{dialog}")

    all_dialogues = "\n\n".join(dialogues)

    return (
        f"以下是 {len(batch_samples)} 段微信聊天记录。对每段对话中「她」的行为表现进行独立评分。\n\n"
        "标签（按顺序）：\n"
        + LABEL_INDEX + "\n\n"
        "评分范围：0-9 整数，每标签独立评分，互不影响。\n"
        "强度锚点（所有标签通用）：\n"
        "  0 = 完全不存在，没有任何迹象\n"
        "  1-2 = 极弱，勉强能感受到一丁点\n"
        "  3-4 = 较弱，偶尔出现一两处\n"
        "  5-6 = 中等，明确出现但不是全程贯穿\n"
        "  7-8 = 较强，多次明显体现\n"
        "  9 = 极强，非常典型或贯穿整个对话\n"
        "评分时综合「出现频率」和「典型程度」：频率高且典型 → 高分；频率低或不典型 → 低分。\n\n"
        + all_dialogues + "\n\n"
        "对每段对话按标签顺序输出评分，用 | 分隔 10 个值。\n"
        f"将 {len(batch_samples)} 段对话的评分放在 <<<<< 和 >>>>> 之间，每行一段，顺序与上文对话编号一致。\n"
        "示例（3段对话，每段10个值）：\n"
        "<<<<<\n"
        "0|3|5|0|0|1|7|0|0|0\n"
        "5|7|2|0|0|3|1|0|0|0\n"
        "1|4|6|0|0|2|3|0|0|0\n"
        ">>>>>"
    )


def parse_batch_response(response, expected_count):
    """从 <<<<< 和 >>>>> 之间提取每行 | 分隔值。"""
    if not response:
        return None

    start = response.find("<<<<<")
    end = response.find(">>>>>")

    if start >= 0 and end > start:
        text = response[start + 5:end].strip()
    else:
        # fallback: 找包含 | 的行
        lines = [l.strip() for l in response.strip().split("\n") if l.strip() and "|" in l]
        text = "\n".join(lines) if lines else response.strip()

    lines = [l.strip() for l in text.split("\n") if l.strip() and "|" in l]

    if len(lines) < expected_count:
        return None

    results = []
    for line in lines[:expected_count]:
        parts = line.replace(" ", "").replace("\t", "").split("|")
        parts = [p.strip() for p in parts if p.strip()]
        if len(parts) != len(LABELS):
            return None
        try:
            values = [int(p) for p in parts]
            if not all(0 <= v <= 9 for v in values):
                return None
            results.append({l: values[i] for i, l in enumerate(LABELS)})
        except (ValueError, IndexError):
            return None

    return results


class HuggingFaceAnnotator:
    def __init__(self, model_name="Qwen/Qwen3-14B"):
        self.model_name = model_name
        self.model = None
        self.tokenizer = None
        self.device = None

    def _load(self):
        if self.model is not None:
            return
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        print("[LOG] Loading tokenizer...", flush=True)
        self.tokenizer = AutoTokenizer.from_pretrained(self.model_name)

        print("[LOG] Loading model...", flush=True)
        t0 = time.time()
        self.model = AutoModelForCausalLM.from_pretrained(
            self.model_name,
            device_map="auto",
            dtype=torch.bfloat16,
        )
        self.model.eval()
        self.device = self.model.device

        param_dtype = next(self.model.parameters()).dtype
        mem = torch.cuda.memory_allocated() / 1024**3
        total_mem = torch.cuda.get_device_properties(0).total_memory / 1024**3
        print(f"[LOG] Model loaded: device={self.device}, dtype={param_dtype}, "
              f"load_time={time.time()-t0:.1f}s, cuda_mem={mem:.1f}GiB/{total_mem:.1f}GiB", flush=True)

    def annotate_batch(self, prompt):
        self._load()
        import torch

        try:
            inputs = self.tokenizer(prompt, return_tensors="pt").to(self.device)
            input_len = inputs["input_ids"].shape[1]

            t0 = time.time()
            with torch.no_grad():
                outputs = self.model.generate(
                    **inputs,
                    max_new_tokens=1200,
                    temperature=0.1,
                    top_p=0.9,
                    pad_token_id=self.tokenizer.eos_token_id,
                    eos_token_id=self.tokenizer.eos_token_id,
                )
            t_gen = time.time() - t0

            output_len = outputs.shape[1] - input_len
            resp = self.tokenizer.decode(outputs[0][input_len:], skip_special_tokens=True)

            print(f"[LOG] gen_time={t_gen:.1f}s, input={input_len}tok, output={output_len}tok", flush=True)
            return resp

        except Exception as e:
            print(f"[ERROR] HF annotate exception: {e}", flush=True)
            import traceback
            traceback.print_exc(file=sys.stderr)
            return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--hf", action="store_true")
    parser.add_argument("--input", default=None)
    parser.add_argument("--output", default=None)
    parser.add_argument("--batch_size", type=int, default=BATCH_SIZE)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent.parent
    dataset_dir = project_root / "data" / "ml_dataset"
    input_path = Path(args.input) if args.input else dataset_dir / "samples_phase0.jsonl"
    output_path = Path(args.output) if args.output else dataset_dir / "annotations_phase1.jsonl"

    print(f"[LOG] input={input_path}", flush=True)
    print(f"[LOG] output={output_path}", flush=True)

    with open(input_path, "r", encoding="utf-8") as f:
        samples = [json.loads(line) for line in f if line.strip()]

    if args.limit:
        samples = samples[:args.limit]
        print(f"[LOG] Limited to {args.limit} samples", flush=True)

    # 加载已完成的标注（断点续传）
    existing = set()
    if output_path.exists():
        with open(output_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    existing.add(json.loads(line)["sample_id"])

    # 过滤已完成，剩余分批
    remaining = [s for s in samples if s["sample_id"] not in existing]
    batches = [remaining[i:i + args.batch_size] for i in range(0, len(remaining), args.batch_size)]

    print(f"[LOG] Total: {len(samples)}, Done: {len(existing)}, Remaining: {len(remaining)}", flush=True)
    print(f"[LOG] Batches: {len(batches)} (batch_size={args.batch_size})", flush=True)

    if not remaining:
        print("[LOG] All done!", flush=True)
        return

    annotator = HuggingFaceAnnotator() if args.hf else None
    if annotator is None:
        print("[ERROR] Only --hf mode supported", flush=True)
        return

    success_count = 0
    fail_count = 0
    total_gen_time = 0.0

    with open(output_path, "a", encoding="utf-8") as f:
        for bi, batch in enumerate(batches):
            batch_ids = [s["sample_id"] for s in batch]
            print(f"\n[Batch {bi+1}/{len(batches)}] {len(batch)} samples: {', '.join(batch_ids[:3])}{'...' if len(batch_ids)>3 else ''}", flush=True)

            prompt = build_batch_prompt(batch)

            labels_list = None
            for attempt in range(3):
                t_start = time.time()
                resp = annotator.annotate_batch(prompt)
                elapsed = time.time() - t_start

                if resp:
                    labels_list = parse_batch_response(resp, len(batch))
                    if labels_list:
                        print(f"  attempt {attempt+1}/3 OK ({elapsed:.1f}s) ✓", flush=True)
                        total_gen_time += elapsed
                        break
                    else:
                        print(f"  attempt {attempt+1}/3 PARSE FAIL ({elapsed:.1f}s)", flush=True)
                        print(f"    raw ({len(resp)}c): {resp[:200]}", flush=True)
                else:
                    print(f"  attempt {attempt+1}/3 GEN FAIL ({elapsed:.1f}s)", flush=True)

            if labels_list:
                for sample, labels in zip(batch, labels_list):
                    result = {
                        "sample_id": sample["sample_id"],
                        "contact_wxid": sample.get("contact_wxid", ""),
                        "labels": labels,
                    }
                    f.write(json.dumps(result, ensure_ascii=False) + "\n")
                    success_count += 1
                f.flush()
            else:
                print(f"  => ALL 3 FAILED for batch {bi+1}", flush=True)
                fail_count += len(batch)

            # 进度摘要
            total_done = len(existing) + success_count + fail_count
            print(f"  Progress: {total_done}/{len(samples)} ({total_done*100//len(samples)}%)", flush=True)

    avg_time = total_gen_time / max(len(batches), 1)
    print(f"\n=== DONE ===", flush=True)
    print(f"Success: {success_count}, Failed: {fail_count}, Batches: {len(batches)}, Avg batch time: {avg_time:.1f}s", flush=True)


if __name__ == "__main__":
    main()
