"""G-ADMISSION — is the B4 firehose actually off?

The registry audit found 487 rows, ~375 of them voice/ASR TEST CORPUS that the B4
auto-capture had swallowed because the admission gate was "any declarative, 4..120
words, not a question":

    "The kind nurse painted the tall building as the sun went down."
    "A lonely sailor polished the garden as the church bells rang."

Grammatical. Declarative. In range. About NOBODY. They then surfaced mid-answer as
"recalled memories" — the recall misfire.

A durable fact is ABOUT SOMEONE. This gate feeds the daemon exactly the kind of
sentence that filled the registry 404 times and asserts it is now REFUSED, while a
real personal fact still lands — and lands with the v2 schema (speaker/lifecycle),
not the old "The user said:" framing.

Run against a warm stack:  python harness_tests/g_admission.py
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


def say(text):
    body = json.dumps({"messages": [{"role": "user", "content": text}],
                       "max_tokens": 60, "temperature": 0}).encode()
    req = urllib.request.Request(GW, data=body, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=300).read()
    except Exception as e:
        print(f"    (turn error: {e})")


def rows():
    out = []
    try:
        for ln in open(REG, encoding="utf-8", errors="replace"):
            ln = ln.strip()
            if ln:
                try:
                    out.append(json.loads(ln))
                except Exception:
                    pass
    except OSError:
        pass
    return out


def stored(needle):
    return [r for r in rows() if needle in (r.get("text") or "")]


def main() -> int:
    print("G-ADMISSION - a memory is about SOMEONE. Is the firehose off?\n")
    tag = str(int(time.time()))[-6:]

    # 1. THE EXACT SHAPE THAT FILLED THE REGISTRY 404 TIMES — must be REFUSED
    junk = f"The kind nurse painted the tall building{tag} as the sun went down."
    say(junk)
    time.sleep(1)
    check("an IMPERSONAL declarative is REFUSED (the test-corpus shape)",
          not stored(f"tall building{tag}"),
          "captured anyway - the firehose is still on" if stored(f"tall building{tag}") else "not captured")

    # 2. a real personal fact must STILL land
    real = f"My workshop bench is made of oak{tag}."
    say(real)
    time.sleep(1)
    hit = stored(f"oak{tag}")
    check("a PERSONAL fact still lands", bool(hit),
          (hit[0].get("text") or "")[:50] if hit else "lost - the gate is too tight")

    # 3. and it lands in the v2 schema, not the old framing
    check("it carries a SPEAKER (v2 schema)",
          bool(hit) and hit[0].get("speaker") == "user",
          hit[0].get("speaker", "-") if hit else "-")
    check("it carries LIFECYCLE (so it can be superseded)",
          bool(hit) and hit[0].get("lifecycle") == 0)
    check("the 'The user said:' framing is GONE",
          bool(hit) and not (hit[0].get("text") or "").startswith("The user said:"),
          (hit[0].get("text") or "")[:40] if hit else "-")

    # 4. episodes live next to the registry, not inside the engine source tree
    if hit:
        d = (hit[0].get("dir") or "").replace("\\", "/")
        check("the episode lives with the DATA, not in the engine tree",
              "_nightshift_live" not in d,
              d[-46:] if d else "-")

    print(f"\nG-ADMISSION: {'PASS' if not FAIL else 'FAIL'} ({len(PASS)}/{len(PASS)+len(FAIL)})")
    return 0 if not FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())
