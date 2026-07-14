#!/usr/bin/env python
"""G-SEM-VERDICT — the Phase B2 cutover: the table rules, silence-direction only, and
arming it changes NOTHING today (docs/INVARIANT-MEMORY.md Phase B2).

  1. THE RECEIPT THAT JUSTIFIES ARMING IT: with slots empty, all 160 frozen corpus
     queries return BYTE-IDENTICAL results (addrs AND scores) with SP_SEM_VERDICT on
     vs off. Cutover moves authority; it does not move behaviour — until a law-relevant
     fact (a slot link, a table change) gives it something to say.
  2. THE LAW CAN ONLY SILENCE (mechanism, labeled): a temp table ruling a live cell
     seam-inadmissible drops that row through the REAL seam; nothing else moves; a
     witness is written.
  3. UNMAPPED IS KEPT AND COUNTED (mechanism, labeled): a row in an unlegislated cell
     passes through and trips the counter — unlegislated is not forbidden, and her
     self-preference rows were one field-run away from proving why (they were unmapped
     for a day; enforcement must not have muted her lane for my enumeration gap).
  4. A MISSING TABLE DISABLES ENFORCEMENT (there is no law to apply), loudly nothing.

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
os.environ["SP_RECALL_REGISTRY"] = os.path.join(FIX, "registry_snapshot.jsonl")
for _k in [k for k in os.environ if k.startswith("SP_SEM_")]:
    del os.environ[_k]
_tmp = tempfile.mkdtemp(prefix="g_sem_verdict_")
os.environ["SP_SEM_LAW_LOG"] = os.path.join(_tmp, "witness.jsonl")

from harness.skills import memory as M                      # noqa: E402
from harness.skills import semindex as SX                   # noqa: E402
from harness.skills import verdict as V                     # noqa: E402

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok   %s" % name)
    else:
        FAIL += 1
        print("  FAIL %s   %s" % (name, str(detail)[:200]))


def results_scored(q):
    return [[SX.addr_of(e.get("text") or ""), round(float(s), 6)]
            for s, e in M.search_memories_ranked_rows(q, k=5)]


with open(os.path.join(FIX, "paraphrase.jsonl"), encoding="utf-8") as f:
    QUERIES = [json.loads(x)["q"] for x in f if x.strip()]
with open(os.path.join(FIX, "foreign.jsonl"), encoding="utf-8") as f:
    QUERIES += [json.loads(x)["q"] for x in f if x.strip()]

# -- 1. BYTE-IDENTICAL WITH THE FLAG ON (slots empty) ---------------------------------------
print("\n1. cutover armed == cutover off, byte-for-byte, all %d corpus queries" % len(QUERIES))
off = [results_scored(q) for q in QUERIES]
os.environ["SP_SEM_VERDICT"] = "1"
on = [results_scored(q) for q in QUERIES]
diff = [QUERIES[i] for i in range(len(QUERIES)) if off[i] != on[i]]
check("no query moved (addrs and scores)", not diff, diff[:3])
check("zero enforced drops on the corpus", V.stats().get("enforced_drops", 0) == 0,
      V.stats())

# -- 2. THE LAW CAN ONLY SILENCE (mechanism) -------------------------------------------------
print("\n2. an inadmissible ruling drops the row through the REAL seam (mechanism)")
PROBE_FACT = "Knack's cat is called Biscuit"          # a snapshot row, verbatim
probe_q = PROBE_FACT                                   # own-text query: always admitted
base = results_scored(probe_q)
check("probe admits the cat fact before the mechanism test",
      len(base) >= 1, base)
target_cell = None
rows = [json.loads(x) for x in open(os.environ["SP_RECALL_REGISTRY"], encoding="utf-8")
        if x.strip()]
for r in rows:
    if r.get("text") == PROBE_FACT:
        target_cell = V.cell(r, probe_q, rows)
with open(V.TABLE_PATH, encoding="utf-8") as f:
    real_table = json.load(f)
tampered = {"table": {c: ({"ruling": {"seam": False, "spoken": False, "declined": False}}
                          if c == target_cell else v)
                      for c, v in real_table["table"].items()}}
tmp_table = os.path.join(_tmp, "table.json")
with open(tmp_table, "w", encoding="utf-8") as f:
    json.dump(tampered, f)
_orig = V.TABLE_PATH
V.TABLE_PATH = tmp_table
V._TABLE.update(mtime=None, cells=None)
dropped = results_scored(probe_q)
gate_addr = SX.addr_of(PROBE_FACT)
check("the ruled-out row is gone", all(a != gate_addr for a, _ in dropped), dropped)
# The k-window REFILLS: dropping a top-5 row lets the next admissible row in at the
# tail. That is the seam working, not the law overreaching — assert the survivors kept
# their order and nothing else was touched.
survivors = [x for x in base if x[0] != gate_addr]
check("survivors unchanged, in order (tail refill permitted)",
      dropped[:len(survivors)] == survivors, (base, dropped))
check("an enforcement witness was written",
      any(json.loads(x)["kind"] == "enforced_drop"
          for x in open(os.environ["SP_SEM_LAW_LOG"], encoding="utf-8") if x.strip()))
V.TABLE_PATH = _orig
V._TABLE.update(mtime=None, cells=None)

# -- 3. UNMAPPED IS KEPT AND COUNTED (mechanism) ---------------------------------------------
print("\n3. unlegislated is not forbidden (mechanism)")
alien = {"text": "alien row", "speaker": "user", "status": "observed",
         "lifecycle": 0, "mem_class": "class-from-the-future", "name": "alien"}
before = V.stats().get("unmapped", 0)
kept = V.enforce("alien query", [(1.0, alien)], rows + [alien])
check("the unmapped row passes through", kept == [(1.0, alien)], kept)
check("and trips the counter", V.stats().get("unmapped", 0) == before + 1, V.stats())

# -- 4. NO TABLE, NO LAW ---------------------------------------------------------------------
print("\n4. a missing table disables enforcement")
V.TABLE_PATH = os.path.join(_tmp, "no_such_table.json")
V._TABLE.update(mtime=None, cells=None)
check("results equal the unenforced baseline", results_scored(probe_q) == base)
V.TABLE_PATH = _orig
V._TABLE.update(mtime=None, cells=None)

print("\nG-SEM-VERDICT: %d pass, %d fail" % (PASS, FAIL))
rdir = os.path.join(ROOT, "var", "sem", "receipts")
os.makedirs(rdir, exist_ok=True)
with open(os.path.join(rdir, "g_sem_verdict.json"), "w", encoding="utf-8") as f:
    json.dump({"name": "g_sem_verdict", "pass": PASS, "fail": FAIL,
               "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, f, indent=2)
sys.exit(1 if FAIL else 0)
