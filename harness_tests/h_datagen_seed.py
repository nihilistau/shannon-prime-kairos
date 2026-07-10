"""G-DF-SEED (DF-B2) — synthetic mem_class seed: balanced, all 6 classes incl private-secret,
Alpaca format, deterministic, and merges with the DF-B1 live tier into the combined trainer input.
"""
from __future__ import annotations

import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datagen import seed_mem_class as S
from datagen import prepare_from_telemetry as P

PER = 30
EXPECT_CLASSES = {"private-secret", "persona", "preference", "counterfact", "fact", "episodic-event"}


def main() -> int:
    random.seed(42)
    ex = S.generate(PER)
    st = S.stats(ex)
    classes_ok = set(st.keys()) == EXPECT_CLASSES
    balanced_ok = all(n == PER for n in st.values())
    fmt_ok = all(set(e.keys()) == {"instruction", "output"} for e in ex)
    secret_ok = st.get("private-secret", 0) == PER
    # determinism: regenerate with same seed -> identical
    random.seed(42)
    ex2 = S.generate(PER)
    deterministic = (ex == ex2)

    out = S.save(ex, "mem_class")
    # merge with the DF-B1 live tier (mem_class_live.jsonl) -> combined trainer input
    combined_n = P.merge_datasets("mem_class")
    live_n = P.get_dataset_stats("mem_class")["live"]

    print(f"classes={sorted(st.keys())}")
    print(f"per-class counts: {st}")
    print(f"total seed={len(ex)}  live={live_n}  combined={combined_n}")
    print(f"classes_ok={classes_ok} balanced_ok={balanced_ok} fmt_ok={fmt_ok} "
          f"secret_present={secret_ok} deterministic={deterministic}")
    # combined = unique(train + live); >= seed size, and >= seed+live-overlap
    merge_ok = combined_n >= len(ex)
    ok = classes_ok and balanced_ok and fmt_ok and secret_ok and deterministic and merge_ok
    print(f"RESULT df-seed: {'PASS' if ok else 'FAIL'} "
          f"(6 balanced classes + synthetic private-secret + Alpaca + deterministic + merges with live)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
