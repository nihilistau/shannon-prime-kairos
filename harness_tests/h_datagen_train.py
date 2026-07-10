"""G-DF-TRAIN (DF-B3, smoke) — the mem_class LoRA training pipeline end-to-end on our data.

Generates a seed, holds out a slice, trains a tiny LoRA over Qwen2.5-0.5B-Instruct (cached), saves
the adapter, reloads it, and classifies the held-out. PASS = trained + saved + loaded + produces
valid labels + learns (accuracy above chance). Pipeline proof, NOT a generalization benchmark
(eval shares templates with train by augmentation). The real run is bigger (Colab/RunPod), same code.
"""
from __future__ import annotations

import json
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datagen import seed_mem_class as S
from datagen import finetune_mem_class as F


def main() -> int:
    random.seed(7)
    ex = S.generate(30)          # 180 balanced examples
    random.shuffle(ex)
    held, train = ex[:12], ex[12:]

    F.DATASETS_DIR.mkdir(parents=True, exist_ok=True)
    (F.DATASETS_DIR / "mem_class_combined.jsonl").write_text(
        "\n".join(json.dumps(e) for e in train) + "\n", encoding="utf-8")

    r = F.finetune(dataset_name="mem_class", epochs=6.0, max_steps=60, out_name="mem_class_smoke")
    print("train:", {k: r.get(k) for k in ["ok", "n_examples", "final_loss", "base_model"]})
    if not r.get("ok"):
        print(f"RESULT df-train: FAIL ({r.get('error')})")
        return 1

    adapter = r["adapter_path"]
    saved_ok = os.path.exists(os.path.join(adapter, "adapter_config.json"))
    ev = F.evaluate(adapter, held)
    print("eval:", {k: ev[k] for k in ["n", "correct", "valid_labels", "accuracy"]})
    for stmt, gold, pred in ev["preds"]:
        print(f"    {gold:16s} <- pred={pred!s:16s} | {stmt!r}")

    ok = (r.get("ok") and saved_ok and ev["valid_labels"] == ev["n"] and ev["accuracy"] >= 0.5)
    print(f"RESULT df-train: {'PASS' if ok else 'FAIL'} "
          f"(trained+saved={saved_ok} loaded+valid={ev['valid_labels']}/{ev['n']} acc={ev['accuracy']:.2f})")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
