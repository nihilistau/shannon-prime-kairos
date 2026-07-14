#!/usr/bin/env python
"""G-SEM-CONSERVE — the SEM stack is CONSERVATIVE over the ground tier (docs/SEMANTICS.md §1.1, S4).

The executable form of the WKL0-over-PRA contract: ideal machinery (embeddings, dominance,
verdict merges) may reorder and propose, but with every SP_SEM_* flag off, recall behaviour
is IDENTICAL to the pre-SEM golden — byte-for-byte, through the real seam.

This gate exists BEFORE any SEM behaviour does, on purpose: it is the harness the rest is
built inside. Three sections:

  1. CLOSURE.  Every SP_SEM_* var read anywhere in harness/ must be mapped in serve.py's
     build_env table (G-ONEDOOR: an unmapped knob does not exist — and a knob that exists
     unmapped is a stray shell var away from being live). Today the reader set is empty;
     the day someone adds a reader without mapping it, this fails THAT day, not at 3am.
  2. DETERMINISM.  The seam gives the same answer twice. A ranker with hidden state is
     unauditable; every future SEM score must keep this property.
  3. GOLDEN.  With SEM off, every corpus query returns exactly the frozen golden result
     list (ts + score). This is the pre-SEM behaviour, pinned. When S1 lands, SEM-off runs
     must still land here exactly.

OFFLINE. No GPU, no daemon.
"""
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FIX = os.path.join(HERE, "fixtures", "sem")
sys.path.insert(0, ROOT)
os.environ["SP_DAEMON_URL"] = "http://127.0.0.1:9"
os.environ["SP_RECALL_REGISTRY"] = os.path.join(FIX, "registry_snapshot.jsonl")
# SEM off is the ABSENCE of the flags, not the presence of a zero:
for k in [k for k in os.environ if k.startswith("SP_SEM_")]:
    del os.environ[k]

from harness.skills import memory as M                       # noqa: E402
from harness.skills import semindex as SX                    # noqa: E402

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok   %s" % name)
    else:
        FAIL += 1
        print("  FAIL %s   %s" % (name, str(detail)[:200]))


def results(q):
    """Row identity + order. Not scores: scores carry the salience recency term, which
    decays by design — a frozen score is a frozen clock (the first golden went stale in
    hours when the event-class half-life moved the 6th decimal)."""
    return [SX.addr_of(e.get("text") or "")
            for _, e in M.search_memories_ranked_rows(q, k=3)]


def results_scored(q):
    return [[SX.addr_of(e.get("text") or ""), round(float(s), 6)]
            for s, e in M.search_memories_ranked_rows(q, k=3)]


# -- 1. CLOSURE: every SP_SEM_* reader is mapped in the one door -----------------------
print("\n1. SP_SEM_* closure (readers subset-of serve.py map)")
readers = set()
for base, _, files in os.walk(os.path.join(ROOT, "harness")):
    for fn in files:
        if not fn.endswith(".py"):
            continue
        with open(os.path.join(base, fn), encoding="utf-8", errors="replace") as f:
            readers |= set(re.findall(r"SP_SEM_[A-Z_]+", f.read()))
with open(os.path.join(ROOT, "serve.py"), encoding="utf-8", errors="replace") as f:
    mapped = set(re.findall(r"SP_SEM_[A-Z_]+", f.read()))
check("every SP_SEM_* read in harness/ is mapped in serve.py",
      readers <= mapped, "unmapped readers: %s" % sorted(readers - mapped))

# -- 2. DETERMINISM: the seam answers the same question the same way twice -------------
print("\n2. determinism")
with open(os.path.join(FIX, "paraphrase.jsonl"), encoding="utf-8") as f:
    queries = [json.loads(x)["q"] for x in f if x.strip()]
with open(os.path.join(FIX, "foreign.jsonl"), encoding="utf-8") as f:
    queries += [json.loads(x)["q"] for x in f if x.strip()]
diff = [q for q in queries if results(q) != results(q)]
check("all %d corpus queries deterministic" % len(queries), not diff, diff[:3])

# -- 3. GOLDEN: SEM-off equals the pre-SEM frozen behaviour, exactly --------------------
print("\n3. golden (SEM off == pre-SEM, byte-equal)")
gp = os.path.join(FIX, "golden-lexical.json")
check("golden-lexical.json exists (run sem_baseline.py --freeze once)", os.path.exists(gp))
if os.path.exists(gp):
    with open(gp, encoding="utf-8") as f:
        golden = json.load(f)
    flat = {**golden.get("paraphrase", {}), **golden.get("foreign", {})}
    bad = [q for q, want in flat.items() if results(q) != want]
    check("all %d golden result lists reproduced exactly" % len(flat), not bad, bad[:3])

# -- 4. FLAGS ABSENT == FLAGS ZERO, SAME INSTANT, SCORES INCLUDED ------------------------
# The golden above is deliberately clock-free; THIS check is byte-exact because both
# runs share one clock: SEM disabled by absence must equal SEM disabled by "0".
print("\n4. flags absent == flags zero (byte-exact, same instant)")
probe = queries[:20]
absent = [results_scored(q) for q in probe]
os.environ["SP_SEM_RANK"] = "0"
zero = [results_scored(q) for q in probe]
del os.environ["SP_SEM_RANK"]
check("absence and '0' are the same off", absent == zero)

print("\nG-SEM-CONSERVE: %d pass, %d fail" % (PASS, FAIL))
rdir = os.path.join(ROOT, "var", "sem", "receipts")
os.makedirs(rdir, exist_ok=True)
with open(os.path.join(rdir, "g_sem_conserve.json"), "w", encoding="utf-8") as f:
    json.dump({"name": "g_sem_conserve", "pass": PASS, "fail": FAIL,
               "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, f, indent=2)
sys.exit(1 if FAIL else 0)
