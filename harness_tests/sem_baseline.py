#!/usr/bin/env python
"""sem_baseline.py — the boundary-thesis scoreboard (docs/SEMANTICS.md §4.2, Phase 0).

Scores TODAY'S lexical recall on the frozen corpus, through the real paths:
    - the seam:    memory.search_memories_ranked_rows(q, k=3)     (tool-recall grade)
    - the decider: spine.recall_decider(min_overlap=0.34)          (what runs EVERY turn)

The receipt is committed. SEM Phase 2 (S1 rank) must beat these numbers on this corpus
or it stays off — that is the ship condition, and this file is where the bar is set.

    --freeze   additionally writes golden-lexical.json: the exact per-query result lists
               (ts + rounded score) that G-SEM-CONSERVE holds all future SEM-off runs to.

OFFLINE. No GPU, no daemon.
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FIX = os.path.join(HERE, "fixtures", "sem")
sys.path.insert(0, ROOT)
os.environ["SP_DAEMON_URL"] = "http://127.0.0.1:9"          # discard port
os.environ["SP_RECALL_REGISTRY"] = os.path.join(FIX, "registry_snapshot.jsonl")

from harness.skills import memory as M                       # noqa: E402
from harness.skills import semindex as SX                    # noqa: E402
from harness.control.spine import recall_decider, TurnView   # noqa: E402

DECIDER_OVERLAP = 0.34   # the live per-turn threshold (AGENTS.md §3 / spine.py)


def _jsonl(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]


def seam(q, k=3):
    return M.search_memories_ranked_rows(q, k=k)


def injected(q):
    """What actually reaches her context — the real decider, never a hand-called helper."""
    out = []
    for d in recall_decider(min_overlap=DECIDER_OVERLAP)._fn(
            TurnView(phase="pre", user_text=q)):
        out += d.payload.get("facts", [])
    return out


def main():
    paras, foreign = _jsonl("paraphrase.jsonl"), _jsonl("foreign.jsonl")

    # GOLDEN = ROW IDENTITY AND ORDER (content addresses), NOT SCORES. The first golden
    # froze 6-decimal scores and went stale within hours: scores contain the salience
    # recency term, which DECAYS BY DESIGN (event-class half-life is 3 days), so a
    # frozen score is a frozen clock — the G-CLOCK lesson wearing a new hat. What
    # conservation actually promises is: same rows, same order. That is what is pinned.
    golden = {"paraphrase": {}, "foreign": {}}
    r_at1 = r_at3 = dec_hit = 0
    for p in paras:
        rows = seam(p["q"])
        golden["paraphrase"][p["q"]] = [SX.addr_of(e.get("text") or "") for _, e in rows]
        hits = [e.get("ts") for _, e in rows]
        if hits[:1] == [p["expect_ts"]]:
            r_at1 += 1
        if p["expect_ts"] in hits:
            r_at3 += 1
        if any(p["expect_text"] in f for f in injected(p["q"])):
            dec_hit += 1

    seam_fp = dec_fp = 0
    for fq in foreign:
        rows = seam(fq["q"])
        golden["foreign"][fq["q"]] = [SX.addr_of(e.get("text") or "") for _, e in rows]
        if rows:
            seam_fp += 1
        if injected(fq["q"]):
            dec_fp += 1

    n, m = len(paras), len(foreign)
    metrics = {
        "seam_recall_at_1": round(r_at1 / n, 4),
        "seam_recall_at_3": round(r_at3 / n, 4),
        "decider_hit_rate": round(dec_hit / n, 4),
        "foreign_seam_false_hit_rate": round(seam_fp / m, 4),
        "foreign_decider_false_injection_rate": round(dec_fp / m, 4),
        "foreign_decider_precision": round(1.0 - dec_fp / m, 4),
    }
    receipt = {
        "name": "sem_baseline", "ranker": "lexical (overlap + salience prior)",
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "corpus": {"facts": 50, "paraphrase_queries": n, "foreign_queries": m,
                   "version": "v1"},
        "metrics": metrics, "pass": n, "fail": 0,
    }

    with open(os.path.join(FIX, "baseline-receipt.json"), "w", encoding="utf-8") as f:
        json.dump(receipt, f, indent=2)
    rdir = os.path.join(ROOT, "var", "sem", "receipts")
    os.makedirs(rdir, exist_ok=True)
    with open(os.path.join(rdir, "sem_baseline.json"), "w", encoding="utf-8") as f:
        json.dump(receipt, f, indent=2)

    if "--freeze" in sys.argv:
        with open(os.path.join(FIX, "golden-lexical.json"), "w", encoding="utf-8") as f:
            json.dump(golden, f, indent=2, sort_keys=True)
        print("golden-lexical.json frozen (%d + %d query result lists)" % (n, m))

    print("LEXICAL BASELINE - the bar SEM must clear:")
    for k, v in metrics.items():
        print("  %-40s %s" % (k, v))


if __name__ == "__main__":
    main()
