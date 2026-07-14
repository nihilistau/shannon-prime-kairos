#!/usr/bin/env python
"""G-SEM-STABLE — verdicts are invariant under the PROVABLE class of transformations
(docs/INVARIANT-MEMORY.md §1.2: Friedman's invariant-maximality discipline, scaled to a
unit test).

A VERDICT here is what the correctness layer decides: WHICH rows are admitted for a
query (the set), and what the per-turn decider injects. RANK is not a verdict — recency
decay reordering admitted rows is the rank layer doing its job — so this gate asserts
SETS, never order.

The three invariances, each chosen from the provable class (finite order-preserving
transformations), each a theorem the order-type discipline must keep true:

  1. TIME TRANSLATION. Shift every time coordinate of every row back uniformly (30 days,
     then 400 — crossing the event and fact half-life boundaries on purpose). Order
     types among rows are unchanged, so verdicts must be unchanged: the system keys on
     the ORDER of events, never the calendar.
  2. FUTURE EXTENSION. Append unrelated facts (through the real writer). Verdicts about
     the past do not flip because the world grew, and the new rows never appear in old
     queries' results.
  3. UNRELATED RETIREMENT. Tombstone a row no old query involves. No old verdict moves.

What is deliberately NOT demanded (the tail-identity analogue — unaffordable):
invariance under REORDERING observations. What he said second superseding what he said
first is load-bearing; a memory invariant under observation order cannot learn.

Checks run twice: SEM off (flags absent — today's live behaviour) and, for §2/§3,
SEM on in hash-space (SP_SEM_RANK=1) — the invariances must survive the semantic gate.
(§1 is SEM-off only: the time shift breaks the (addr, ts) index join by construction,
which silently degrades SEM to lexical and would make the SEM-on check vacuous.)

OFFLINE. No GPU, no daemon.
"""
import calendar
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.environ["SP_DAEMON_URL"] = "http://127.0.0.1:9"
os.environ["SP_CAPTURE_ASYNC"] = "0"
_tmp = tempfile.mkdtemp(prefix="g_sem_stable_")
REG = os.path.join(_tmp, "reg.jsonl")
IDX = os.path.join(_tmp, "idx.jsonl")
open(REG, "w").close()
os.environ["SP_RECALL_REGISTRY"] = REG
for k in [k for k in os.environ if k.startswith("SP_SEM_")]:
    del os.environ[k]

from harness.skills import memory as M                      # noqa: E402
from harness.skills import semindex as SX                   # noqa: E402
from harness.control.spine import recall_decider, TurnView  # noqa: E402

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok   %s" % name)
    else:
        FAIL += 1
        print("  FAIL %s   %s" % (name, str(detail)[:200]))


def verdict(q):
    """The correctness layer's answer: admitted SET (k=10 decouples truncation from
    rank) + what the real per-turn decider injects. Sets and sorted tuples only."""
    seam = frozenset(SX.addr_of(e.get("text") or "")
                     for _, e in M.search_memories_ranked_rows(q, k=10))
    inj = []
    for d in recall_decider(min_overlap=0.34)._fn(TurnView(phase="pre", user_text=q)):
        inj += d.payload.get("facts", [])
    return (seam, tuple(sorted(inj)))


def shift_all(days):
    """Uniform order-preserving time translation of every time field on every row.
    gmtime/timegm only — the G-CLOCK law."""
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    rows = [json.loads(x) for x in open(REG, encoding="utf-8") if x.strip()]
    for r in rows:
        for f in ("ts", "first_seen", "last_seen", "minted_at", "superseded_at"):
            v = r.get(f)
            if not v:
                continue
            try:
                t = calendar.timegm(time.strptime(v, fmt))
                r[f] = time.strftime(fmt, time.gmtime(t - days * 86400))
            except Exception:
                pass
    with open(REG, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


FACTS = [
    "Knack's front gate is painted teal",
    "Knack's favourite soup is laksa",
    "Knack's daughter has a piano recital in spring",
    "Knack is wary of magpies in September",
]
SELF_FACTS = ["I am fond of foggy mornings"]
QUERIES = [
    "what colour is his front gate",
    "what soup does he love",
    "when is the piano recital",
    "how does he feel about magpies",
    "what mornings do you enjoy",
    "does he play squash",            # foreign — its verdict is (empty, empty)
    "what is his shoe size",          # foreign
]
LATER = [
    "Knack's ladder hook is in the carport",
    "Knack's favourite mug is the cracked blue one",
    "Knack is a member of the astronomy club",
]

for f in FACTS:
    M.remember(f, source="user turn")
for f in SELF_FACTS:
    M.remember_about_self(f)

base = {q: verdict(q) for q in QUERIES}
nonempty = sum(1 for v in base.values() if v[0])
check("fixture sanity: matching queries admit, foreign do not",
      nonempty >= 4 and not base["does he play squash"][0],
      {q: len(v[0]) for q, v in base.items()})

# -- 1. TIME TRANSLATION --------------------------------------------------------------------
print("\n1. time translation (30 then 400 days: order types unchanged => verdicts unchanged)")
for days in (30, 400):
    shift_all(days)
    now = {q: verdict(q) for q in QUERIES}
    bad = [q for q in QUERIES if now[q] != base[q]]
    check("verdict sets survive a uniform -%d day shift" % days, not bad,
          [(q, sorted(base[q][0] ^ now[q][0])) for q in bad[:2]])
    base = now                      # verdicts compose across shifts

# -- 2. FUTURE EXTENSION --------------------------------------------------------------------
print("\n2. future extension (the world grows; the past does not flip)")


def run_extension_and_retirement(tag):
    global base
    pre = {q: verdict(q) for q in QUERIES}
    for f in LATER:
        M.remember(f, source="user turn")
    post = {q: verdict(q) for q in QUERIES}
    new_addrs = {SX.addr_of(f) for f in LATER}
    bad = [q for q in QUERIES if post[q] != pre[q]]
    check("%s: old verdicts unchanged by unrelated appends" % tag, not bad, bad[:3])
    leak = [q for q in QUERIES if new_addrs & post[q][0]]
    check("%s: new rows never surface for old queries" % tag, not leak, leak)
    # -- 3. UNRELATED RETIREMENT --
    M.forget("ladder hook")
    post2 = {q: verdict(q) for q in QUERIES}
    bad = [q for q in QUERIES if post2[q] != post[q]]
    check("%s: tombstoning an unrelated row moves no old verdict" % tag, not bad, bad[:3])


run_extension_and_retirement("SEM off")

print("\n3. the same laws with the semantic gate armed (hash-space)")
os.environ["SP_SEM_MINT"] = "1"
os.environ["SP_SEM_INDEX"] = IDX
os.environ["SP_SEM_RANK"] = "1"
os.environ["SP_SEM_TAU"] = "0.60"
with open(REG, encoding="utf-8") as f:
    SX.backfill([json.loads(x) for x in f if x.strip()])
LATER = ["Knack's spare bike tube is in the shed drawer",
         "Knack's favourite biscuit is the ginger nut",
         "Knack is a regular at the Tuesday quiz night"]
run_extension_and_retirement("SEM on")
M.forget("bike tube")               # leave no live clutter ambiguity; belt-and-braces

print("\nG-SEM-STABLE: %d pass, %d fail" % (PASS, FAIL))
rdir = os.path.join(ROOT, "var", "sem", "receipts")
os.makedirs(rdir, exist_ok=True)
with open(os.path.join(rdir, "g_sem_stable.json"), "w", encoding="utf-8") as f:
    json.dump({"name": "g_sem_stable", "pass": PASS, "fail": FAIL,
               "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, f, indent=2)
sys.exit(1 if FAIL else 0)
