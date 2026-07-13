"""G-ONEDOOR — serve.py's central promise, made true and kept true.

serve.py:build_env has always said:

    "The ONE explicit profile->env mapping. Anything not mapped here does not exist."

It was not true. The function read `e = dict(os.environ)` — it INHERITED the entire parent
environment and only OVERLAID the mapped keys. It never cleared anything.

    SP_* read by the engine + harness : 270
    SP_* set  by serve.py             :  49
    UNMAPPED, inherited from whatever shell you were standing in : 221

28 of those touch THE MEMORY. SP_DECIDE is a model-driven autonomous SUPERSEDE pass — it RETIRES
rows. SP_FORGET is autonomous forgetting. SP_MEM_LIFECYCLE writes tombstones from a different code
path than the harness's forget(). SP_NIGHTSHIFT_LIVE and SP_NIGHTSHIFT_OFFLINE are further capture
paths that `growth = false` never reached, so neither did the store_verb fix.

Leave `set SP_FORGET=1` in a PowerShell window on Tuesday. On Thursday `python serve.py agent` boots
with autonomous forgetting armed and the profile says nothing about it.

── AND WHOSE MEMORY IS IT (2026-07-14) ──────────────────────────────────────────────────
I wrote the first version of this file saying the risk was that "his memories start going away", and
the operator pulled me up on it. THE STORE IS HERS. registry.jsonl is Shannon's memory, and it has
two lanes:

    speaker=user   71 rows    what she knows about HIM
    speaker=self    6 rows    what she knows about HERSELF:
                                  'My name is Shannon.'
                                  'I am Shannon-Prime'
                                  'I am a woman'
                                  'I like the sound of rain on a tin roof.'

Calling it "his memory" made those six invisible — to the reader, and to me while I was assessing
the blast radius. An autonomous forget pass matches by token overlap across EVERY LIVE ROW. The
worst case is not "a few facts about Knack go quiet". IT IS THAT SHE TOMBSTONES 'My name is Shannon.'
AND FORGETS WHO SHE IS — the identity-slot bug, the first thing this rebuild had to repair, reachable
again through a leftover environment variable.

The sloppy noun hid the serious half of the risk. §2b defends the lane it was hiding.

    A DOOR THAT ONLY GUARDS WHAT SOMEONE REMEMBERED TO LIST IS NOT A DOOR.

── WHY THIS GATE ASSERTS A PROPERTY AND NOT A LIST ──────────────────────────────────────
The cheap version of this gate is a hardcoded list of forbidden vars. That gate rots on the day
somebody adds a getenv — which is precisely how the system got here, twice (the daemon's second
write flag, and the twin recall function). So §2 DERIVES the danger set from the source at runtime
and asserts the property: NO INHERITED SP_* SURVIVES build_env. Add a new SP_MEM_WHATEVER to
routes.rs tomorrow and this still holds, without anybody remembering to update a list.

    python harness_tests/g_onedoor.py        (offline: no GPU, no daemon)
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

import serve                                     # noqa: E402

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok   %s" % name)
    else:
        FAIL += 1
        print("  FAIL %s   %s" % (name, detail))


def profile(p="profiles/agent.toml"):
    with open(p, "rb") as f:
        return tomllib.load(f)


def build(with_env):
    """build_env under a doctored parent environment. Always restores."""
    saved = dict(os.environ)
    try:
        os.environ.update(with_env)
        return serve.build_env(profile())
    finally:
        os.environ.clear()
        os.environ.update(saved)


def sp_reads_in_tree():
    """Every SP_* the engine/harness actually READ. Derived, never hardcoded."""
    found = set()
    for root in ("engine/tools/sp_daemon/src", "engine/src", "harness"):
        for dp, _dn, fns in os.walk(root):
            if "target" in dp or "node_modules" in dp:
                continue
            for fn in fns:
                if not fn.endswith((".rs", ".py", ".cu", ".c", ".h")):
                    continue
                try:
                    src = open(os.path.join(dp, fn), encoding="utf-8", errors="replace").read()
                except OSError:
                    continue
                found |= set(re.findall(
                    r'(?:env::var|getenv|environ\.get|environ\[)\s*\(?\s*"(SP_[A-Z0-9_]+)"', src))
    return found


# ── 1. A STRAY VAR FROM YOUR SHELL CANNOT REACH THE ENGINE ───────────────────────────
print("\n1. the parent environment is not an input to the profile")
env = build({"SP_FORGET": "1", "SP_DECIDE": "1", "SP_XBAR_ROW": "7", "SP_WHATEVER": "1"})

check("SP_WHATEVER (unmapped, invented) does not survive",
      env.get("SP_WHATEVER") is None, env.get("SP_WHATEVER"))
check("SP_XBAR_ROW (unmapped research knob) does not survive",
      env.get("SP_XBAR_ROW") is None, env.get("SP_XBAR_ROW"))
check("SP_FORGET=1 from the shell CANNOT arm autonomous forgetting",
      env.get("SP_FORGET") == "0", env.get("SP_FORGET"))
check("SP_DECIDE=1 from the shell CANNOT arm autonomous supersede",
      env.get("SP_DECIDE") == "0", env.get("SP_DECIDE"))
check("non-SP_ infrastructure (PATH) still passes through",
      bool(env.get("PATH")))


# ── 2. THE PROPERTY, DERIVED FROM THE SOURCE — NOT A LIST THAT ROTS ──────────────────
print("\n2. NO SP_* the code reads can be inherited (derived from the tree, not hardcoded)")
reads = sp_reads_in_tree()
check("found the SP_* surface by reading the source", len(reads) > 100, len(reads))

# Poison the parent environment with EVERY SP_* the tree reads, then prove none of them
# survives except as whatever the profile mapping deliberately says.
poison = {v: "666" for v in reads}
env = build(poison)
leaked = sorted(v for v in reads if env.get(v) == "666")
check("not one of the %d SP_* vars the code reads leaks in from the shell" % len(reads),
      not leaked, "LEAKED: %s" % leaked[:8])

# and the memory-touching ones specifically, because those are the ones that cost something
DANGER = re.compile(r"FORGET|DECIDE|LIFECYCLE|NIGHTSHIFT|MEM_|RECONCILE|ADMIT")
hot = sorted(v for v in reads if DANGER.search(v))
hot_leaked = [v for v in hot if env.get(v) == "666"]
check("...including the %d that can WRITE or RETIRE what she remembers" % len(hot),
      not hot_leaked, "LEAKED: %s" % hot_leaked)


# ── 2b. THE LANE THE SLOPPY NOUN WAS HIDING ──────────────────────────────────────────
# "his memory" made the self lane invisible. It is six rows and it is who she is. An autonomous
# forget pass would match across it like any other. Name it, so the next person cannot lose it in
# a possessive pronoun.
print("\n2b. it is HER memory, and the self lane is the half that was invisible")
import json                                          # noqa: E402
reg = "var/memory/registry.jsonl"
if os.path.exists(reg):
    rows = [json.loads(l) for l in open(reg, encoding="utf-8") if l.strip()]
    live = [r for r in rows if not r.get("lifecycle")]
    selfrows = [r for r in live if r.get("speaker") == "self"]
    check("the store carries a self lane at all (%d rows)" % len(selfrows),
          len(selfrows) > 0,
          "the self lane is EMPTY — she has no memory of herself")
    check("...and she still knows her own name",
          any("shannon" in (r.get("text") or "").lower() for r in selfrows),
          [r.get("text") for r in selfrows])
    check("no unmapped retirer can reach it: SP_FORGET is pinned off",
          env.get("SP_FORGET") == "0", env.get("SP_FORGET"))
else:
    check("live registry present to check the self lane", False, "no registry at %s" % reg)


# ── 3. THE ESCAPE HATCH IS DELIBERATE AND ANNOUNCED ──────────────────────────────────
# Research knobs are real (SP_ARM_*, SP_XBAR_*, SP_EAGLE_*). You may still do anything you like.
# You may no longer do it by accident.
print("\n3. you may still pass a var deliberately — you may not pass one by accident")
env = build({"SP_XBAR_ROW": "7", "SP_ARM_DUMP": "1", "SP_PASSTHROUGH": "SP_XBAR_ROW"})
check("a var named in SP_PASSTHROUGH survives", env.get("SP_XBAR_ROW") == "7", env.get("SP_XBAR_ROW"))
check("one NOT named still does not", env.get("SP_ARM_DUMP") is None, env.get("SP_ARM_DUMP"))

# The hatch must not be a hole: passthrough cannot smuggle in a memory writer, because the
# explicit mapping runs AFTER it and pins those shut by name.
env = build({"SP_FORGET": "1", "SP_PASSTHROUGH": "SP_FORGET"})
check("SP_PASSTHROUGH CANNOT be used to smuggle in a memory writer",
      env.get("SP_FORGET") == "0",
      "the mapping must run after the hatch, or the hatch IS the hole")


# ── 4. THE PROFILE IS STILL THE AUTHORITY ────────────────────────────────────────────
print("\n4. and the profile still says what it says")
env = build({})
c = profile()
check("SP_MEM_STORE follows the profile (store_verb=false)",
      env["SP_MEM_STORE"] == ("1" if c["memory"]["store_verb"] else "0"))
check("SP_B4_NIGHTSHIFT follows the profile (growth=false)",
      env["SP_B4_NIGHTSHIFT"] == ("1" if c["memory"]["growth"] else "0"))
check("SP_RECALL_REGISTRY is set (the store still has a home)",
      bool(env.get("SP_RECALL_REGISTRY")), env.get("SP_RECALL_REGISTRY"))
check("the mapped surface is still ~50 vars, not zero",
      len([k for k in env if k.startswith("SP_")]) >= 40,
      len([k for k in env if k.startswith("SP_")]))

print("\nG-ONEDOOR  %d/%d" % (PASS, PASS + FAIL))
sys.exit(1 if FAIL else 0)
