#!/usr/bin/env python
"""G-MEMCLASS — ONE class vocabulary, everyone consumes it, drift is convicted at the
source (INVARIANT-ROADMAP.md Tier 1.2).

The incident this gate exists to make structurally unrepeatable: the 2026-07-12 engine
fix (fact -> system delivery — "a remembered thing is CONTEXT, not a command") was
applied in ONE of THREE class->delivery copies. okf_mem.py and self_model.py still said
fact -> recite until 2026-07-14. An invariant fixed in one of three copies is fixed in
none.

  1. THE REGISTRY IS WELL-FORMED. Every delivery in the known vocabulary; every class
     has a producer or an explicit operator-only note; private-secret is
     attr-gate-strict (the safety floor, non-negotiable).
  2. THE PYTHON SITES CONSUME, NOT COPY. okf_mem and self_model equal the registry's
     projections, AND their sources no longer contain a class->delivery dict literal
     (equality can be faked by a faithful copy — the absence of the literal cannot).
  3. THE PRODUCER HONORS ITS DECLARATION. lifecycle.classify(), probed with the
     verified per-class templates, emits exactly what the registry says it may.
  4. THE ENGINE IS PINNED AT THE SOURCE. recall.rs cannot import Python, so its
     class_default_delivery match arms and classify_mem_class returns are PARSED OUT
     OF THE RUST SOURCE and held to the registry (the G-ONEDOOR derive-from-source
     trick). The day someone edits one side, this fails — that day, not eight weeks in.
  5. THE VERDICT LAYER'S INPUT IS COVERED. Every class coordinate in the committed
     memory verdict table is a registry class; every class the spine's decider
     branches on has a registry entry with a producer story.

OFFLINE. No GPU, no daemon.
"""
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.environ["SP_DAEMON_URL"] = "http://127.0.0.1:9"

from harness.skills import memclass as MC                  # noqa: E402

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok   %s" % name)
    else:
        FAIL += 1
        print("  FAIL %s   %s" % (name, str(detail)[:220]))


def src(relpath):
    with open(os.path.join(ROOT, relpath), encoding="utf-8") as f:
        return f.read()


# -- 1. WELL-FORMED --------------------------------------------------------------------------
print("\n1. the registry is well-formed")
bad = [c for c, r in MC.REGISTRY.items()
       if r["delivery"] not in MC.DELIVERIES and not r["delivery"].startswith("route:")]
check("every delivery is vocabulary", not bad, bad)
bad = [c for c, r in MC.REGISTRY.items() if not r.get("producers")]
check("every class declares its producers", not bad, bad)
check("private-secret is attr-gate-strict (the safety floor)",
      MC.REGISTRY["private-secret"]["delivery"] == "attr-gate-strict")
check("fact is system (the 2026-07-12 fix, held)",
      MC.REGISTRY["fact"]["delivery"] == "system")

# -- 2. CONSUMERS, NOT COPIES ----------------------------------------------------------------
print("\n2. the python sites consume, not copy")
import importlib                                            # noqa: E402
sys.path.insert(0, os.path.join(ROOT, "tools"))
okf = importlib.import_module("okf_mem")
check("okf_mem.MEM_CLASSES == registry", okf.MEM_CLASSES == set(MC.CLASSES),
      okf.MEM_CLASSES ^ set(MC.CLASSES))
check("okf_mem.CLASS_DEFAULT_DELIVERY == registry projection",
      okf.CLASS_DEFAULT_DELIVERY == MC.delivery_map())
from harness.personality import self_model as sm            # noqa: E402
check("self_model._CLASS_DELIVERY == registry projection",
      sm._CLASS_DELIVERY == MC.delivery_map())
for rel in ("tools/okf_mem.py", "harness/personality/self_model.py"):
    body = src(rel)
    literal = re.search(r'"private-secret"\s*:\s*"attr-gate-strict"', body)
    check("%s carries no class->delivery literal (imports, not copies)" % rel,
          literal is None)

# -- 3. THE PRODUCER HONORS ITS DECLARATION ---------------------------------------------------
print("\n3. lifecycle.classify emits what the registry says it may")
from harness.skills import lifecycle as lc                  # noqa: E402
declared = MC.produced_by("lifecycle.classify")
probes = {
    "fact": "Knack's front gate is painted teal",
    "preference": "Knack's favourite soup is spicy laksa",
    "relationship": "Knack's best friend is a carpenter named Sol",
    "identity": "My name is Knack",
    "event": "Knack's flight to Perth is on the twelfth",
    "private-secret": "My secret access code is 9137",
}
for want, text in sorted(probes.items()):
    got = lc.classify(text)
    check("probe lands in %r" % want, got == want, got)
    check("  ...and %r is a declared production" % got, got in declared, declared)

# -- 4. THE ENGINE, PINNED AT THE SOURCE ------------------------------------------------------
print("\n4. recall.rs held to the registry (parsed from source)")
rs = src("engine/tools/sp_daemon/src/recall.rs")
m = re.search(r"fn class_default_delivery.*?\n}", rs, re.S)
check("class_default_delivery found in recall.rs", m is not None)
if m:
    pairs = {}
    for arm in re.finditer(r'((?:"[a-z\-]+"\s*\|\s*)*"[a-z\-]+")\s*=>\s*"([a-z\-]+)"',
                           m.group(0)):
        for cls in re.findall(r'"([a-z\-]+)"', arm.group(1)):
            pairs[cls] = arm.group(2)
    bad = [(c, d, MC.delivery_for(c)) for c, d in pairs.items()
           if c in MC.REGISTRY and d != MC.REGISTRY[c]["delivery"]]
    check("every engine match arm equals the registry (%d arms)" % len(pairs),
          not bad, bad)
    alien = [c for c in pairs if c not in MC.REGISTRY]
    check("no engine class is outside the registry", not alien, alien)
m = re.search(r"fn classify_mem_class.*?\n}", rs, re.S)
check("classify_mem_class found in recall.rs", m is not None)
if m:
    emits = set(re.findall(r'return "([a-z\-]+)";', m.group(0)))
    emits |= {mm for mm in re.findall(r'^\s*"([a-z\-]+)"\s*$', m.group(0), re.M)}
    declared_rs = MC.produced_by("recall.rs.classify_mem_class")
    check("engine classifier emits exactly its declared productions",
          emits == set(declared_rs), (sorted(emits), sorted(declared_rs)))

# -- 5. THE VERDICT LAYER'S INPUT ------------------------------------------------------------
print("\n5. sigma's class coordinate is covered")
with open(os.path.join(HERE, "fixtures", "sem", "verdict-table.json"),
          encoding="utf-8") as f:
    cells = json.load(f)["table"]
used = {dict(p.split("=") for p in c.split("|"))["class"] for c in cells}
check("every verdict-table class is a registry class", used <= set(MC.CLASSES),
      used - set(MC.CLASSES))
spine = src("harness/control/spine.py")
branched = set(re.findall(r'mem_class[^\n]*?==\s*"([a-z\-]+)"', spine))
branched |= set(re.findall(r'get\("mem_class"[^\n]*?==\s*"([a-z\-]+)"', spine))
bad = [c for c in branched if c not in MC.REGISTRY]
check("every class the decider branches on has a registry entry (%s)"
      % sorted(branched), not bad, bad)

print("\nG-MEMCLASS: %d pass, %d fail" % (PASS, FAIL))
rdir = os.path.join(ROOT, "var", "sem", "receipts")
os.makedirs(rdir, exist_ok=True)
with open(os.path.join(rdir, "g_memclass.json"), "w", encoding="utf-8") as f:
    json.dump({"name": "g_memclass", "pass": PASS, "fail": FAIL,
               "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, f, indent=2)
sys.exit(1 if FAIL else 0)
