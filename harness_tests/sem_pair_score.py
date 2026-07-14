#!/usr/bin/env python
"""sem_pair_score.py — the Phase C2 scoreboard: WHO may propose same-subject links,
measured on the committed pair corpus (fixtures/sem/pairs.jsonl: 20 positives, 20
negatives including deliberate shared-word-different-dimension traps).

PRE-REGISTERED SHIP BAR (declared before the first run, like every SEM scoreboard):
the order-frame proposer ships for live scanning iff, on the GAP ZONE (the pairs the
incumbent prose test abstains on entirely):
        precision >= 0.80   AND   recall >= 0.80
The cost asymmetry justifying 0.80 rather than 0.98: a wrong LINK silences one
inference while its fake-cover is live — one sentence, the same failure direction the
incumbent topic test accepts on purpose ("at worst she is quieter"). Compare: a wrong
RECALL admission (the S1 bar, 0.98) puts a wrong fact in her mouth. Different costs,
different bars, both written down before the measurement.

Proposers measured:
    prose      the incumbent: topic_of overlap >= 2 (testimony_wins's own relation)
    frame      the order-frame/emulation test (slots.frame_link) — structure, no meaning
    oracle     the greedy LLM judge (only if a daemon answers; else reported absent)
    combined   prose on its zone UNION frame on the gap zone — the system's total reach

OFFLINE (oracle column live-optional).
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FIX = os.path.join(HERE, "fixtures", "sem")
sys.path.insert(0, ROOT)
os.environ.setdefault("SP_DAEMON_URL", "http://127.0.0.1:9")

from harness.skills import lifecycle as lc                 # noqa: E402
from harness.skills import slots as SL                     # noqa: E402

BAR = {"precision": 0.80, "recall": 0.80}


def prose(a, b):
    return len(lc.topic_of(lc.strip_prefix(a)) & lc.topic_of(lc.strip_prefix(b))) >= 2


def stats(preds, rows):
    tp = sum(1 for p, r in zip(preds, rows) if p and r["link"])
    fp = sum(1 for p, r in zip(preds, rows) if p and not r["link"])
    fn = sum(1 for p, r in zip(preds, rows) if not p and r["link"])
    prec = tp / (tp + fp) if tp + fp else None
    rec = tp / (tp + fn) if tp + fn else None
    return {"tp": tp, "fp": fp, "fn": fn,
            "precision": round(prec, 4) if prec is not None else None,
            "recall": round(rec, 4) if rec is not None else None}


def main():
    with open(os.path.join(FIX, "pairs.jsonl"), encoding="utf-8") as f:
        rows = [json.loads(x) for x in f if x.strip()]
    gap = [r for r in rows if r["zone"] == "gap"]

    frame_all = [SL.frame_link(r["a"], r["b"])[0] for r in rows]
    prose_all = [prose(r["a"], r["b"]) for r in rows]
    combined = [p or (f and not p) for p, f in zip(prose_all, frame_all)]
    frame_gap = [SL.frame_link(r["a"], r["b"])[0] for r in gap]

    oracle_verdicts = None
    try:
        # Liveness probe with a pair the judge demonstrably answers (its own few-shot
        # NO case) — probing with corpus rows failed silently, because the first rows
        # are exactly the hard pairs where the judge drifts to prose and returns None.
        if SL.ask_oracle("The kitchen tap drips at night.",
                         "The car needs new tyres.") is not None:
            oracle_verdicts = [SL.ask_oracle(r["a"], r["b"]) for r in rows]
    except Exception:
        pass
    oracle_col = ([v == "same" for v in oracle_verdicts] if oracle_verdicts else None)
    # THE VETO HYPOTHESIS (the operator's combine-opposites): structure proposes
    # (recall 1.0), the oracle may only VETO — frame ∧ ¬(oracle says "different").
    veto_col = ([f and v != "different" for f, v in zip(frame_all, oracle_verdicts)]
                if oracle_verdicts else None)

    report = {
        "name": "sem_pair_score", "bar": BAR,
        "corpus": {"pairs": len(rows), "positives": sum(r["link"] for r in rows),
                   "gap_zone": len(gap)},
        "prose_incumbent_all": stats(prose_all, rows),
        "frame_all": stats(frame_all, rows),
        "frame_gap_zone": stats(frame_gap, gap),
        "combined_all": stats(combined, rows),
        "oracle_all": stats(oracle_col, rows) if oracle_col else "absent (no daemon)",
        "frame_with_oracle_veto_all": (stats(veto_col, rows) if veto_col
                                       else "absent (no daemon)"),
        "frame_with_oracle_veto_gap": (stats(
            [v for v, r in zip(veto_col, rows) if r["zone"] == "gap"], gap)
            if veto_col else "absent (no daemon)"),
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    g = report["frame_gap_zone"]
    ships = (g["precision"] or 0) >= BAR["precision"] and (g["recall"] or 0) >= BAR["recall"]
    report["ships"] = ships
    report["pass"], report["fail"] = (1, 0) if ships else (0, 1)
    report["note"] = ("SHIPS: frame proposer clears the pre-registered gap-zone bar"
                      if ships else
                      "does not clear the pre-registered bar — frame stays out of the "
                      "live scan; this negative is the receipt")

    rdir = os.path.join(ROOT, "var", "sem", "receipts")
    os.makedirs(rdir, exist_ok=True)
    with open(os.path.join(rdir, "sem_pair_score.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    if "--freeze" in sys.argv:
        with open(os.path.join(FIX, "pair-receipt.json"), "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        print("receipt frozen: fixtures/sem/pair-receipt.json")

    print("C2 PAIR SCOREBOARD  (bar: gap precision>=%.2f recall>=%.2f)" %
          (BAR["precision"], BAR["recall"]))
    for k in ("prose_incumbent_all", "frame_all", "frame_gap_zone", "combined_all",
              "oracle_all", "frame_with_oracle_veto_all", "frame_with_oracle_veto_gap"):
        print("  %-28s %s" % (k, report[k]))
    if oracle_verdicts:
        for r, v in zip(rows, oracle_verdicts):
            if (v == "different") == r["link"]:      # veto killing a TP, or blessing an FP
                print("    oracle %s on %s pair: %r / %r" % (
                    v, "LINKED" if r["link"] else "unlinked", r["a"][:36], r["b"][:36]))
    print("  ships: %s — %s" % (ships, report["note"]))
    for r, f, p in zip(rows, frame_all, prose_all):
        if f != r["link"]:
            print("    frame %s: %r / %r  (%s)" % (
                "FP" if f else "FN", r["a"][:38], r["b"][:38], r["note"][:40]))


if __name__ == "__main__":
    main()
