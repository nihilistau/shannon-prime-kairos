#!/usr/bin/env python
"""sem_wc_score.py — the learned selector's scoreboard (the last open contender for the
recall-quality gap; INVARIANT-ROADMAP successor of G-SEM-SCOREBOARD's Phase 3).

The contender: the W_c + (E+1)-NULL head (G-CHAT-B3-WC-DIV2: 360/361 recall + 50/50
foreign reject on the curated corpus), exposed read-only at /v1/recall_rank. The
HONESTY FLAG carried from the engine's own comments: W_c is geometric — strong on
high-entropy novel needles, measured BLIND on mutually-similar natural facts. THIS
corpus is natural personal facts. A negative here is a result, not a failure.

PRE-REGISTERED SHIP BAR (same as every SEM contender, declared before the first run):
    paraphrase hit rate (picked == expected, NULL = miss)  >  0.06   (the lexical decider)
    foreign precision  (picked == NULL)                    >= 0.98

LIVE: needs `python serve.py agent` up and the corpus episode dirs
(var/sem/l5eps/<addr>, built by sem_l5_corpus.py). The deploy blob rides in the request.
"""
import json
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FIX = os.path.join(HERE, "fixtures", "sem")
sys.path.insert(0, ROOT)
DAEMON = os.environ.get("SP_DAEMON_URL", "http://127.0.0.1:3000")
WC = os.environ.get("SP_WC_BLOB",
                    r"D:\F\shannon-prime-repos\shannon-prime-system-engine\_b3_wc\wc_deploy.bin")
EPS = os.path.join(ROOT, "var", "sem", "l5eps")

from harness.skills import semindex as SX                # noqa: E402

BAR = {"hit": 0.06, "foreign_precision": 0.98}


def rank(text, dirs):
    body = json.dumps({"text": text, "episode_dirs": dirs, "wc_path": WC}).encode()
    req = urllib.request.Request(DAEMON + "/v1/recall_rank", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read().decode())


def main():
    with open(os.path.join(FIX, "paraphrase.jsonl"), encoding="utf-8") as f:
        paras = [json.loads(x) for x in f if x.strip()]
    with open(os.path.join(FIX, "foreign.jsonl"), encoding="utf-8") as f:
        foreign = [json.loads(x)["q"] for x in f if x.strip()]

    addrs = sorted(a for a in os.listdir(EPS)
                   if os.path.isfile(os.path.join(EPS, a, "ep.k")))
    dirs = [os.path.join(EPS, a).replace("\\", "/") for a in addrs]
    print("candidates: %d episode dirs" % len(dirs))

    hit = argmax_hit = null_on_para = 0
    t0 = time.time()
    for i, p in enumerate(paras):
        want = SX.addr_of(p["expect_text"])
        r = rank(p["q"], dirs)
        picked = r.get("picked")
        if picked is None:
            null_on_para += 1
        elif addrs[picked] == want:
            hit += 1
        scores = [(-1e30 if s is None else s, j) for j, s in enumerate(r["scores"])]
        if addrs[max(scores)[1]] == want:
            argmax_hit += 1
        if (i + 1) % 25 == 0:
            print("  %d/%d paraphrase (%.0fs)" % (i + 1, len(paras), time.time() - t0))

    rejects = 0
    for i, q in enumerate(foreign):
        if rank(q, dirs).get("picked") is None:
            rejects += 1
        if (i + 1) % 20 == 0:
            print("  %d/%d foreign (%.0fs)" % (i + 1, len(foreign), time.time() - t0))

    n, m = len(paras), len(foreign)
    metrics = {
        "wc_hit_rate": round(hit / n, 4),                     # picked==expected (NULL=miss)
        "wc_argmax_rate": round(argmax_hit / n, 4),           # ranking-only quality
        "wc_null_on_paraphrase": round(null_on_para / n, 4),  # over-rejection
        "foreign_precision": round(rejects / m, 4),           # NULL on foreign = correct
    }
    ships = metrics["wc_hit_rate"] > BAR["hit"] \
        and metrics["foreign_precision"] >= BAR["foreign_precision"]
    receipt = {
        "name": "sem_wc_score", "bar": BAR, "wc_blob": WC,
        "candidates": len(dirs), "metrics": metrics, "ships": ships,
        "pass": 1 if ships else 0, "fail": 0 if ships else 1,
        "baseline_decider_hit_rate": 0.06,
        "note": ("SHIPS: the learned selector beats the lexical decider at precision"
                 if ships else
                 "does not clear the pre-registered bar on natural personal facts — "
                 "consistent with the engine's own F2b honesty flag; this negative is "
                 "the receipt"),
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    rdir = os.path.join(ROOT, "var", "sem", "receipts")
    os.makedirs(rdir, exist_ok=True)
    with open(os.path.join(rdir, "sem_wc_score.json"), "w", encoding="utf-8") as f:
        json.dump(receipt, f, indent=2)
    if "--freeze" in sys.argv:
        with open(os.path.join(FIX, "wc-receipt.json"), "w", encoding="utf-8") as f:
            json.dump(receipt, f, indent=2)
        print("receipt frozen: fixtures/sem/wc-receipt.json")

    print("W_C SCOREBOARD  (bar: hit>%.2f, foreign>=%.2f)" %
          (BAR["hit"], BAR["foreign_precision"]))
    for k, v in metrics.items():
        print("  %-26s %s" % (k, v))
    print("  ships: %s - %s" % (ships, receipt["note"]))


if __name__ == "__main__":
    main()
