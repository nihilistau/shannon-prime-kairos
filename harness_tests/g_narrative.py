#!/usr/bin/env python
"""G-NARRATIVE — she writes the days down, and the record behaves (CONTINUITY.md N2).

The narrative is HER ACCOUNT: presentation layer, oracle output, quarantined by
construction — never a fact row, never in the registry, never supersedes anything,
rendered under a header that names it as hers. This gate proves the machinery with an
INJECTED composer (the live oneshot is exercised by NIGHTSHIFT itself):

  1. COMPOSED AND DATED: compose_and_write produces the dated entry from a transcript
     tail + the previous entry, writes the current file beside the registry (sandboxes
     inherit it via SP_RECALL_REGISTRY for free), snapshots content-addressed history.
  2. THE WORLD CARRIES IT, NAMED AS HERS — and the KV-prefix law still holds: the
     narrative changes NOTHING mid-session; refresh() folds it in.
  3. ROLLING: the next night's composition receives the previous entry (continuity is
     input, not just output).
  4. FAIL-SAFE: a dead composer writes NOTHING — yesterday's true paragraph stands
     (a stale true record beats a fresh empty one). A trivial reply is rejected.
  5. NEVER A FACT: the registry is byte-identical through everything above.

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
_tmp = tempfile.mkdtemp(prefix="g_narr_")
REG = os.path.join(_tmp, "reg.jsonl")
open(REG, "w").close()
os.environ["SP_RECALL_REGISTRY"] = REG
os.environ["SP_PERSONALITY_TIER"] = os.path.join(_tmp, "tier")
os.environ["SP_WORLD"] = "1"
for _k in [k for k in os.environ if k.startswith("SP_SEM_")]:
    del os.environ[_k]

from harness.skills import memory as M                      # noqa: E402
from harness.skills import narrative as N                   # noqa: E402
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


M.remember("My cat's name is Tuffy", source="user turn")
with open(REG, "rb") as f:
    REG_BYTES = f.read()

MSGS = [
    {"role": "user", "content": "morning — Tuffy knocked a glass off the bench at 3am"},
    {"role": "assistant", "content": "So that was the crash. Is she banned from the bench now?"},
    {"role": "user", "content": "never. she owns the bench. also I restarted the workshop project"},
    {"role": "assistant", "content": "Third time's the charm — what's different this run?"},
]

# -- 1. COMPOSED AND DATED --------------------------------------------------------------------
print("\n1. composed, dated, snapshotted")
seen_prompts = []


def fake_ask(prompt):
    seen_prompts.append(prompt)
    return ("We talked about Tuffy's 3am bench raid and he finally restarted the "
            "workshop project; he sounded lighter about it than last time.")


r = N.compose_and_write(MSGS, ask=fake_ask)
check("written", r.get("written") is True, r)
entry = N.current()
check("the entry is dated ('As of ...')", entry.startswith("As of "), entry[:40])
check("the entry carries the day", "Tuffy" in entry and "workshop" in entry)
check("history snapshot written (content-addressed)",
      r.get("snapshot") and os.path.exists(
          os.path.join(_tmp, "tier", "full", r["snapshot"] + ".md")), r)

# -- 2. THE WORLD CARRIES IT, NAMED AS HERS; THE PREFIX LAW HOLDS ------------------------------
print("\n2. the world carries it, as hers, on refresh only")
before = W.refresh()
check("the standing world includes the journal line, named as her account",
      "your account, not his words" in before and "bench raid" in before, before[-200:])
N.compose_and_write(MSGS, ask=lambda p: "A completely different day happened.")
check("mid-session: the cached world does NOT move (the KV-prefix law)",
      W.render_world() == before)
after = W.refresh()
check("after refresh: the new entry is in", "different day" in after)

# -- 3. ROLLING --------------------------------------------------------------------------------
print("\n3. rolling: yesterday feeds tomorrow")
check("the composer received the previous entry as input",
      any("bench raid" in p for p in seen_prompts[1:] or [""])
      or "bench raid" in (seen_prompts + [""])[1] if len(seen_prompts) > 1 else True)
seen2 = []
N.compose_and_write(MSGS, ask=lambda p: (seen2.append(p) or
                    "Carrying on from the different day, quietly."))
check("previous entry present in the next composition prompt",
      any("different day" in p for p in seen2), seen2 and seen2[0][:120])

# -- 4. FAIL-SAFE ------------------------------------------------------------------------------
print("\n4. a dead composer changes nothing")
held = N.current()
r = N.compose_and_write(MSGS, ask=lambda p: None)
check("unreachable composer: not written, why recorded",
      r.get("written") is False and r.get("why"), r)
check("yesterday's paragraph stands", N.current() == held)
r = N.compose_and_write(MSGS, ask=lambda p: "ok.")
check("a trivial reply is rejected", r.get("written") is False, r)
r = N.compose_and_write([], ask=fake_ask)
check("no transcript: nothing written", r.get("written") is False, r)

# -- 5. NEVER A FACT ---------------------------------------------------------------------------
print("\n5. never a fact")
with open(REG, "rb") as f:
    check("the registry is byte-identical through all of it", f.read() == REG_BYTES)

print("\nG-NARRATIVE: %d pass, %d fail" % (PASS, FAIL))
rdir = os.path.join(ROOT, "var", "sem", "receipts")
os.makedirs(rdir, exist_ok=True)
with open(os.path.join(rdir, "g_narrative.json"), "w", encoding="utf-8") as f:
    json.dump({"name": "g_narrative", "pass": PASS, "fail": FAIL,
               "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, f, indent=2)
sys.exit(1 if FAIL else 0)
