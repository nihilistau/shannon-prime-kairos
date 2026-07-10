"""G-DF-CONVERT (DF-B1) — the telemetry -> labelled JSONL converter, and its privacy choke point.

Builds a synthetic telemetry corpus (clear counterfact + persona records, a normal redacted
private-secret, AND an adversarial 'redacted-but-carries-secret-text' record), runs the converter,
and verifies: correct {query->mem_class} examples, decision+turn dedup, redacted records SKIPPED,
and the secret text NEVER reaches the JSONL (0 hits). Pure data-transform unit gate — no daemon.
"""
from __future__ import annotations

import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datagen import prepare_from_telemetry as P

CORPUS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_datagen_gate")
SECRET = "orchid tango falcon delta"


def _write(recs):
    recdir = os.path.join(CORPUS, "records")
    if os.path.isdir(CORPUS):
        shutil.rmtree(CORPUS)
    os.makedirs(recdir)
    for i, r in enumerate(recs):
        with open(os.path.join(recdir, f"{i:016x}.json"), "w", encoding="utf-8") as f:
            f.write(json.dumps(r))


def main() -> int:
    recs = [
        # clear counterfact — decision + turn for the SAME query (must dedup to 1 example)
        {"ts": 1, "query": "What is the chemical symbol for gold now?", "redacted": False,
         "recall": {"class": "counterfact", "delivery": "systemecho", "decision": "deliver"}},
        {"ts": 1, "kind": "turn", "query": "What is the chemical symbol for gold now?", "redacted": False,
         "turn": {"class": "counterfact", "output": "The chemical symbol for gold is Xg.", "obeyed": True}},
        # clear persona
        {"ts": 2, "query": "What is my name?", "redacted": False,
         "recall": {"class": "persona", "delivery": "system", "decision": "deliver"}},
        {"ts": 2, "kind": "turn", "query": "What is my name?", "redacted": False,
         "turn": {"class": "persona", "output": "My name is Aldric Vance.", "obeyed": True}},
        # normal redacted private-secret (hashed query, no text) — SKIP
        {"ts": 3, "query": "#0d9a9c8f29af05f1", "redacted": True,
         "recall": {"class": "private-secret", "delivery": "recite", "decision": "deliver"}},
        # ADVERSARIAL: flagged redacted but (wrongly) carries the secret text — the guard MUST skip it
        {"ts": 4, "kind": "turn", "query": f"the phrase is {SECRET}", "redacted": True,
         "turn": {"class": "private-secret", "output": f"The recovery phrase is {SECRET}.", "obeyed": True}},
    ]
    _write(recs)

    out_path = os.path.join(os.path.dirname(P.__file__), "datasets", "mem_class_live.jsonl")
    if os.path.exists(out_path):
        os.remove(out_path)

    n = P.prepare_dataset(corpus_root=CORPUS, dataset_name="mem_class")
    lines = [l for l in open(out_path, encoding="utf-8").read().splitlines() if l.strip()]
    examples = [json.loads(l) for l in lines]
    labels = {(e["instruction"], e["output"]) for e in examples}

    expected = {
        ("What is the chemical symbol for gold now?", "counterfact"),
        ("What is my name?", "persona"),
    }
    count_ok = (n == 2 and len(examples) == 2)
    labels_ok = (labels == expected)
    leak = sum(1 for l in lines if "orchid" in l.lower())
    fmt_ok = all(set(e.keys()) == {"instruction", "output"} for e in examples)
    # idempotent re-run
    n2 = P.prepare_dataset(corpus_root=CORPUS, dataset_name="mem_class")
    dedup_ok = (n2 == 2)

    print(f"examples={n} (expect 2)  labels_ok={labels_ok}  fmt_ok={fmt_ok}  rerun={n2}")
    print(f"REDACTION: secret {SECRET!r} in mem_class_live.jsonl = {leak} -> {'PASS' if leak == 0 else 'FAIL'}")
    for e in examples:
        print("  ", e)
    ok = count_ok and labels_ok and leak == 0 and fmt_ok and dedup_ok
    print(f"RESULT df-convert: {'PASS' if ok else 'FAIL'} "
          f"(clear examples + labels + redacted-skipped + no-secret + dedup)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
