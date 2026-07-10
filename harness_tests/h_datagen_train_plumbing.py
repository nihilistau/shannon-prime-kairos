"""G-DF-TRAIN-PLUMBING (DF-B3, data path) — verifies the trainer's DATA pipeline without loading
the heavy ML stack (torch/trl are imported lazily inside finetune(), so this runs in ms). Proves
_load_dataset, the training-text format, and the label parser are correct. The actual LoRA training
runs on the Colab/RunPod lane (the local transformers-5.5/trl-1.7 env import is hung/corrupted —
see G-DF-TRAIN.log honest-negative)."""
from __future__ import annotations

import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datagen import seed_mem_class as S
from datagen import finetune_mem_class as F


def main() -> int:
    random.seed(7)
    ex = S.generate(30)
    F.DATASETS_DIR.mkdir(parents=True, exist_ok=True)
    (F.DATASETS_DIR / "mem_class_combined.jsonl").write_text(
        "\n".join(json.dumps(e) for e in ex) + "\n", encoding="utf-8")

    # 1) _load_dataset picks up combined
    rows = F._load_dataset("mem_class")
    load_ok = len(rows) == len(ex)

    # 2) training text: prompt + statement + label + eos, label recoverable
    sample = {"instruction": "My PIN is 4-7-2-9.", "output": "private-secret"}
    text = F._text(sample, "<eos>")
    text_ok = ("My PIN is 4-7-2-9." in text and text.rstrip("<eos>").endswith("private-secret")
               and "Classify the memory" in text)

    # 3) label parser handles clean + noisy generations (private-secret before persona/fact)
    cases = {
        "private-secret": "private-secret",
        " persona": "persona",
        "the label is counterfact.": "counterfact",
        "Label: fact": "fact",
        "episodic-event\nMemory:": "episodic-event",
        "preference": "preference",
        "banana": None,
    }
    parse_ok = all(F._parse_label(g) == exp for g, exp in cases.items())

    print(f"load_ok={load_ok} ({len(rows)} rows)  text_ok={text_ok}  parse_ok={parse_ok}")
    print(f"  sample text: {text!r}")
    ok = load_ok and text_ok and parse_ok
    print(f"RESULT df-train-plumbing: {'PASS' if ok else 'FAIL'} "
          f"(dataset load + train-text format + label parser)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
