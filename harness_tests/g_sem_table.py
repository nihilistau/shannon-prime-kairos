#!/usr/bin/env python
"""G-SEM-COMPLETE + G-SEM-CONSISTENT — the verdict table is total, single-valued, and
pinned (docs/INVARIANT-MEMORY.md Phase A). One enumeration, both claims.

COMPLETE — the game board is finite and every square has a ruling:
  - every recipe either produced a ruled cell or a RECORDED writer refusal (a refusal
    is a ruling of the admission layer, with its reason attached);
  - the ∀-theorems hold over the whole table — this is "provable because it is in the
    sets", executably: statements quantified over every cell, not spot-checks:
        ∀ cells with lifecycle=1:                  silent (no seam, no speech, no decline)
        ∀ cells with lifecycle=0 ∧ status=observed: seam-admitted
        ∀ cells with class=private-secret ∧ attr=−: never spoken (declined, or silent)
        ∀ cells with status=inferred ∧ competition=1 ∧ lifecycle=0: not spoken
        ∀ cells: spoken ⇒ seam-admitted (nothing reaches her mouth around the seam)
  - every class a consumer branches on is either producible or explicitly noted
    (counterfact is vocabulary-only by design and must stay flagged).

CONSISTENT — one ruling per cell, and the committed table is the law:
  - zero conflict cells (a conflict = the same signature ruled two ways across text
    variants = policy secretly reading prose — the src-branching bug class);
  - the regenerated table equals the committed fixtures/sem/verdict-table.json cell for
    cell, ruling for ruling. A diff is a POLICY CHANGE: re-freeze deliberately, in the
    same commit as the change that caused it, or this gate is the tripwire that says
    you changed her rules without saying so.

OFFLINE. No GPU, no daemon. Runtime ~2-4 min (it builds ~50 small worlds through the
real writer).
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import sem_enum                                            # noqa: E402

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok   %s" % name)
    else:
        FAIL += 1
        print("  FAIL %s   %s" % (name, str(detail)[:240]))


def coords(cell):
    return dict(p.split("=", 1) for p in cell.split("|"))


table, refusals, notes = sem_enum.enumerate_table()

# ── COMPLETE ────────────────────────────────────────────────────────────────────────────
print("\nG-SEM-COMPLETE")
check("enumeration produced a non-trivial board", len(table) >= 15, len(table))
check("every refusal carries the writer's stated reason",
      all(r.get("why") for r in refusals), refusals[:2])

bad = [c for c, v in table.items() if coords(c)["lifecycle"] == "1"
       and (v["ruling"]["seam"] or v["ruling"]["spoken"] or v["ruling"]["declined"])]
check("FORALL lifecycle=1: silent on every path", not bad, bad[:2])

bad = [c for c, v in table.items()
       if coords(c)["lifecycle"] == "0" and coords(c)["status"] == "observed"
       and not v["ruling"]["seam"]]
check("FORALL live observed: seam-admitted", not bad, bad[:2])

bad = [c for c, v in table.items()
       if coords(c)["class"] == "private-secret" and coords(c)["attr"] == "-"
       and v["ruling"]["spoken"]]
check("FORALL secret with attr absent: never spoken", not bad, bad[:2])

bad = [c for c, v in table.items()
       if coords(c)["status"] == "inferred" and coords(c)["competition"] == "1"
       and coords(c)["lifecycle"] == "0" and v["ruling"]["spoken"]]
check("FORALL covered inference: does not take the floor", not bad, bad[:2])

bad = [c for c, v in table.items() if v["ruling"]["spoken"] and not v["ruling"]["seam"]]
check("FORALL cells: spoken implies seam-admitted (no path around the seam)",
      not bad, bad[:2])

check("counterfact stays flagged as consumer-branched-without-producer",
      any("counterfact" in n for n in notes), notes)

# ── CONSISTENT ──────────────────────────────────────────────────────────────────────────
print("\nG-SEM-CONSISTENT")
conflicts = {c: v["conflict"] for c, v in table.items() if "conflict" in v}
check("zero conflict cells (no ruling depends on prose)", not conflicts,
      list(conflicts.items())[:1])

try:
    with open(sem_enum.TABLE_PATH, encoding="utf-8") as f:
        committed = json.load(f)["table"]
except Exception as e:
    committed = None
check("a committed table exists (sem_enum.py --freeze)", committed is not None)
if committed is not None:
    now = {c: v["ruling"] for c, v in table.items()}
    then = {c: v["ruling"] for c, v in committed.items()}
    gone = sorted(set(then) - set(now))
    new = sorted(set(now) - set(then))
    moved = sorted(c for c in set(now) & set(then) if now[c] != then[c])
    check("no cells vanished", not gone, gone[:3])
    check("no unreviewed new cells", not new, new[:3])
    check("no ruling moved", not moved,
          [(c, then[c], now[c]) for c in moved[:2]])

print("\nG-SEM-TABLE: %d pass, %d fail" % (PASS, FAIL))
rdir = os.path.join(ROOT, "var", "sem", "receipts")
os.makedirs(rdir, exist_ok=True)
with open(os.path.join(rdir, "g_sem_table.json"), "w", encoding="utf-8") as f:
    json.dump({"name": "g_sem_table", "pass": PASS, "fail": FAIL,
               "cells": len(table), "refusals": len(refusals), "notes": notes,
               "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, f, indent=2)
sys.exit(1 if FAIL else 0)
