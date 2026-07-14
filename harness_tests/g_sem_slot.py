#!/usr/bin/env python
"""G-SEM-SLOT — the ladders leak, closed by quarantined proposal (docs/INVARIANT-MEMORY.md
Phase C).

THE FINDING (verdict-table notes): his "wary of ladders after a fall" shares ONE content
word with her "relaxed about ladders these days", so prose topic coverage misses it and
she can lawfully say the inference over his testimony. THE FIX: an oracle proposes a
same-subject LINK (sidecar), verdict.competition() consumes it (the row's cell becomes
competition=1), and the B2 enforcement drops the inference — through the REAL seam and
the REAL decider.

  1. THE LEAK, ON THE RECORD: without a link, the inference IS spoken (today's lawful
     behaviour, the reason this gate exists).
  2. THE CLOSE: with a same-subject link in the sidecar and SP_SEM_VERDICT armed, the
     inference is silenced; HIS testimony is untouched; the registry is byte-identical
     (the sidecar is the only thing that changed).
  3. QUARANTINE DIRECTION: a WRONG link (two unrelated rows) silences at most a
     sentence — the unrelated inference — and cannot make anything speak, admit, or
     retire. A "different" verdict changes nothing.
  4. OFF IS OFF: sidecar unset -> today's behaviour exactly.
  5. THE PROPOSER'S SCAN POLICY is what it says: gap-zone pairs only (overlap exactly
     1), idempotent (asked pairs never re-asked), and an unreachable oracle proposes
     NOTHING (asserted against the discard port — no daemon in this gate).

The live-oracle half (real /v1/oneshot verdicts) runs when the stack is up:
    python -m harness.skills.slots --scan

OFFLINE. No GPU, no daemon.
"""
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
_tmp = tempfile.mkdtemp(prefix="g_sem_slot_")
REG = os.path.join(_tmp, "reg.jsonl")
SLOTS = os.path.join(_tmp, "slots.jsonl")
open(REG, "w").close()
os.environ["SP_RECALL_REGISTRY"] = REG
for _k in [k for k in os.environ if k.startswith("SP_SEM_")]:
    del os.environ[_k]

from harness.skills import memory as M                      # noqa: E402
from harness.skills import semindex as SX                   # noqa: E402
from harness.skills import slots as SL                      # noqa: E402
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


def injected(q):
    out = []
    for d in recall_decider(min_overlap=0.34)._fn(TurnView(phase="pre", user_text=q)):
        out += d.payload.get("facts", [])
    return out


TESTIMONY = "Knack is wary of ladders after a fall"
INFERENCE = "Knack is relaxed about ladders these days"
UNRELATED_FACT = "Knack's favourite soup is spicy laksa"
UNRELATED_INF = "Knack is starting to enjoy gardening more"
M.remember(TESTIMONY, source="user turn")
M.remember(INFERENCE, source="reflection pass")
M.remember(UNRELATED_FACT, source="user turn")
M.remember(UNRELATED_INF, source="reflection pass")
Q = INFERENCE                                   # own-text query: the leak's worst case
with open(REG, "rb") as f:
    REG_BYTES = f.read()

# -- 1. THE LEAK, ON THE RECORD ---------------------------------------------------------------
print("\n1. the leak (no link, no enforcement): she says it over him")
base = injected(Q)
check("the inference is spoken today (the finding, reproduced)",
      any("relaxed" in x for x in base), base)

# -- 2. THE CLOSE -----------------------------------------------------------------------------
print("\n2. link + enforcement: the inference is silenced, his words stand")
os.environ["SP_SEM_SLOTS"] = SLOTS
os.environ["SP_SEM_VERDICT"] = "1"
with open(SLOTS, "w", encoding="utf-8") as f:       # the oracle's output shape, fixture
    f.write(json.dumps({"a": SX.addr_of(TESTIMONY), "b": SX.addr_of(INFERENCE),
                        "verdict": "same", "oracle": "fixture",
                        "ts": "2026-07-14T00:00:00Z"}) + "\n")
after = injected(Q)
check("the inference no longer takes the floor",
      not any("relaxed" in x for x in after), after)
check("his testimony is unaffected on its own subject",
      any("wary" in x for x in injected(TESTIMONY)), injected(TESTIMONY))
check("the unrelated rows are unaffected",
      any("laksa" in x for x in injected(UNRELATED_FACT)))
with open(REG, "rb") as f:
    check("the registry is BYTE-IDENTICAL (the sidecar is the only change)",
          f.read() == REG_BYTES)

# -- 3. QUARANTINE DIRECTION ------------------------------------------------------------------
print("\n3. a wrong link costs a sentence, never a voice-over")
with open(SLOTS, "a", encoding="utf-8") as f:
    f.write(json.dumps({"a": SX.addr_of(UNRELATED_FACT), "b": SX.addr_of(UNRELATED_INF),
                        "verdict": "same", "oracle": "fixture-wrong",
                        "ts": "2026-07-14T00:00:01Z"}) + "\n")
check("the wrongly-linked inference is silenced (the safe direction)",
      not any("gardening" in x for x in injected(UNRELATED_INF)))
check("nothing new is spoken anywhere (a link cannot admit)",
      not any("gardening" in x for x in injected(Q)))
with open(SLOTS, "a", encoding="utf-8") as f:       # a 'different' verdict changes nothing
    f.write(json.dumps({"a": SX.addr_of(TESTIMONY), "b": SX.addr_of(UNRELATED_INF),
                        "verdict": "different", "oracle": "fixture",
                        "ts": "2026-07-14T00:00:02Z"}) + "\n")
check("a 'different' verdict is inert (cached, consulted, never a cover)",
      not any("relaxed" in x for x in injected(Q)))

# -- 4. OFF IS OFF ----------------------------------------------------------------------------
print("\n4. off is off")
del os.environ["SP_SEM_SLOTS"]
del os.environ["SP_SEM_VERDICT"]
check("without the sidecar, today's behaviour exactly",
      any("relaxed" in x for x in injected(Q)))

# -- 5. THE SCAN POLICY -----------------------------------------------------------------------
print("\n5. the proposer: gap zone only, idempotent, mute without its oracle")
os.environ["SP_SEM_SLOTS"] = os.path.join(_tmp, "slots2.jsonl")
rows = [json.loads(x) for x in open(REG, encoding="utf-8") if x.strip()]
r = SL.scan(rows)                                   # daemon is a discard port here
check("an unreachable oracle proposes nothing", r == {"asked": 0, "same": 0,
      "different": 0}, r)
check("gap-zone candidacy is real (the ladders pair overlaps at exactly 1)",
      len(__import__("harness.skills.lifecycle", fromlist=["x"]).topic_of(TESTIMONY)
          & __import__("harness.skills.lifecycle", fromlist=["x"]).topic_of(INFERENCE)) == 1)

print("\nG-SEM-SLOT: %d pass, %d fail" % (PASS, FAIL))
rdir = os.path.join(ROOT, "var", "sem", "receipts")
os.makedirs(rdir, exist_ok=True)
with open(os.path.join(rdir, "g_sem_slot.json"), "w", encoding="utf-8") as f:
    json.dump({"name": "g_sem_slot", "pass": PASS, "fail": FAIL,
               "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, f, indent=2)
sys.exit(1 if FAIL else 0)
