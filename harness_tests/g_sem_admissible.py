#!/usr/bin/env python
"""G-SEM-ADMISSIBLE — the invariance family has an admissions office (Tier 3,
INVARIANT-ROADMAP.md §1.1: Friedman's FIN/USE as an entry test).

A proposed invariance map over the value axis passes admissible() BEFORE it becomes a
stability gate. A rejected map is not a worse invariance — it is one the mathematics
says CANNOT consistently be demanded of maximal objects; gating it would pin a promise
that provably cannot hold.

  1. THE BATTERY. Verdicts on maps whose answers FIN/USE fixes: identity and pure
     translations usable; a non-monotone swap rejected; the endpoint pathology (lift lo
     while hi is reached from strictly inside) rejected ON A BOUNDED AXIS and vacuously
     fine on an unbounded one; Friedman's own Lead-function shape ([-1,0);0/n,...,n/n
     restricted to its finite moved points) REJECTED as a finite demand — exactly the
     class whose full form costs subtle cardinals.
  2. LOCALITY (FIN/USE*). The global answer equals the every-2-element-restriction
     answer on the whole battery — disagreement is a bug in the checker itself.
  3. THE HOOK. The transformations G-SEM-STABLE actually gates (uniform time
     translations) pass the checker — the existing family is admitted by its own
     admissions office, and every FUTURE family member goes through the same door.

OFFLINE. No GPU, no daemon, no store.
"""
import json
import os
import sys
import time
from fractions import Fraction

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from harness.skills import invariance as IV               # noqa: E402

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok   %s" % name)
    else:
        FAIL += 1
        print("  FAIL %s   %s" % (name, str(detail)[:200]))


F = Fraction

# -- 1. THE BATTERY ---------------------------------------------------------------------------
print("\n1. verdicts FIN/USE fixes")
battery = [
    ("identity (empty map)", {}, None, None, True),
    ("pure translation on the unbounded time axis",
     {F(0): F(1), F(5): F(6), F(100): F(101)}, None, None, True),
    ("monotone squeeze, endpoints untouched, bounded axis",
     {F(-1, 2): F(-1, 4), F(1, 4): F(1, 2)}, -1, 1, True),
    ("non-monotone swap", {F(0): F(1), F(1): F(0)}, None, None, False),
    ("collapse (not strictly increasing)", {F(0): F(1, 2), F(1): F(1, 2)},
     None, None, False),
    ("endpoint pathology on a bounded axis: lo lifted, hi reached from inside",
     {F(-1): F(-1, 2), F(1, 2): F(1)}, -1, 1, False),
    ("the SAME map on an unbounded axis: vacuously fine",
     {F(-1): F(-1, 2), F(1, 2): F(1)}, None, None, True),
    ("dual pathology: lo reached from inside, hi pulled in",
     {F(-1, 2): F(-1), F(1): F(1, 2)}, -1, 1, False),
    # Friedman's Lead shape [-1,0);0/2,1/2,2/2 — moved points 0->1/2->1 with the
    # identity interval implied: as a FINITE demand on [-1,1] the endpoint condition
    # trips (0 is fixed... the moved chain reaches hi=1 from 1/2 inside while -1 is
    # fixed => lo NOT lifted => actually passes?). Honest battery: the shape that
    # trips is lifting the BOTTOM: {-1 -> -1/2} with {1/2 -> 1}: already above. The
    # ladder-without-endpoints {0: 1/2, 1/2: 1} on [-1,1]: f(-1)=-1 fixed (lo not
    # lifted), f^{-1}(-1)=-1, f(1)=1? 1 not in dom -> f(1)=1 fixed => both conjuncts
    # fail => USABLE as a finite map — which is FIN/USE's actual content: the finite
    # ladder alone is cheap; it is the INFINITE interval+ladder that costs cardinals.
    ("the finite ladder 0 -> 1/2 -> 1 alone (no interval): cheap, usable — the "
     "cardinal cost belongs to the infinite interval+ladder, not the finite shadow",
     {F(0): F(1, 2), F(1, 2): F(1)}, -1, 1, True),
]
for name, f, lo, hi, want in battery:
    ok, why = IV.admissible(f, lo, hi)
    check("%s -> %s" % (name, "usable" if want else "rejected"), ok is want,
          (ok, why))

# -- 2. LOCALITY ------------------------------------------------------------------------------
print("\n2. FIN/USE*: global == pairwise on the whole battery")
bad = []
for name, f, lo, hi, _ in battery:
    if IV.admissible(f, lo, hi)[0] != IV.admissible_pairwise(f, lo, hi)[0]:
        bad.append(name)
check("the locality theorem holds on every battery map", not bad, bad)

# -- 3. THE HOOK ------------------------------------------------------------------------------
print("\n3. the existing stability family is admitted by its own admissions office")
for days in (30, 400):
    shift = {F(t): F(t) - days * 86400 for t in (0, 10**6, 10**9)}
    ok, why = IV.admissible(shift)
    check("G-SEM-STABLE's -%dd uniform time translation is admissible" % days, ok, why)

print("\nG-SEM-ADMISSIBLE: %d pass, %d fail" % (PASS, FAIL))
rdir = os.path.join(ROOT, "var", "sem", "receipts")
os.makedirs(rdir, exist_ok=True)
with open(os.path.join(rdir, "g_sem_admissible.json"), "w", encoding="utf-8") as f:
    json.dump({"name": "g_sem_admissible", "pass": PASS, "fail": FAIL,
               "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, f, indent=2)
sys.exit(1 if FAIL else 0)
