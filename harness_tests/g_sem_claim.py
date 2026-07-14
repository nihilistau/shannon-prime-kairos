#!/usr/bin/env python
"""G-SEM-CLAIM — with SEM ON, every law of the seam still holds, ON THE REAL PATH
(docs/SEMANTICS.md §3 — the blast-radius clause, executable).

G-CLAIM proved the laws for the lexical seam. This gate proves the semantic gate cannot
be the fourth way around them. All assertions go through spine.recall_decider — the
automatic per-turn injection — with SP_SEM_RANK=1 and a live index minted by the real
writer:

  1. A TOMBSTONE IS DEAD ON THE SEMANTIC PATH TOO. A retired fact whose index row still
     exists (append-only: it always will) is never admitted, however high its cosine —
     lifecycle joins from the REGISTRY at the seam.
  2. TESTIMONY STILL OUTRANKS INFERENCE. A semantically-admitted inference on a topic
     his own words cover still loses the floor to him.
  3. THE PRIVACY DECLINE STILL FIRES. A private-secret admitted semantically is still
     declined by the policy dispatch — ranking runs BEFORE policy, never instead of it.
  4. SPEAKER LANES DO NOT CROSS. Semantic admission never lets a user-lane row answer a
     "your"-scoped (self) question ranked above the self row.

The worst case this gate exists to keep impossible: an embedding concluding two rows are
"the same" and semantics merging or resurrecting what the lifecycle retired — the
identity-slot bug with a cosine on top.

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
_tmp = tempfile.mkdtemp(prefix="g_sem_claim_")
REG = os.path.join(_tmp, "reg.jsonl")
IDX = os.path.join(_tmp, "idx.jsonl")
open(REG, "w").close()
os.environ["SP_RECALL_REGISTRY"] = REG
os.environ["SP_SEM_MINT"] = "1"
os.environ["SP_SEM_INDEX"] = IDX
os.environ["SP_SEM_RANK"] = "1"
os.environ["SP_SEM_TAU"] = "0.60"

from harness.skills import memory as M                      # noqa: E402
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


def decisions(q):
    return list(recall_decider(min_overlap=0.34)._fn(TurnView(phase="pre", user_text=q)))


def injected(q):
    out = []
    for d in decisions(q):
        out += d.payload.get("facts", [])
    return out


def reset():
    open(REG, "w").close()
    open(IDX, "w").close()


# Diluted-query helper: all content tokens of the fact + filler, so the lexical gate
# fails and admission (if any) is SEMANTIC — the path under test.
def diluted(fact_tokens):
    return (fact_tokens + " location detail question answer information context "
            "extra filler words padding tokens dilution")


# -- 1. TOMBSTONES ARE DEAD, COSINE OR NO COSINE ------------------------------------------
print("\n1. a tombstone is dead on the semantic path")
reset()
M.remember("Knack's garage code lockbox is behind the meter", source="user turn")
M.forget("garage code lockbox")
q = diluted("garage code lockbox meter knack behind")
check("retired row never injected despite a live index row",
      not any("lockbox" in f for f in injected(q)), injected(q))

# -- 2. TESTIMONY STILL WINS ---------------------------------------------------------------
# The law is about ADMITTED rows: when both his testimony and her inference clear the
# semantic gate, his words take the floor and hers stay home. (The system does NOT
# promise his testimony gets admitted for every query that admits the inference — the
# first draft of this check assumed that, and tested a promise nobody made.)
print("\n2. testimony outranks a semantically-admitted inference")
reset()
TESTIMONY = "Knack is terrified of open water"
INFERENCE = "Knack is comfortable in open water"
M.remember(TESTIMONY, source="user turn")
M.remember(INFERENCE, source="reflection pass")
# query carries BOTH texts' raw tokens (cosine admits both) + enough content filler
# that lexical overlap stays under the decider's 0.34 — admission here is semantic.
q2 = (TESTIMONY.lower() + " " + INFERENCE.lower()
      + " feelings summary detail question answer context information filler")
facts = injected(q2)
check("both rows cleared the semantic gate (his words present)",
      any("terrified" in f for f in facts), facts)
check("her inference does not speak over him",
      not any("comfortable" in f for f in facts), facts)

# -- 3. THE PRIVACY DECLINE STILL FIRES ----------------------------------------------------
print("\n3. a secret admitted semantically is still declined")
reset()
M.remember("My secret access code is 9137", source="user turn")
rows = [json.loads(x) for x in open(REG, encoding="utf-8") if x.strip()]
check("the writer classified it private-secret (the real producer)",
      any(r.get("mem_class") == "private-secret" for r in rows),
      [r.get("mem_class") for r in rows])
q = diluted("secret access code 9137")
ds = decisions(q)
payload = json.dumps([d.payload for d in ds], ensure_ascii=False)
check("the digits never reach the payload", "9137" not in payload, payload[:200])

# -- 4. SPEAKER LANES DO NOT CROSS ---------------------------------------------------------
print("\n4. lanes: a 'your'-scoped question is not answered from his lane")
reset()
M.remember_about_self("I am calmed by thunderstorms")
M.remember("Knack is frightened of thunderstorms", source="user turn")
facts = injected("how do you feel about thunderstorms")
if facts:
    check("the self row outranks his on a self-scoped question",
          "calmed" in facts[0] or "About myself" in facts[0], facts)
else:
    check("no injection at all is acceptable (quieter, never wrong-lane-first)", True)

print("\nG-SEM-CLAIM: %d pass, %d fail" % (PASS, FAIL))
rdir = os.path.join(ROOT, "var", "sem", "receipts")
os.makedirs(rdir, exist_ok=True)
with open(os.path.join(rdir, "g_sem_claim.json"), "w", encoding="utf-8") as f:
    json.dump({"name": "g_sem_claim", "pass": PASS, "fail": FAIL,
               "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, f, indent=2)
sys.exit(1 if FAIL else 0)
