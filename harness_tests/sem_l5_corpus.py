#!/usr/bin/env python
"""sem_l5_corpus.py — capture the frozen corpus facts through the LIVE engine so the
scoreboard can measure l5-space (docs/SEMANTICS.md §4.3 resolved, Phase 2).

For each snapshot fact: POST /v1/capture into var/sem/l5eps/<addr>/ (the daemon mints
ep.l5 there when SP_CAPTURE_L5=1 — the new seam), then append the l5-space index row
via the real semindex.mint(). Prints a cosine sanity line for the first few paraphrase
pairs so a dead signal is visible before the full scoreboard spends minutes.

LIVE: needs `python serve.py agent` up. Writes only var/sem/ artifacts.
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
EPS = os.path.join(ROOT, "var", "sem", "l5eps")
IDX = os.path.join(ROOT, "var", "sem", "scoreboard_index.jsonl")
os.environ["SP_SEM_MINT"] = "1"
os.environ["SP_SEM_INDEX"] = IDX

from harness.skills import semindex as SX      # noqa: E402


def post(path, obj, timeout=180):
    req = urllib.request.Request(DAEMON + path, data=json.dumps(obj).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def main():
    rows = [json.loads(x) for x in open(os.path.join(FIX, "registry_snapshot.jsonl"),
                                        encoding="utf-8") if x.strip()]
    rows = [r for r in rows if not r.get("lifecycle") and r.get("text")]
    if os.path.exists(IDX):
        os.remove(IDX)                          # scoreboard artifact, not memory
    os.makedirs(EPS, exist_ok=True)

    minted_l5 = minted_hash = 0
    t0 = time.time()
    for i, r in enumerate(rows):
        addr = SX.addr_of(r["text"])
        out_dir = os.path.join(EPS, addr).replace("\\", "/")
        try:
            post("/v1/capture", {"text": r["text"], "out_dir": out_dir})
        except Exception as e:
            print("  capture failed (%s): %s" % (addr, e))
        ok = SX.mint(r["text"], r.get("ts") or "", out_dir=out_dir)
        has_l5 = os.path.isfile(os.path.join(out_dir, "ep.l5"))
        minted_l5 += 1 if (ok and has_l5) else 0
        minted_hash += 1 if (ok and not has_l5) else 0
        if (i + 1) % 10 == 0:
            print("  %d/%d captured (%.0fs)" % (i + 1, len(rows), time.time() - t0))

    print("index rows: l5-space=%d hash-space=%d (hash means ep.l5 missing — check "
          "SP_CAPTURE_L5 on the daemon)" % (minted_l5, minted_hash))

    # cosine sanity: first 5 paraphrase pairs, l5 query vs l5 episode key
    paras = [json.loads(x) for x in open(os.path.join(FIX, "paraphrase.jsonl"),
                                         encoding="utf-8") if x.strip()][:5]
    idx = SX.load()
    print("\ncosine sanity (l5 query vs its fact's l5 key):")
    for p in paras:
        try:
            q = post("/v1/embed", {"text": p["q"]}, timeout=60).get("l5") or []
        except Exception as e:
            print("  embed failed: %s" % e)
            break
        row = idx.get((SX.addr_of(p["expect_text"]), p["expect_ts"] or ""))
        if row and row["model"] == SX.MODEL_L5 and q:
            print("  cos=%.4f  %-46s <- %s" % (SX.cosine(q, row["vec"]),
                                               p["expect_text"][:46], p["q"][:40]))
        else:
            print("  no l5 pair for: %s" % p["q"][:50])


if __name__ == "__main__":
    main()
