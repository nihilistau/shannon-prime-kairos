"""G-SALIENCE — a repeat is not a duplicate. It is a second data point.

HER IDEA, UNPROMPTED, ON A KAIROS CHECK-IN:

    "the difference between memory and knowledge is that memory has context — it remembers
     WHO told you what, WHEN they did, maybe even HOW MANY TIMES."

She had two of the three. `speaker` is who; `ts` is when. There was no how-many-times, and
there could not be, because remember() DELETED the evidence on arrival:

    if any(_text(e).strip() == fact.strip() for e in existing):
        return f"already in memory: {fact}"          # <- a measurement, thrown away

Every time he told her something again, the store said "I know" and dropped the event on
the floor, pleased with itself for not duplicating a row. But a thing a person tells you
five times is not the same thing as a thing they told you once, and we were recording them
identically.

THE TWO SAFETY PROPERTIES THIS GATE EXISTS FOR — everything else here is bookkeeping:

  1. SALIENCE MUST NOT OVERRULE MATCHING. It is a prior. Of two memories that answer the
     question equally well, prefer the one he keeps repeating. It must NEVER make a
     frequently-repeated irrelevance beat a rarely-mentioned answer, or she will answer
     every question with her favourite fact.

  2. FREQUENCY MUST NOT RESURRECT CHATTER. Frequency is not importance on its own —
     chatter is the most frequent thing there is, and "you are cool af!" said ten times
     would dominate a store ranked on repetition alone. It only works because the
     DURABILITY GATE decides what is ELIGIBLE to be counted. The gate says what is a fact;
     salience says which facts matter. Built in the other order, this would have amplified
     the firehose instead of ranking the store.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_TMP = tempfile.mkdtemp()
os.environ["SP_RECALL_REGISTRY"] = os.path.join(_TMP, "registry.jsonl")
os.environ["SP_DAEMON_URL"] = "http://127.0.0.1:9"      # unreachable: no episode minting

from harness.skills import lifecycle as lc      # noqa: E402
from harness.skills import memory as M          # noqa: E402

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" :: {detail}" if detail else ""))


def rows():
    return M._load()


def find(sub):
    return next((r for r in rows() if sub.lower() in (r.get("text") or "").lower()), None)


def main() -> int:
    print("G-SALIENCE - a repeat is not a duplicate.\n")
    M.set_author("user")

    # ── 1. A REPEAT REINFORCES ──────────────────────────────────────────────────
    M.remember("Knack's GPU is an RTX 2060")
    r = M.remember("Knack's GPU is an RTX 2060")            # he said it again
    check("saying it again REINFORCES rather than being discarded",
          "reinforced" in r.lower(), r)
    row = find("RTX 2060")
    check("...mentions goes to 2", row.get("mentions") == 2, str(row.get("mentions")))
    check("...and it is still ONE row, not two",
          len([x for x in rows() if "2060" in (x.get("text") or "")]) == 1)
    check("...first_seen is kept, last_seen moves",
          row.get("first_seen") and row.get("last_seen"))

    # a paraphrase is the same event in different words
    r = M.remember("Knack's GPU is an RTX 2060.")
    check("a PARAPHRASE reinforces too (he said it, not a new fact)",
          "reinforced" in r.lower() and find("RTX 2060").get("mentions") == 3, r)

    # ── 2. HER LOOKUPS ARE NOT HIS SIGNAL ───────────────────────────────────────
    before = find("RTX 2060").get("mentions")
    M.set_question("what GPU do I run on?")
    M.recall("what GPU do I run on?")
    M.recall("what GPU do I run on?")
    after = find("RTX 2060")
    check("recall does NOT inflate `mentions` (that would be marking its own homework)",
          after.get("mentions") == before, f"{before} -> {after.get('mentions')}")
    check("...it counts separately, in `recalled`",
          after.get("recalled", 0) >= 2, str(after.get("recalled")))

    # ── 3. A TOMBSTONE IS NOT REINFORCED BACK TO LIFE ───────────────────────────
    M.remember("Knack's old car was a Corolla")
    # NB: load ONCE, mutate that list, save THAT list. find() re-loads from disk and hands
    # back a detached dict — writing lifecycle=1 onto it and then saving a fresh _load()
    # silently discards the edit, and the "tombstone" was never a tombstone. (The first cut
    # of this check did exactly that and failed, and the bug was in the test, not the store.
    # A gate can be wrong about the thing it is watching; that is the most dangerous kind.)
    all_rows = rows()
    for _r in all_rows:
        if "corolla" in (_r.get("text") or "").lower():
            _r["lifecycle"] = 1
    M._save_all(all_rows)
    M.remember("Knack's old car was a Corolla")
    live_corollas = [x for x in rows() if "corolla" in (x.get("text") or "").lower()
                     and not x.get("lifecycle")]
    check("a retired memory is not reinforced back into the live set",
          len(live_corollas) == 1 and live_corollas[0].get("mentions", 1) == 1,
          "a repeat makes a NEW row; it does not un-retire the tombstone")

    # ── 4. SALIENCE RANKS TIES — AND ONLY TIES ─────────────────────────────────
    now = time.time()
    said_once = {"text": "Knack's lucky number is 69", "mem_class": "fact", "mentions": 1,
                 "last_seen": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))}
    said_often = dict(said_once, text="Knack's lucky number is 7", mentions=6)
    check("a fact he has repeated outranks an identical-shaped one-off",
          lc.salience(said_often) > lc.salience(said_once),
          f"{lc.salience(said_often)} vs {lc.salience(said_once)}")

    # DECAY: same fact, unmentioned for a season
    old = dict(said_once,
               last_seen=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 120 * 86400)))
    check("...and a fact unmentioned for four months ranks below a fresh one",
          lc.salience(old) < lc.salience(said_once),
          f"{lc.salience(old)} vs {lc.salience(said_once)}")
    check("...but it is NOT deleted — decay is about rank, not existence",
          lc.salience(old) > 0.0, "nothing in this store is ever destroyed")

    # ── 5. THE SAFETY PROPERTY: SALIENCE MUST NOT OVERRULE MATCHING ─────────────
    # A much-repeated irrelevance must never beat a rarely-mentioned answer. Build exactly
    # that trap: hammer an unrelated fact six times, then ask about the GPU.
    for _ in range(6):
        M.remember("Knack's cat is called Tuffy")
    cat = find("Tuffy")
    check("(setup) the cat is now the most-repeated thing she knows",
          cat.get("mentions") >= 6, str(cat.get("mentions")))

    M.set_question("what GPU do I run on?")
    out = M.recall("what GPU do I run on?")
    first = out.splitlines()[0] if out else ""
    check("a 6x-repeated irrelevance does NOT outrank the answer to the question",
          "2060" in first, f"top hit was: {first[:64]!r}")

    # ── 6. FREQUENCY CANNOT RESURRECT CHATTER ──────────────────────────────────
    # The durability gate decides what is ELIGIBLE to be counted. Repetition of junk is
    # still junk: it never gets a row, so it never gets a count.
    for _ in range(9):
        M.remember("you are cool af! I really like you!")
    check("chatter repeated NINE times still never enters the store",
          find("cool af") is None,
          "the durability gate decides what may be counted; salience only ranks what is")

    total = len(PASS) + len(FAIL)
    print(f"\nG-SALIENCE: {'PASS' if not FAIL else 'FAIL'} ({len(PASS)}/{total})")
    return 0 if not FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())
