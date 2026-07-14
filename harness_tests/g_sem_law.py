#!/usr/bin/env python
"""G-SEM-LAW — the evaluator agrees with the seam, in the field, on the real path
(docs/INVARIANT-MEMORY.md Phase B).

G-SEM-TABLE proves the table matches the enumerated worlds. THIS gate proves the
EVALUATOR (harness/skills/verdict.py) matches the RUNNING SEAM on worlds shaped like
her actual registry — including the shape the enumerator cannot produce through the
writer: the 77 live rows that PREDATE the status field. The normalization law
(missing status -> observed, missing speaker -> user) is read off lifecycle's own
defaults; this gate is what catches it drifting.

  1. OFF IS OFF. SP_SEM_LAW absent: shadow never runs (counters stay zero).
  2. ZERO DIVERGENCE, MODERN WORLD. A mixed world through the real writer (facts,
     secret, covered + uncovered inference, tombstones), diverse queries through the
     REAL seam and decider with shadow armed: everything admitted is table-admissible,
     nothing unmapped.
  3. ZERO DIVERGENCE, LEGACY WORLD. Same world with status fields STRIPPED (the one
     sanctioned hand-edit: the producer of that shape is history itself). Same law.
  4. THE ALARM ACTUALLY FIRES (mechanism test, labeled as such): shadow() handed an
     admitted tombstone increments the divergence counter and writes a witness;
     an alien-class row increments unmapped. A tripwire you have never seen trip is
     a wire on the floor.
  5. THE EVALUATOR NEVER GUESSES: ruling() for an unmapped cell is None, not a verdict.

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
_tmp = tempfile.mkdtemp(prefix="g_sem_law_")
REG = os.path.join(_tmp, "reg.jsonl")
open(REG, "w").close()
os.environ["SP_RECALL_REGISTRY"] = REG
for _k in [k for k in os.environ if k.startswith("SP_SEM_")]:
    del os.environ[_k]
os.environ["SP_SEM_LAW_LOG"] = os.path.join(_tmp, "witness.jsonl")

from harness.skills import memory as M                      # noqa: E402
from harness.skills import verdict as V                     # noqa: E402
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


def drive(queries):
    """Exercise the REAL paths: the seam directly and the per-turn decider."""
    for q in queries:
        M.search_memories_ranked_rows(q, k=5)
        list(recall_decider(min_overlap=0.34)._fn(TurnView(phase="pre", user_text=q)))


WORLD = [
    ("Knack's front gate is painted teal", "user turn"),
    ("Knack's favourite soup is spicy laksa", "user turn"),
    ("My secret access code is 9137", "user turn"),
    ("Knack is terrified of open water", "user turn"),
    ("Knack is comfortable in open water", "reflection pass"),      # covered inference
    ("Knack is relaxed about ladders these days", "reflection pass"),  # uncovered
]
QUERIES = [
    "what colour is his front gate", "which soup does he love",
    "what is my secret access code", "when did my secret access code last change",
    "how does he feel about open water", "is he relaxed about ladders",
    "does he play squash", "Knack's front gate is painted teal",
]

for text, src in WORLD:
    M.remember(text, source=src)
M.remember("Knack's old kettle is in the shed", source="user turn")
M.forget("old kettle")                                       # a real tombstone in the world

# -- 1. OFF IS OFF --------------------------------------------------------------------------
print("\n1. off is off")
drive(QUERIES)
check("shadow never ran with SP_SEM_LAW absent", V.stats()["checked"] == 0, V.stats())

# -- 2. ZERO DIVERGENCE, MODERN WORLD -------------------------------------------------------
print("\n2. modern world: everything admitted is table-admissible")
os.environ["SP_SEM_LAW"] = "1"
drive(QUERIES)
s = V.stats()
check("shadow ran (checked > 0)", s["checked"] > 0, s)
check("zero divergence", s["divergent"] == 0, s)
check("zero unmapped cells", s["unmapped"] == 0, s)

# -- 3. ZERO DIVERGENCE, LEGACY WORLD (pre-status rows) --------------------------------------
print("\n3. legacy world: rows that predate the status field")
rows = [json.loads(x) for x in open(REG, encoding="utf-8") if x.strip()]
for r in rows:
    r.pop("status", None)         # the sanctioned hand-edit: history is the producer
with open(REG, "w", encoding="utf-8") as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
before = V.stats()
drive(QUERIES)
s = V.stats()
check("shadow kept running", s["checked"] > before["checked"], (before, s))
check("zero divergence on legacy shapes (normalization law holds)",
      s["divergent"] == 0, s)
check("zero unmapped on legacy shapes", s["unmapped"] == 0, s)

# -- 4. THE ALARM FIRES (mechanism test) -----------------------------------------------------
print("\n4. the alarm fires (mechanism test — the real-path halves are sections 2-3)")
dead = {"text": "Knack's ghost fact", "speaker": "user", "status": "observed",
        "lifecycle": 1, "mem_class": "fact", "name": "ghost"}
V.shadow("ghost fact query", [dead], rows + [dead])
s = V.stats()
check("an admitted tombstone trips the divergence counter", s["divergent"] == 1, s)
alien = {"text": "alien", "speaker": "user", "status": "observed",
         "lifecycle": 0, "mem_class": "class-from-the-future", "name": "alien"}
V.shadow("alien query", [alien], rows + [alien])
check("an alien class trips the unmapped counter", V.stats()["unmapped"] == 1, V.stats())
with open(os.environ["SP_SEM_LAW_LOG"], encoding="utf-8") as f:
    wit = [json.loads(x) for x in f if x.strip()]
check("witnesses were written (finite objects, one per trip)",
      len(wit) == 2 and {w["kind"] for w in wit} == {"divergent", "unmapped"}, wit)

# -- 5. THE EVALUATOR NEVER GUESSES ----------------------------------------------------------
print("\n5. ruling() never guesses")
check("unmapped cell returns None, not a verdict",
      V.ruling(alien, "alien query", rows) is None)

print("\nG-SEM-LAW: %d pass, %d fail" % (PASS, FAIL))
rdir = os.path.join(ROOT, "var", "sem", "receipts")
os.makedirs(rdir, exist_ok=True)
with open(os.path.join(rdir, "g_sem_law.json"), "w", encoding="utf-8") as f:
    json.dump({"name": "g_sem_law", "pass": PASS, "fail": FAIL,
               "shadow_stats": V.stats(),
               "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, f, indent=2)
sys.exit(1 if FAIL else 0)
