"""G-PREFIX — 164 SECONDS TO SAY HELLO, AND THE CACHE THAT WAS THROWN AWAY.

    == baseline turn (163,978 ms, 1 model call)
       she said: 'Hello! How are you today?'
       !! RE-PREFILL 2679 tok in 163.3s -- the cache was thrown away

Of those 2679 tokens, 2517 were the SAME PREAMBLE already sitting correct in VRAM. 94% of the
work was done. It was binned because the other 6% differed.

WHY THE TWO EXISTING INSTRUMENTS BOTH MISSED
────────────────────────────────────────────
  THE JOURNAL (rewind) restores a TAIL, bounded by Jmax (~64 positions). A new conversation
  diverges by the ENTIRE previous conversation -- hundreds or thousands of tokens. No journal
  depth reaches that, and each position costs VRAM. Wrong instrument.

  THE SHEAR restores a PREFIX in O(1) with no copies -- but only while the SWA ring has never
  wrapped. The preamble is 2517 tokens and ring_W is 2048, SO THE RING WRAPS INSIDE THE
  PREAMBLE ITSELF. It refuses, correctly, every single time. It was dead code at this config.
  (And its guard asked "is dpos past the ring NOW?" as a proxy for "has the ring EVER wrapped?"
  -- grow past it, rewind back under it, and the guard passes onto clobbered rows. That is the
  P1c-2 KV corruption. Fixed: the session now REMEMBERS the wrap instead of inferring it.)

So: COPY THE BYTES. A snapshot does not reason about wrapping at all -- it restores the cache
to the exact state it was in.

WHAT THIS GATE ASSERTS, AND WHY THE SECOND ONE IS THE ONE THAT MATTERS
─────────────────────────────────────────────────────────────────────
  1. SPEED     -- a new conversation restores instead of re-prefilling.
  2. CORRECTNESS -- THE RESTORED CACHE PRODUCES THE IDENTICAL ANSWER.

(2) is the whole gate. (1) is easy to fake and easy to be pleased by. A restore that writes
slightly wrong bytes into the KV would be JUST AS FAST and would quietly poison every answer
after it -- she would keep talking, fluently, from a cache that is not hers. That is the exact
failure class this project keeps producing: not a crash, not an error, a thing he TRUSTED that
quietly was not true. So we do the same turn with the snapshot ON and OFF, at temperature 0,
and demand the text be BYTE-IDENTICAL.

    python harness_tests/g_prefix.py        (needs the stack up)
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GATEWAY = "http://127.0.0.1:8800/v1/chat/completions"
LOG = os.path.join(ROOT, "var", "daemon.log")

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" :: {detail}" if detail else ""), flush=True)


def log_mark():
    try:
        return len(open(LOG, "r", errors="replace").readlines())
    except Exception:
        return 0


def log_since(n):
    try:
        return open(LOG, "r", errors="replace").readlines()[n:]
    except Exception:
        return []


def say(messages, max_tokens=40, temperature=0.0):
    body = {"messages": messages, "max_tokens": max_tokens, "temperature": temperature}
    req = urllib.request.Request(GATEWAY, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=900) as r:
        raw = r.read().decode("utf-8", "replace")
    dt = (time.time() - t0) * 1000
    try:
        out = json.loads(raw)["choices"][0]["message"]["content"]
    except Exception:
        out = raw[:120]
    return out, dt


# A conversation long enough that its divergence blows the rewind bound (63). This is the
# ONLY thing that forces the snapshot path; a short one is absorbed by the journal and the
# gate would pass without ever testing what it claims to test.
LONG = [
    "Hello. What's your name?",
    "What kind of music do you like?",
    "Tell me one short thought about rain.",
    "And what did I just ask you about?",
]

NEW = [{"role": "user", "content": "Hi there."}]


def run_long_conversation():
    hist = []
    for t in LONG:
        hist.append({"role": "user", "content": t})
        out, _ = say(hist, max_tokens=50, temperature=0.7)
        hist.append({"role": "assistant", "content": out})
    return hist


def turn_used(lines):
    """What did the cache actually DO on that turn? Read it from the daemon, not from hope."""
    if any("PREFIX-SNAPSHOT: restored" in l for l in lines):
        return "restore"
    if any("PREFIX-SNAPSHOT: captured" in l for l in lines):
        return "capture"       # a genuine FULL prefill, plus the snapshot -- our reference
    for l in lines:
        m = re.search(r"prefill (\d+) tok in", l)
        if m and int(m.group(1)) > 256:
            return "full-prefill"
    return "reuse"


def main() -> int:
    print("G-PREFIX - 164 seconds to say hello.\n", flush=True)
    print("  Requires a FRESH daemon (the snapshot lives in process memory).", flush=True)
    print("  Turn 1 CAPTURES (a real full prefill = the reference answer).", flush=True)
    print("  Turn 2 RESTORES. The two answers must be IDENTICAL.\n", flush=True)

    # ── THE REFERENCE: a genuine FULL PREFILL ────────────────────────────────────────
    # On a fresh daemon there is no snapshot, so this new-conversation turn takes the CAPTURE
    # path: reset, prefill the whole shared prefix from token 0, snapshot it, prefill the
    # suffix. That is a real cold prefill — the exact thing the restore has to reproduce.
    #
    # THIS IS WHY THE GATE NEEDS A FRESH DAEMON AND CANNOT JUST RUN TWICE. My first cut of
    # this ran the same path twice and called it an A/B. Both turns would have restored, both
    # would have agreed, and it would have "proved" correctness while testing nothing. A gate
    # that compares a thing to itself always passes.
    run_long_conversation()
    mark = log_mark()
    ref_text, ref_ms = say(NEW, temperature=0.0)
    ref_how = turn_used(log_since(mark))
    print(f"  reference turn: {ref_how}, {ref_ms:.0f} ms\n", flush=True)
    check("the reference turn was a REAL full prefill (not already a restore)",
          ref_how in ("capture", "full-prefill"),
          f"{ref_how} — run this on a FRESH daemon or it proves nothing")

    # ── 1. SPEED: after a long conversation, a NEW one must RESTORE ──────────────────
    run_long_conversation()
    mark = log_mark()
    on_text, on_ms = say(NEW, temperature=0.0)
    lines = log_since(mark)
    how = turn_used(lines)
    restored = [l for l in lines if "PREFIX-SNAPSHOT: restored" in l]

    check("a new conversation RESTORES the shared preamble", how == "restore",
          restored[0].split("routes: ")[-1].strip()[:76] if restored else f"took the {how} path")
    check("and it is fast", on_ms < 20_000, f"{on_ms:.0f} ms (the bug was 163,978 ms)")

    # ── 2. CORRECTNESS. THE ONE THAT MATTERS. ────────────────────────────────────────
    # A restore that writes subtly wrong bytes into the KV is JUST AS FAST and poisons every
    # answer after it — she keeps talking, fluently, out of a cache that is not hers. Speed is
    # easy to be pleased by. Only the TEXT proves it. Temperature 0 on both sides.
    check("THE RESTORED CACHE GIVES THE IDENTICAL ANSWER",
          on_text.strip() == ref_text.strip(),
          f"full-prefill: {ref_text.strip()[:34]!r}  |  restored: {on_text.strip()[:34]!r}")

    # ── 3. she can still READ the restored prefix (it is not just non-crashing bytes) ──
    hist = list(NEW) + [{"role": "assistant", "content": on_text},
                        {"role": "user", "content": "What is your name? One word."}]
    name, _ = say(hist, max_tokens=12, temperature=0.0)
    check("she can still read her own persona out of the restored cache",
          "shannon" in name.lower(), name.strip()[:40])

    total = len(PASS) + len(FAIL)
    print(f"\nG-PREFIX: {'PASS' if not FAIL else 'FAIL'} ({len(PASS)}/{total})", flush=True)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
