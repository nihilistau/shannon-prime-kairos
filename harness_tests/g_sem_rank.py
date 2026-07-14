#!/usr/bin/env python
"""G-SEM-RANK — the S1 dual admission gate is a MATCH gate, precision-first, and off-is-off
(docs/SEMANTICS.md S1).

Through the real seam (search_memories_ranked_rows) and the real per-turn path
(spine.recall_decider), never a hand-called scorer:

  1. OFF IS OFF. SP_SEM_RANK unset: all 160 frozen corpus queries reproduce
     golden-lexical.json byte-exactly. (G-SEM-CONSERVE holds this forever; asserted here
     too so THIS gate fails first when the seam change leaks.)
  2. SEMANTIC ADMISSION IS ADMISSION BY MATCH. A fact whose lexical overlap is diluted
     below min_overlap is admitted when its same-space cosine clears tau — through the
     seam, from an index row minted by the REAL writer.
  3. CROSS-SPACE COSINE IS NOISE, SO IT IS NEVER COMPUTED. An l5-space index row is
     ignored while the query embeds in hash-space: no admission, no score change.
  4. PRECISION FLOOR. With SEM on (hash-space), foreign-query false injection through
     recall_decider is no worse than the lexical baseline's. Semantics may only ever
     ADD matched facts; it may not add noise.
  5. A DEAD INDEX COSTS NOTHING. SP_SEM_INDEX pointing at nothing: results equal
     lexical, no exception reaches the caller.

The WIN condition (beat decider_hit_rate 0.06 on the corpus) is NOT asserted here — that
is the scoreboard's job (sem_rank_score.py) and a receipt, not a gate: a gate must stay
green on machines without the daemon, and the win needs the engine's l5 space.

OFFLINE. No GPU, no daemon (the /v1/embed probe fails fast to hash-space by design).
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
os.environ["SP_RECALL_REGISTRY"] = os.path.join(FIX, "registry_snapshot.jsonl")
for kv in [k for k in os.environ if k.startswith("SP_SEM_")]:
    del os.environ[kv]

from harness.skills import memory as M              # noqa: E402
from harness.skills import semindex as SX           # noqa: E402
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


def results(q):
    # addr order, not scores — scores carry the decaying salience recency term
    # (see g_sem_conserve.py's golden note).
    return [SX.addr_of(e.get("text") or "")
            for _, e in M.search_memories_ranked_rows(q, k=3)]


def injected(q):
    out = []
    for d in recall_decider(min_overlap=0.34)._fn(TurnView(phase="pre", user_text=q)):
        out += d.payload.get("facts", [])
    return out


with open(os.path.join(FIX, "golden-lexical.json"), encoding="utf-8") as f:
    GOLDEN = json.load(f)
FLAT = {**GOLDEN["paraphrase"], **GOLDEN["foreign"]}

# -- 1. OFF IS OFF ------------------------------------------------------------------------
print("\n1. off is off (SEM unset == golden, all 160)")
bad = [q for q, want in FLAT.items() if results(q) != want]
check("byte-identical to golden with SP_SEM_RANK unset", not bad, bad[:3])

# -- prepare a SEM-on world: temp registry + index, rows through the REAL writer ----------
_tmp = tempfile.mkdtemp(prefix="g_sem_rank_")
REG2 = os.path.join(_tmp, "reg.jsonl")
IDX2 = os.path.join(_tmp, "idx.jsonl")
open(REG2, "w").close()
os.environ["SP_RECALL_REGISTRY"] = REG2
os.environ["SP_SEM_MINT"] = "1"
os.environ["SP_SEM_INDEX"] = IDX2
# NOT a secret on purpose: the first draft of this gate used "Knack's spare key is under
# the blue pot" and the decider returned NOTHING — because lifecycle.classify() minted it
# private-secret and the zero-inference decline fired. On the semantic path. Unprompted.
# That is G-SEM-CLAIM §3's theorem observed in the wild, and this gate now asserts the
# class so a future classifier change cannot silently turn this test into that one.
FACT = "Knack's greenhouse thermometer is stuck at nine degrees"
M.remember(FACT, source="user turn")
M.remember("Knack's favourite dessert is sticky date pudding", source="user turn")
_row = next(r for r in (json.loads(x) for x in open(REG2, encoding="utf-8") if x.strip())
            if r.get("text") == FACT)

# a query engineered for the hash space: every raw token of FACT (twice — counts matter
# to the hashing cosine), diluted with 20 content words so lexical overlap
# (|content(q) ∩ content(t)| / |content(q)|) falls below the 0.25 gate while doc-side
# cosine stays high. This is the paraphrase geometry, made deterministic.
DILUTED = (FACT.lower() + " " + FACT.lower() + " garden weather sensor reading gauge "
           "number value display panel window plant water sunshine morning afternoon "
           "evening cloud rain wind frost")

os.environ["SP_SEM_RANK"] = "1"
os.environ["SP_SEM_TAU"] = "0.60"

# -- 2. ADMISSION BY MATCH ---------------------------------------------------------------
print("\n2. semantic admission through the seam (and the real decider)")
check("the test fact is NOT private-secret (see comment above)",
      _row.get("mem_class") != "private-secret", _row.get("mem_class"))
check("lexical overlap is below the 0.25 gate (so admission below is SEMANTIC)",
      M._overlap(DILUTED, FACT) < 0.25, M._overlap(DILUTED, FACT))
hits = M.search_memories_ranked_rows(DILUTED, k=3)
check("dual gate admits it semantically",
      any(e.get("text") == FACT for _, e in hits), [(s, e.get("text")) for s, e in hits])
check("the real decider (0.34) injects it too",
      any(FACT in f for f in injected(DILUTED)), injected(DILUTED))

# -- 3. CROSS-SPACE IS NEVER COMPARED ------------------------------------------------------
print("\n3. cross-space cosine is never computed")
with open(IDX2, encoding="utf-8") as f:
    lines = f.readlines()
# rewrite the FACT's index row as a fake l5-space row (unit vector, 512-dim)
out = []
for ln in lines:
    r = json.loads(ln)
    if r["addr"] == SX.addr_of(FACT):
        r = {**r, "model": SX.MODEL_L5, "vec": [1.0] + [0.0] * 511}
    out.append(json.dumps(r) + "\n")
with open(IDX2, "w", encoding="utf-8") as f:
    f.writelines(out)
hits = M.search_memories_ranked_rows(DILUTED, k=3)
check("l5-space row ignored while the query is hash-space",
      not any(e.get("text") == FACT for _, e in hits), [(s, e.get("text")) for s, e in hits])
with open(IDX2, "w", encoding="utf-8") as f:
    f.writelines(lines)                      # restore

# -- 4. PRECISION FLOOR --------------------------------------------------------------------
print("\n4. foreign queries: SEM adds matches, never noise")
os.environ["SP_RECALL_REGISTRY"] = os.path.join(FIX, "registry_snapshot.jsonl")
os.environ["SP_SEM_INDEX"] = os.path.join(_tmp, "idx_snap.jsonl")
with open(os.environ["SP_RECALL_REGISTRY"], encoding="utf-8") as f:
    SX.backfill([json.loads(x) for x in f if x.strip()])
with open(os.path.join(FIX, "foreign.jsonl"), encoding="utf-8") as f:
    foreign = [json.loads(x)["q"] for x in f if x.strip()]
base_fp = sum(1 for q in foreign if GOLDEN["foreign"][q])      # lexical seam false hits
sem_fp = sum(1 for q in foreign if results(q))
check("seam false hits with SEM on <= lexical baseline (%d)" % base_fp,
      sem_fp <= base_fp, sem_fp)
dec_fp = sum(1 for q in foreign if injected(q))
check("decider false injections with SEM on <= baseline 8", dec_fp <= 8, dec_fp)

# -- 5. A DEAD INDEX COSTS NOTHING --------------------------------------------------------
print("\n5. dead index degrades to lexical")
os.environ["SP_SEM_INDEX"] = os.path.join(_tmp, "does_not_exist.jsonl")
bad = [q for q, want in FLAT.items() if results(q) != want]
check("missing index == golden lexical, no exception", not bad, bad[:3])

print("\nG-SEM-RANK: %d pass, %d fail" % (PASS, FAIL))
rdir = os.path.join(ROOT, "var", "sem", "receipts")
os.makedirs(rdir, exist_ok=True)
with open(os.path.join(rdir, "g_sem_rank.json"), "w", encoding="utf-8") as f:
    json.dump({"name": "g_sem_rank", "pass": PASS, "fail": FAIL,
               "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, f, indent=2)
sys.exit(1 if FAIL else 0)
