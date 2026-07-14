#!/usr/bin/env python
"""G-SEM-INDEX — the S0 sidecar semantic index is DERIVED, HONEST, and HARMLESS
(docs/SEMANTICS.md S0, §3).

What it must prove, all through the REAL writer (memory.remember), never a hand-built row:

  1. OFF BY ABSENCE. With SP_SEM_MINT unset, remember() creates no index and no file.
     The flag is the contract; a knob that half-exists is the two-paths bug.
  2. MINT THROUGH THE WRITER. With the flag on, remember() produces an index row whose
     (addr, ts) joins the registry row it indexes — addr identical to MEM-OKF addr_of.
  3. TOMBSTONE-BLIND. forget() retires the registry row; the index row is untouched
     (append-only, nothing deleted) and coverage counts only LIVE rows — lifecycle is
     read from the registry at the join, never copied into the index.
  4. VERIFY IS A RECOMPUTATION. Tamper one vector on disk; verify() returns a finite
     witness (addr, ts, why). Untampered, verify is empty.
  5. MODEL TAG CHECKED AT READ. A row with an alien model tag is skipped by load(),
     kept on disk — dead rows are ignored, never compared, never destroyed.
  6. FAILURE NEVER BLOCKS SPEECH. With the index path pointing somewhere unwritable,
     remember() still stores the fact and returns normally; the drop is a counter.
  7. BACKFILL IS IDEMPOTENT AND COMPLETE. Against the frozen fixture snapshot:
     coverage 1.0 after one pass, zero new rows on the second pass, verify green,
     and the registry file is BYTE-IDENTICAL before and after (S0 cannot write it).

OFFLINE. No GPU, no daemon.
"""
import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FIX = os.path.join(HERE, "fixtures", "sem")
sys.path.insert(0, ROOT)
os.environ["SP_DAEMON_URL"] = "http://127.0.0.1:9"
_tmp = tempfile.mkdtemp(prefix="g_sem_index_")
REG = os.path.join(_tmp, "registry.jsonl")
IDX = os.path.join(_tmp, "semindex.jsonl")
open(REG, "w").close()
os.environ["SP_RECALL_REGISTRY"] = REG
os.environ["SP_CAPTURE_ASYNC"] = "0"            # determinism, per the serve.py doctrine
os.environ.pop("SP_SEM_MINT", None)
os.environ.pop("SP_SEM_INDEX", None)

from harness.skills import memory as M          # noqa: E402
from harness.skills import semindex as SX       # noqa: E402

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok   %s" % name)
    else:
        FAIL += 1
        print("  FAIL %s   %s" % (name, str(detail)[:200]))


def reg_rows():
    with open(REG, encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]


# -- 1. OFF BY ABSENCE ------------------------------------------------------------------
print("\n1. off by absence")
M.remember("Knack's spare key is under the blue pot", source="user turn")
check("flag off: no index file appears", not os.path.exists(IDX))

# -- 2. MINT THROUGH THE WRITER ---------------------------------------------------------
print("\n2. mint through the real writer")
os.environ["SP_SEM_MINT"] = "1"
os.environ["SP_SEM_INDEX"] = IDX
M.remember("Knack's greenhouse thermometer is stuck at nine degrees", source="user turn")
idx = SX.load()
row = next((r for r in reg_rows()
            if r.get("text", "").startswith("Knack's greenhouse")), None)
check("index row exists after remember()", len(idx) == 1, idx)
check("registry row found", row is not None)
if row is not None and idx:
    (a, ts), irow = next(iter(idx.items()))
    check("(addr, ts) joins the registry row",
          a == SX.addr_of(row["text"]) and ts == row.get("ts"), (a, ts, row.get("ts")))
    check("hash-space vector recomputes", irow["vec"] == SX.hash_embed(row["text"]))
    # MEM-OKF address identity: one address vocabulary across stores
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import okf_mem                               # noqa: E402
    check("addr identical to tools/okf_mem.addr_of",
          SX.addr_of(row["text"]) == okf_mem.addr_of(row["text"]))

# -- 3. TOMBSTONE-BLIND -----------------------------------------------------------------
print("\n3. tombstone-blind (lifecycle lives in the registry)")
M.forget("greenhouse thermometer")
retired = [r for r in reg_rows() if r.get("lifecycle")]
check("registry row tombstoned (never deleted)", len(retired) == 1, reg_rows())
check("index row untouched by the tombstone", len(SX.load()) == 1)
cov = SX.coverage(reg_rows())
check("coverage counts only LIVE rows", cov["live"] == 1 and cov["indexed"] == 0, cov)

# -- 4. VERIFY IS A RECOMPUTATION -------------------------------------------------------
print("\n4. verify catches tamper")
M.remember("Knack's ladder is aluminium and older than the house", source="user turn")
check("verify green untampered", SX.verify(reg_rows()) == [], SX.verify(reg_rows()))
with open(IDX, encoding="utf-8") as f:
    lines = f.readlines()
tam = json.loads(lines[-1])
tam["vec"][0] = 0.999999
lines[-1] = json.dumps(tam) + "\n"
with open(IDX, "w", encoding="utf-8") as f:
    f.writelines(lines)
bad = SX.verify(reg_rows())
check("tampered vector yields a finite witness", len(bad) == 1 and bad[0][0] == tam["addr"], bad)
lines[-1] = json.dumps({**tam, "vec": SX.hash_embed(
    next(r["text"] for r in reg_rows() if r.get("text", "").startswith("Knack's ladder")))}) + "\n"
with open(IDX, "w", encoding="utf-8") as f:
    f.writelines(lines)
check("restored: verify green again", SX.verify(reg_rows()) == [])

# -- 5. MODEL TAG CHECKED AT READ -------------------------------------------------------
print("\n5. alien model rows are skipped, kept, never compared")
with open(IDX, "a", encoding="utf-8") as f:
    f.write(json.dumps({"addr": "deadbeefdeadbeef", "ts": "2020-01-01T00:00:00Z",
                        "model": "someother-model-v9", "vec": [1.0]}) + "\n")
check("load() skips the alien row", ("deadbeefdeadbeef", "2020-01-01T00:00:00Z") not in SX.load())
with open(IDX, encoding="utf-8") as f:
    check("the alien row is still on disk (nothing deleted)",
          any("someother-model-v9" in ln for ln in f))

# -- 6. FAILURE NEVER BLOCKS SPEECH -----------------------------------------------------
print("\n6. a broken index never reaches her mouth")
os.environ["SP_SEM_INDEX"] = os.path.join(_tmp, "no_such_dir_\0bad", "x.jsonl") \
    if os.name != "nt" else "Z:\\no\\such\\dir\\ever\\x.jsonl"
before = SX.dropped()
out = M.remember("Knack's porch light is on a dusk timer", source="user turn")
check("remember() still stores and returns normally", out.startswith("stored:"), out)
check("the failure is a telemetry counter", SX.dropped() == before + 1,
      (before, SX.dropped()))
check("the fact row was written regardless",
      any(r.get("text", "").startswith("Knack's porch light") for r in reg_rows()))
os.environ["SP_SEM_INDEX"] = IDX

# -- 7. BACKFILL: COMPLETE, IDEMPOTENT, REGISTRY-UNTOUCHED ------------------------------
print("\n7. backfill against the frozen fixture snapshot")
snap_src = os.path.join(FIX, "registry_snapshot.jsonl")
snap = os.path.join(_tmp, "snapshot.jsonl")
shutil.copyfile(snap_src, snap)
with open(snap, "rb") as f:
    reg_bytes_before = f.read()
idx2 = os.path.join(_tmp, "semindex2.jsonl")
os.environ["SP_SEM_INDEX"] = idx2
with open(snap, encoding="utf-8") as f:
    srows = [json.loads(x) for x in f if x.strip()]
r1 = SX.backfill(srows)
cov = SX.coverage(srows)
check("coverage 1.0 after one pass", cov["coverage"] == 1.0, cov)
r2 = SX.backfill(srows)
check("second pass mints zero (idempotent)", r2["minted"] == 0, r2)
check("verify green on the backfilled index", SX.verify(srows) == [])
with open(snap, "rb") as f:
    check("registry snapshot BYTE-IDENTICAL after backfill", f.read() == reg_bytes_before)
os.environ["SP_SEM_INDEX"] = IDX

print("\nG-SEM-INDEX: %d pass, %d fail" % (PASS, FAIL))
rdir = os.path.join(ROOT, "var", "sem", "receipts")
os.makedirs(rdir, exist_ok=True)
with open(os.path.join(rdir, "g_sem_index.json"), "w", encoding="utf-8") as f:
    json.dump({"name": "g_sem_index", "pass": PASS, "fail": FAIL,
               "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, f, indent=2)
sys.exit(1 if FAIL else 0)
