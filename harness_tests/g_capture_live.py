"""G-CAPTURE-LIVE — replay the REAL conversation that filled her memory with banter, and
prove the store now keeps the facts and drops the chatter.

This is the end-to-end arbiter for the two offline gates (g_durability). Offline rules
passing means nothing if the gateway hook is wired into one of two entry points — which is
the single most repeated bug in this system (kairos, the repeat-guard and roleplay each
shipped half-wired). So this drives the LIVE gateway, on the path the console actually
uses, and reads the registry afterwards.

The turns below are verbatim from the transcript that produced the 17 junk rows.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GW = "http://127.0.0.1:8800/v1/chat/completions"
REG = os.environ.get("SP_RECALL_REGISTRY") or os.path.join(ROOT, "var", "memory", "registry.jsonl")

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" :: {detail}" if detail else ""))


def rows():
    out = []
    with open(REG, encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if ln:
                try:
                    out.append(json.loads(ln))
                except Exception:
                    pass
    return out


def say(text, max_tokens=60):
    body = json.dumps({"messages": [{"role": "user", "content": text}],
                       "max_tokens": max_tokens, "temperature": 0.3,
                       "session": "gcap"}).encode()
    req = urllib.request.Request(GW, data=body, headers={"Content-Type": "application/json"})
    r = urllib.request.urlopen(req, timeout=900)
    return json.loads(r.read().decode())["choices"][0]["message"]["content"].strip()


# verbatim from the transcript that produced the junk
BANTER = [
    "you are cool af! I really like you!",
    "yes, we lose lips, sink ships.",
    "well, we make do. you're doing alright for such a constrained system",
]
FACTFUL = "oh i always run my pc's 24/7. so you are lucky there"


def main() -> int:
    print("G-CAPTURE-LIVE — the store keeps facts, not conversation.\n")

    before = {r.get("name", "") for r in rows()}

    for t in BANTER:
        say(t)
        time.sleep(0.4)
    after_banter = [r for r in rows() if r.get("name", "") not in before]
    check("three turns of REAL banter wrote NOTHING to memory",
          not after_banter,
          f"wrote: {[r.get('text') for r in after_banter]}" if after_banter else "")

    before2 = {r.get("name", "") for r in rows()}
    say(FACTFUL)
    time.sleep(0.6)
    new = [r for r in rows() if r.get("name", "") not in before2]
    texts = [r.get("text", "") for r in new]

    check("a turn carrying a real fact DID write one", len(new) >= 1, repr(texts))
    check("...and it kept the FACT",
          any("24/7" in t for t in texts), repr(texts))
    check("...and dropped the banter riding with it",
          not any("lucky" in t.lower() for t in texts), repr(texts))
    check("...stamped as the USER's, since he said it",
          all(r.get("speaker") == "user" for r in new),
          repr([(r.get("speaker"), r.get("mem_class")) for r in new]))

    # the identity slot must still be his, and single-valued
    live_id = [r for r in rows()
               if r.get("mem_class") == "identity" and not r.get("lifecycle")
               and r.get("speaker") == "user"]
    check("the user's identity slot is still HIS, and single",
          len(live_id) == 1 and "knack" in live_id[0].get("text", "").lower(),
          repr([r.get("text") for r in live_id]))

    total = len(PASS) + len(FAIL)
    print(f"\nG-CAPTURE-LIVE: {'PASS' if not FAIL else 'FAIL'} ({len(PASS)}/{total})")
    return 0 if not FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())
