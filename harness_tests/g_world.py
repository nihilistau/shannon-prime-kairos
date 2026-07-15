#!/usr/bin/env python
"""G-WORLD — the standing world obeys the table (CONTINUITY.md N1; the verdict layer
guarding the newest, most ambient surface in the system).

The block sits in EVERY prompt of a session. What may live there is therefore the
strictest rendering surface we have, and its laws are ∀-checks over the composed block
against a registry built through the REAL writer:

  1. THE SPINE IS THERE, FRAMED: his facts render as his ("Knack told me:"), ranked by
     salience within the word budget.
  2. NEVER A TOMBSTONE: a superseded fact vanishes from the world on the next refresh.
  3. NEVER A SECRET, EVER: private-secret rows never enter the block — the one
     absolute. An ambient secret in every prompt is the worst possible leak surface;
     secrets remain fetch-on-direct-ask behind the seam's decline.
  4. HER VOICE IS HERS: an uncovered inference appears as "I've come to think:";
     a COVERED inference (his words already speak to it) stays home — the same
     competition coordinate as the recall seam, query-free.
  5. NOT HER LANE: self-rows never appear (render_self_model owns that slot).
  6. THE KV-PREFIX LAW: the block is process-cached — a remember() after first
     composition does NOT change it; refresh() does. Off (SP_WORLD unset) is empty.
  7. THE BUDGET HOLDS: never more than the word budget, however fat the store.

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
_tmp = tempfile.mkdtemp(prefix="g_world_")
REG = os.path.join(_tmp, "reg.jsonl")
open(REG, "w").close()
os.environ["SP_RECALL_REGISTRY"] = REG
for _k in [k for k in os.environ if k.startswith("SP_SEM_")]:
    del os.environ[_k]
os.environ.pop("SP_WORLD", None)

from harness.skills import memory as M                      # noqa: E402
from harness.skills import world as W                       # noqa: E402

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok   %s" % name)
    else:
        FAIL += 1
        print("  FAIL %s   %s" % (name, str(detail)[:200]))


# the world, through the real writer
M.remember("My cat's name is Tuffy", source="user turn")
M.remember("Knack's favourite tea is Oolong", source="user turn")
M.remember("My secret alarm code is 8842", source="user turn")          # NEVER ambient
M.remember("Knack is terrified of open water", source="user turn")
M.remember("Knack is comfortable in open water", source="reflection pass")   # covered
M.remember("Knack is warming to early starts lately", source="reflection pass")  # hers
M.remember_about_self("I like the hour just before sunrise")             # her lane

# -- 6a. OFF IS OFF -------------------------------------------------------------------------
print("\n1. off is off")
check("SP_WORLD unset -> empty block", W.render_world() == "")

os.environ["SP_WORLD"] = "1"
block = W.refresh()

# -- 1. THE SPINE ---------------------------------------------------------------------------
print("\n2. the spine, framed")
check("the block exists and carries the header", block.startswith(W._HEADER), block[:80])
check("his facts are there, IN THE PREFIX'S GRAMMAR (his, not quoted 'my' — the "
      "ownership-tangle field bug)",
      "His cat's name is Tuffy" in block, block)
check("his first person never appears ambient",
      "My cat" not in block and "my cat" not in block, block)
check("preferences included", "Oolong" in block)

# -- 3. NEVER A SECRET ----------------------------------------------------------------------
print("\n3. never a secret, ever")
check("the secret's digits are NOT ambient", "8842" not in block)
check("the secret's text is NOT ambient", "alarm code" not in block)

# -- 4. HER VOICE ---------------------------------------------------------------------------
print("\n4. her voice is hers; covered stays home")
check("her uncovered conclusion appears addressed to her (the prefix speaks in 'you')",
      "You've come to think: Knack is warming to early starts lately" in block, block)
check("the covered inference stays home (his words speak to open water)",
      "comfortable in open water" not in block)
check("his testimony on that subject IS there",
      "terrified of open water" in block)

# -- 5. NOT HER LANE ------------------------------------------------------------------------
print("\n5. lanes")
check("self-rows never appear (render_self_model owns that slot)",
      "sunrise" not in block)

# -- 2 + 6. TOMBSTONES AND THE KV-PREFIX LAW ------------------------------------------------
print("\n6. tombstones vanish on refresh; the cache holds until then")
M.remember("My cat's name is Milo", source="user turn")     # supersedes Tuffy (slot)
cached = W.render_world()
check("the cache HOLDS after a remember (no mid-session prefix bust)",
      cached == block)
fresh = W.refresh()
check("after refresh: the tombstoned fact is gone", "Tuffy" not in fresh, fresh)
check("...and the successor is in", "Milo" in fresh)

# -- 7. THE BUDGET --------------------------------------------------------------------------
print("\n7. duplicates render once")
open(REG, "a", encoding="utf-8").close()
M.remember("Knack's favourite biscuit is the ginger nut", source="user turn")
rows_now = [json.loads(x) for x in open(REG, encoding="utf-8") if x.strip()]
dup = next(r for r in rows_now if "ginger nut" in (r.get("text") or ""))
with open(REG, "a", encoding="utf-8") as f:      # the store's real duplicate shape
    f.write(json.dumps({**dup, "name": dup["name"] + "_dup"}, ensure_ascii=False) + "\n")
fresh2 = W.refresh()
check("a duplicated row renders exactly once",
      fresh2.count("ginger nut") == 1, fresh2.count("ginger nut"))

print("\n8. the budget holds under a fat store")
for i in range(60):
    M.remember("Knack's shelf number %d is painted a different colour" % i,
               source="user turn")
fat = W.refresh()
check("never more than the word budget (+header)",
      len(fat.split()) <= W._BUDGET_WORDS + len(W._HEADER.split()) + 5,
      len(fat.split()))

print("\nG-WORLD: %d pass, %d fail" % (PASS, FAIL))
rdir = os.path.join(ROOT, "var", "sem", "receipts")
os.makedirs(rdir, exist_ok=True)
with open(os.path.join(rdir, "g_world.json"), "w", encoding="utf-8") as f:
    json.dump({"name": "g_world", "pass": PASS, "fail": FAIL,
               "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, f, indent=2)
sys.exit(1 if FAIL else 0)
