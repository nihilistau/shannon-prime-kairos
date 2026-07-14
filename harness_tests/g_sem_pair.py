#!/usr/bin/env python
"""G-SEM-PAIR — Phase C2: the order-frame proposer, its honest scoreboard, and the
review pipeline that ships instead of the auto-link that didn't.

THE C2 STORY, in receipts: similarity failed twice as a link detector (cosine: no
discrimination; the greedy LLM judge: parseable at last and STILL all-NO, true pairs
included — measured out in every role, confirmer and veto). Its OPPOSITE is pair-level
STRUCTURE — Friedman's emulation: two rows link the way a known pair links iff the
pairs are order-equivalent. Measured on the committed corpus (pairs.jsonl, 20/20 with
deliberate shared-word-different-dimension traps): gap-zone recall 1.0, precision
0.625 — below the PRE-REGISTERED 0.80 auto-bar, so auto-linking stays off and the
receipt says so. What ships is the COMBINATION the operator named: machine recall +
human precision — frame proposals land PENDING (inert: the evaluator honors only
'same'), and the operator confirms or rejects with the 'operator' tag.

  1. FRAME PROPERTIES (pure, over the whole corpus): deterministic; symmetric; never
     links pairs with no shared subject-matter; different grammatical subjects
     rejected (the cross-lane pair); a restatement/containment is not competition;
     attribute pairs (shared possessive slot) link.
  2. THE RECEIPT IS PINNED: the offline columns regenerate exactly against
     fixtures/sem/pair-receipt.json — including ships:false. Quietly improving the
     proposer without re-freezing the receipt trips this gate.
  3. THE PIPELINE, END TO END, REAL PATHS: ladders world through the real writer →
     scan(frame-review) proposes PENDING → the link is INERT (the decider still
     speaks the inference) → operator confirms via the real resolve() → under the
     armed cutover the decider SILENCES it, his words standing. Structure proposed,
     the human ruled, the table enforced.
  4. THE REJECTED PATH: operator rejects → stays spoken, queue empties, and the pair
     is never re-proposed (idempotency through the seen-set).

OFFLINE. No GPU, no daemon.
"""
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FIX = os.path.join(HERE, "fixtures", "sem")
sys.path.insert(0, ROOT)
os.environ["SP_DAEMON_URL"] = "http://127.0.0.1:9"
os.environ["SP_CAPTURE_ASYNC"] = "0"
_tmp = tempfile.mkdtemp(prefix="g_sem_pair_")
REG = os.path.join(_tmp, "reg.jsonl")
SLOTS = os.path.join(_tmp, "slots.jsonl")
open(REG, "w").close()
os.environ["SP_RECALL_REGISTRY"] = REG
for _k in [k for k in os.environ if k.startswith("SP_SEM_")]:
    del os.environ[_k]

from harness.skills import memory as M                      # noqa: E402
from harness.skills import lifecycle as lc                  # noqa: E402
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


with open(os.path.join(FIX, "pairs.jsonl"), encoding="utf-8") as f:
    CORPUS = [json.loads(x) for x in f if x.strip()]

# -- 1. FRAME PROPERTIES ------------------------------------------------------------------
print("\n1. frame properties over the corpus")
check("deterministic", all(SL.frame_link(r["a"], r["b"]) == SL.frame_link(r["a"], r["b"])
                           for r in CORPUS))
check("symmetric", all(SL.frame_link(r["a"], r["b"])[0] == SL.frame_link(r["b"], r["a"])[0]
                       for r in CORPUS))
check("never links without shared subject-matter",
      all(not SL.frame_link(r["a"], r["b"])[0] for r in CORPUS if r["zone"] == "none"))
check("cross-lane grammatical subjects rejected",
      not SL.frame_link("I am calmed by thunderstorms",
                        "Knack is scared of thunderstorms")[0])
check("a restatement is not competition",
      not SL.frame_link("Knack is fond of the garden", "Knack is fond of the garden")[0])
check("attribute pairs link (shared possessive slot)",
      SL.frame_link("My mower fuel is E10", "My mower fuel is diesel")[0])

# -- 2. THE RECEIPT IS PINNED --------------------------------------------------------------
print("\n2. the scoreboard receipt is pinned (ships:false stays said)")
with open(os.path.join(FIX, "pair-receipt.json"), encoding="utf-8") as f:
    committed = json.load(f)


def prose(a, b):
    return len(lc.topic_of(lc.strip_prefix(a)) & lc.topic_of(lc.strip_prefix(b))) >= 2


frame_now = [SL.frame_link(r["a"], r["b"])[0] for r in CORPUS]
gap = [r for r in CORPUS if r["zone"] == "gap"]
frame_gap = [SL.frame_link(r["a"], r["b"])[0] for r in gap]
tp = sum(1 for p, r in zip(frame_gap, gap) if p and r["link"])
fp = sum(1 for p, r in zip(frame_gap, gap) if p and not r["link"])
fn = sum(1 for p, r in zip(frame_gap, gap) if not p and r["link"])
check("gap-zone stats regenerate exactly",
      {"tp": tp, "fp": fp, "fn": fn} == {k: committed["frame_gap_zone"][k]
                                         for k in ("tp", "fp", "fn")},
      (tp, fp, fn, committed["frame_gap_zone"]))
check("the committed receipt honestly says ships:false (the pre-registered bar held)",
      committed["ships"] is False and committed["bar"] == {"precision": 0.80,
                                                           "recall": 0.80})

# -- 3. THE PIPELINE, END TO END -----------------------------------------------------------
print("\n3. propose (pending) -> inert -> operator confirms -> the table silences")
os.environ["SP_SEM_SLOTS"] = SLOTS
TESTIMONY = "Knack is wary of ladders after a fall"
INFERENCE = "Knack is relaxed about ladders these days"
M.remember(TESTIMONY, source="user turn")
M.remember(INFERENCE, source="reflection pass")
rows = [json.loads(x) for x in open(REG, encoding="utf-8") if x.strip()]
r = SL.scan(rows, proposers=("frame-review",))
check("the frame proposes exactly the ladders pair, PENDING", r["frame"] == 1, r)
q = SL.pending()
check("it sits in the review queue", len(q) == 1
      and "ladders" in q[0].get("a_text", "") + q[0].get("b_text", ""), q)
check("a pending link is INERT to the evaluator",
      not SL.linked(q[0]["a"], q[0]["b"]))


def injected(x):
    out = []
    for d in recall_decider(min_overlap=0.34)._fn(TurnView(phase="pre", user_text=x)):
        out += d.payload.get("facts", [])
    return out


os.environ["SP_SEM_VERDICT"] = "1"
check("pending: the inference still speaks (no behaviour from a proposal)",
      any("relaxed" in x for x in injected(INFERENCE)), injected(INFERENCE))
SL.resolve(q[0]["a"], q[0]["b"], "same")            # the operator's ruling, real path
check("confirmed: the evaluator honors the operator link",
      SL.linked(q[0]["a"], q[0]["b"]))
check("confirmed: the table silences the inference through the REAL decider",
      not any("relaxed" in x for x in injected(INFERENCE)), injected(INFERENCE))
check("his testimony stands on its own subject",
      any("wary" in x for x in injected(TESTIMONY)))
check("the queue is empty (resolved)", SL.pending() == [])

# -- 4. THE REJECTED PATH ------------------------------------------------------------------
print("\n4. the rejected path")
M.remember("Knack is proud of his garden this spring", source="user turn")
M.remember("Knack is embarrassed by the garden lately", source="reflection pass")
rows = [json.loads(x) for x in open(REG, encoding="utf-8") if x.strip()]
r = SL.scan(rows, proposers=("frame-review",))
q = SL.pending()
check("a second proposal arrives pending", len(q) == 1, (r, q))
SL.resolve(q[0]["a"], q[0]["b"], "different")
check("rejected: still speaks",
      any("embarrassed" in x for x in injected("Knack is embarrassed by the garden lately")))
check("rejected: queue empty and never re-proposed",
      SL.pending() == [] and SL.scan(rows, proposers=("frame-review",))["frame"] == 0)

print("\nG-SEM-PAIR: %d pass, %d fail" % (PASS, FAIL))
rdir = os.path.join(ROOT, "var", "sem", "receipts")
os.makedirs(rdir, exist_ok=True)
with open(os.path.join(rdir, "g_sem_pair.json"), "w", encoding="utf-8") as f:
    json.dump({"name": "g_sem_pair", "pass": PASS, "fail": FAIL,
               "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, f, indent=2)
sys.exit(1 if FAIL else 0)
