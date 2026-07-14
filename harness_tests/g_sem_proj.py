#!/usr/bin/env python
"""G-SEM-PROJ — the σ-native verdicts are table projections, and there is ONE
normalization law (INVARIANT-ROADMAP.md Tier 1.3).

THE FINDING THIS CONVERSION MADE: the status-normalization law had DIVERGED. A legacy
row (status missing, src sniffing 'reflection') was HER CONCLUSION to render() and
_is_evidence() — both carried the migration shim — but HIS TESTIMONY to testimony_wins()
and sigma(), which used a plain observed-default. Same row: ground truth at the seam, a
conclusion at the mouth. lifecycle.status_of() is now the one law; this gate holds every
consumer to it.

  1. FRAMING — every cell of the (status × speaker × legacy-src) domain through the
     REAL render(): inferred reads as hers in any lane; confirmed reads as agreed;
     observed splits by speaker; the legacy reflection row reads as hers.
  2. SUPERSEDE — the permission matrix through the REAL writer (memory.remember), every
     (incoming × held) cell: an inference NEVER retires ground truth; everything else
     supersedes. Including the shim direction: a legacy src-reflection row does NOT get
     testimony's shield.
  3. ONE LAW AT THE SEAM — the divergence, closed and pinned: a legacy reflection row is
     a conclusion to the seam's testimony_wins too (it no longer suppresses her fresh
     inferences as if he had spoken).
  4. EVIDENCE — verdict.is_evidence over the full signature domain: live ∧ his-lane ∧
     ground truth, tombstones never news, legacy shim honored.

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
for _k in [k for k in os.environ if k.startswith("SP_SEM_")]:
    del os.environ[_k]
_tmp = tempfile.mkdtemp(prefix="g_sem_proj_")
REG = os.path.join(_tmp, "reg.jsonl")
open(REG, "w").close()
os.environ["SP_RECALL_REGISTRY"] = REG

from harness.skills import memory as M                      # noqa: E402
from harness.skills import lifecycle as lc                  # noqa: E402
from harness.skills import verdict as V                     # noqa: E402
from harness.kairos import scheduler as sched               # noqa: E402

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok   %s" % name)
    else:
        FAIL += 1
        print("  FAIL %s   %s" % (name, str(detail)[:200]))


def row(**kw):
    base = {"text": "Knack's shed key hangs by the door", "speaker": "user",
            "status": "observed", "lifecycle": 0, "mem_class": "fact", "name": "r"}
    base.update(kw)
    return base


# -- 1. FRAMING -------------------------------------------------------------------------------
print("\n1. framing: every cell through the REAL render()")
cases = [
    (row(status="observed", speaker="user"), "Knack told me:"),
    (row(status="observed", speaker="self"), "About myself:"),
    (row(status="inferred", speaker="user"), "I've come to think:"),
    (row(status="inferred", speaker="self"), "I've come to think:"),   # status outranks lane
    (row(status="confirmed", speaker="user"), "We settled that:"),
    (row(status="confirmed", speaker="self"), "We settled that:"),
    (row(status="disputed", speaker="user"), "Knack told me:"),        # vocab-only: falls through
    (row(status=None, speaker="user", src="user turn"), "Knack told me:"),
    (row(status=None, speaker="user", src="reflection | cleanup: x"), "I've come to think:"),
    (row(status=None, speaker="self", src="insight"), "I've come to think:"),
]
for r, want in cases:
    got = lc.render(r)
    check("(%s, %s, src=%r) -> %r" % (r.get("status"), r["speaker"],
                                      (r.get("src") or "")[:14], want),
          got.startswith(want), got)

# -- 2. SUPERSEDE MATRIX, THROUGH THE REAL WRITER ----------------------------------------------
print("\n2. supersede permission: every (incoming x held) cell through remember()")


def world(held_src, held_status, incoming_src):
    # ATTRIBUTE shape on purpose ("My X is Y" — the possessive is the tell): properties
    # accumulate and never supersede (G-CLAIM), so only a slotted fact exercises the
    # permission matrix. The first draft used "Knack's mower fuel..." and proved it —
    # nothing retired anywhere, because that shape has no slot.
    open(REG, "w").close()
    M.remember("My mower fuel is E10", source=held_src)
    if held_status is None:               # legacy: strip the field (history is the producer)
        rows = [json.loads(x) for x in open(REG, encoding="utf-8") if x.strip()]
        for r in rows:
            r.pop("status", None)
        with open(REG, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    M.remember("My mower fuel is diesel", source=incoming_src)
    rows = [json.loads(x) for x in open(REG, encoding="utf-8") if x.strip()]
    old = next(r for r in rows if "E10" in (r.get("text") or ""))
    return bool(old.get("lifecycle"))


check("observation retires observation (he changed his mind)",
      world("user turn", "observed", "user turn") is True)
check("observation retires inference (he corrects her)",
      world("reflection pass", "inferred", "user turn") is True)
check("inference retires inference (she revised her view)",
      world("reflection pass", "inferred", "reflection pass") is True)
check("inference NEVER retires observation (the one rule)",
      world("user turn", "observed", "reflection pass") is False)
check("legacy no-status row is protected as testimony (default protects him)",
      world("user turn", None, "reflection pass") is False)
check("legacy src-reflection row does NOT get testimony's shield (the shim direction)",
      world("reflection pass", None, "reflection pass") is True)

# -- 3. ONE LAW AT THE SEAM --------------------------------------------------------------------
print("\n3. the divergence, closed: legacy reflection is a conclusion to the seam too")
open(REG, "w").close()
M.remember("Knack is guarded around strangers at parties", source="reflection pass")
rows = [json.loads(x) for x in open(REG, encoding="utf-8") if x.strip()]
for r in rows:
    r.pop("status", None)                  # the legacy shape: pre-status reflection row
with open(REG, "w", encoding="utf-8") as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
M.remember("Knack is relaxed around strangers at parties", source="reflection pass")
hits = M.search_memories_ranked_rows("how is Knack around strangers at parties", k=5)
texts = [e.get("text") for _, e in hits]
check("her fresh inference is NOT suppressed by her own legacy conclusion "
      "(pre-fix, the legacy row wore testimony's shield at the seam)",
      any("relaxed" in (t or "") for t in texts), texts)

# -- 4. EVIDENCE, OVER THE DOMAIN --------------------------------------------------------------
print("\n4. is_evidence: the sigma projection, all cells")
ev = [
    (row(), True),
    (row(lifecycle=1), False),                                  # a tombstone is not news
    (row(speaker="self"), False),                               # her voice is not the world
    (row(status="inferred"), False),                            # a conclusion is not news
    (row(status="confirmed"), True),                            # agreed = ground truth
    (row(status=None, src="user turn"), True),                  # legacy default: observed
    (row(status=None, src="reflection | cleanup"), False),      # legacy shim: conclusion
]
for r, want in ev:
    check("evidence(%s/%s/lc=%d/src=%r) == %s" % (
        r.get("status"), r["speaker"], r["lifecycle"], (r.get("src") or "")[:10], want),
        sched._is_evidence(r) is want)
check("scheduler delegates to the ONE implementation",
      all(sched._is_evidence(r) == V.is_evidence(r) for r, _ in ev))

print("\nG-SEM-PROJ: %d pass, %d fail" % (PASS, FAIL))
rdir = os.path.join(ROOT, "var", "sem", "receipts")
os.makedirs(rdir, exist_ok=True)
with open(os.path.join(rdir, "g_sem_proj.json"), "w", encoding="utf-8") as f:
    json.dump({"name": "g_sem_proj", "pass": PASS, "fail": FAIL,
               "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, f, indent=2)
sys.exit(1 if FAIL else 0)
