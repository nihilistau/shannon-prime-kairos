#!/usr/bin/env python
"""sem_rank_score.py — the S1 scoreboard (docs/SEMANTICS.md §6, Phase 2 ship condition).

Same corpus, same metrics, same real paths as sem_baseline.py — with SP_SEM_RANK=1.
The embedding space is whatever query_embed() can reach: hash256-v1 when the daemon is
down, l5-512-v1 when /v1/embed exists and answers. The receipt names the space, because
a number without its provenance is not a measurement.

Ship condition (SEMANTICS.md): decider_hit_rate must beat the lexical baseline (0.06)
AND foreign_decider_precision >= 0.98, or SP_SEM_RANK stays false and the negative is
committed. This script only measures; it flips nothing.

OFFLINE-safe. Uses the daemon if present.
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
os.environ["SP_CAPTURE_ASYNC"] = "0"
os.environ["SP_RECALL_REGISTRY"] = os.path.join(FIX, "registry_snapshot.jsonl")
os.environ["SP_SEM_MINT"] = "1"
os.environ["SP_SEM_INDEX"] = os.path.join(ROOT, "var", "sem", "scoreboard_index.jsonl")
os.environ["SP_SEM_RANK"] = "1"
os.environ.setdefault("SP_SEM_TAU", "0.60")

from harness.skills import memory as M                       # noqa: E402
from harness.skills import semindex as SX                    # noqa: E402
from harness.control.spine import recall_decider, TurnView   # noqa: E402


def _jsonl(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]


def injected(q):
    out = []
    for d in recall_decider(min_overlap=0.34)._fn(TurnView(phase="pre", user_text=q)):
        out += d.payload.get("facts", [])
    return out


def measure(paras, foreign):
    # JOIN BY ADDR, NOT TS: gen_corpus minted all 50 facts inside one second, so ts is
    # degenerate across the snapshot and a ts-join matches almost anything — it scored
    # seam@1 = 1.00 while the probe showed the wrong fact on top. Content address is
    # the join key everywhere else in SEM; it is the join key here too.
    r1 = r3 = dec = 0
    for p in paras:
        want = SX.addr_of(p["expect_text"])
        hits = M.search_memories_ranked_rows(p["q"], k=3)
        addrs = [SX.addr_of(e.get("text") or "") for _, e in hits]
        if addrs[:1] == [want]:
            r1 += 1
        if want in addrs:
            r3 += 1
        if any(p["expect_text"] in f for f in injected(p["q"])):
            dec += 1
    dec_fp = sum(1 for fq in foreign if injected(fq["q"]))
    n, m = len(paras), len(foreign)
    return {
        "seam_recall_at_1": round(r1 / n, 4),
        "seam_recall_at_3": round(r3 / n, 4),
        "decider_hit_rate": round(dec / n, 4),
        "foreign_decider_false_injection_rate": round(dec_fp / m, 4),
        "foreign_decider_precision": round(1.0 - dec_fp / m, 4),
    }


def main():
    # --keep-index: score the index sem_l5_corpus.py just built (l5-space). Default:
    # rebuild fresh from the snapshot (hash-space when no daemon).
    if "--keep-index" not in sys.argv:
        if os.path.exists(os.environ["SP_SEM_INDEX"]):
            os.remove(os.environ["SP_SEM_INDEX"])   # a SCOREBOARD artifact, not memory
        SX.backfill(_jsonl("registry_snapshot.jsonl"))
    space = sorted({r["model"] for r in SX.load().values()})

    # memoize query embeds ON DISK: the sweep re-scores 160 queries per tau, the embed
    # is the only expensive part, and a rerun should not pay for it twice. Keyed by
    # query text; the (vec, model) pair rides together so a hash-space fallback is
    # never mistaken for an l5 vector. The cache changes nothing but wall time.
    cache_p = os.path.join(ROOT, "var", "sem", "qembed_cache.json")
    try:
        with open(cache_p, encoding="utf-8") as f:
            _memo = {k: (v[0], v[1]) for k, v in json.load(f).items()
                     if v[1] == SX.MODEL_L5}       # never cache the fallback space
    except Exception:
        _memo = {}
    _real = SX.query_embed
    SX.query_embed = lambda q: _memo.setdefault(q, _real(q))

    paras, foreign = _jsonl("paraphrase.jsonl"), _jsonl("foreign.jsonl")
    with open(os.path.join(FIX, "baseline-receipt.json"), encoding="utf-8") as f:
        base = json.load(f)["metrics"]

    # tau sweep: the shipped tau is CHOSEN BY THE PRECISION FLOOR (>= 0.98), then by
    # hit rate — precision-first, per SEMANTICS.md S1. One tau = one full measurement.
    taus = ([float(t) for t in os.environ.get("SP_SEM_SWEEP", "").split(",") if t]
            or [0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.70, 0.80])
    sweep = {}
    for t in taus:
        os.environ["SP_SEM_TAU"] = str(t)
        sweep[str(t)] = measure(paras, foreign)
        print("  tau=%.2f  hit=%.2f  seam@1=%.2f  precision=%.4f" % (
            t, sweep[str(t)]["decider_hit_rate"], sweep[str(t)]["seam_recall_at_1"],
            sweep[str(t)]["foreign_decider_precision"]))
    ok_taus = [t for t in taus if sweep[str(t)]["foreign_decider_precision"] >= 0.98]
    best = (max(ok_taus, key=lambda t: sweep[str(t)]["decider_hit_rate"])
            if ok_taus else max(taus, key=lambda t: sweep[str(t)]["foreign_decider_precision"]))
    metrics = sweep[str(best)]
    beats = (metrics["decider_hit_rate"] > base["decider_hit_rate"]
             and metrics["foreign_decider_precision"] >= 0.98)
    receipt = {
        "name": "sem_rank_score", "space": space, "tau": best, "sweep": sweep,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "metrics": metrics,
        "baseline_decider_hit_rate": base["decider_hit_rate"],
        "ships": beats,
        "pass": 1 if beats else 0, "fail": 0 if beats else 1,
        "note": ("SHIP CONDITION MET at tau=%s — flip [sem].rank/tau with this receipt "
                 "in the commit" % best if beats else
                 "does not beat the baseline in this space — SP_SEM_RANK stays false; "
                 "this negative is the receipt"),
    }
    rdir = os.path.join(ROOT, "var", "sem", "receipts")
    os.makedirs(rdir, exist_ok=True)
    with open(os.path.join(rdir, "sem_rank_score.json"), "w", encoding="utf-8") as f:
        json.dump(receipt, f, indent=2)
    try:
        with open(cache_p, "w", encoding="utf-8") as f:
            json.dump({k: [v[0], v[1]] for k, v in _memo.items()
                       if v[1] == SX.MODEL_L5}, f)
    except Exception:
        pass
    print("S1 SCOREBOARD  space=%s  chosen tau=%s" % (space, best))
    for k, v in metrics.items():
        print("  %-42s %-8s (lexical: %s)" % (k, v, base.get(k, "-")))
    print("  ships: %s - %s" % (beats, receipt["note"]))


if __name__ == "__main__":
    main()
