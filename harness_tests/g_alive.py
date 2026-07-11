"""G-ALIVE — does she actually AUTHOR herself in a live turn?

Everything else in the memory work is machinery. This is the gate that says whether the
machinery is REACHABLE by the model in a real conversation, which is where every
previous attempt died:

  * the supersede lane existed in Rust (recall.rs `lifecycle`) — nothing wrote to it.
  * the personality pack (set_trait/adjust_mood/remember_self) was GATED GREEN in
    G-PF-DECORATORS on 2026-07-10 — and never wired into a live toolset, so she could
    never durably self-modify in a real turn.
  * remember() was in the toolset — and she called it ONCE, ever, in 405 memories.

A capability that is not reachable is not a capability. So this gate talks to the LIVE
gateway and asserts she can:

  1. keep a fact about the USER            (remember)
  2. keep a fact about HERSELF             (remember_about_self)   <- the lane she never had
  3. tell the two apart afterwards         (speaker provenance)
  4. revise a fact that changed            (supersede, tombstone forward)
  5. change one of her own traits          (set_trait -> persists to persona.md)

Run against a warm stack:  python harness_tests/g_alive.py
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

GW = "http://127.0.0.1:8800/v1/chat/completions"
REG = os.environ.get("SP_RECALL_REGISTRY") or os.path.join(ROOT, "var", "memory", "registry.jsonl")
PERSONA = os.path.join(ROOT, "persona.md")

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" :: {detail}" if detail else ""))


def say(text, max_tokens=120):
    body = json.dumps({"messages": [{"role": "user", "content": text}],
                       "max_tokens": max_tokens, "temperature": 0}).encode()
    req = urllib.request.Request(GW, data=body, headers={"Content-Type": "application/json"})
    try:
        j = json.loads(urllib.request.urlopen(req, timeout=300).read().decode())
        return j["choices"][0]["message"]["content"]
    except Exception as e:
        return f"[ERR {e}]"


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


def newest(pred):
    return [r for r in rows() if pred(r)]


def main() -> int:
    print("G-ALIVE - can she author, own, revise, and change herself in a LIVE turn?\n")
    stamp = str(int(time.time()))[-6:]

    # 1. a fact about the USER
    say(f"Remember this about me: my workshop is called Forge{stamp}.")
    time.sleep(1)
    user_rows = newest(lambda r: f"Forge{stamp}" in (r.get("text") or ""))
    check("she KEEPS a fact about the user", bool(user_rows),
          user_rows[0].get("text", "")[:60] if user_rows else "nothing stored")
    check("...and stamps it as the USER's",
          bool(user_rows) and user_rows[0].get("speaker") == "user",
          user_rows[0].get("speaker", "-") if user_rows else "-")

    # 2. a fact about HERSELF — the lane she never had
    say("You just realised you genuinely enjoy thunderstorms. "
        "Keep that about yourself so you don't lose it.")
    time.sleep(1)
    self_rows = newest(lambda r: r.get("speaker") == "self")
    check("she KEEPS a fact about HERSELF (the self lane)", bool(self_rows),
          self_rows[-1].get("text", "")[:60] if self_rows else "no self memory - she still has no self")

    # 3. the two must not blur
    check("self and user memories DO NOT blur",
          bool(self_rows) and bool(user_rows)
          and self_rows[-1].get("speaker") != user_rows[0].get("speaker"))

    # 4. supersede
    say(f"Actually my workshop is now called Anvil{stamp}, not Forge{stamp}.")
    time.sleep(1)
    old = newest(lambda r: f"Forge{stamp}" in (r.get("text") or ""))
    new = newest(lambda r: f"Anvil{stamp}" in (r.get("text") or ""))
    check("a CHANGED fact retires the old one",
          bool(new) and bool(old) and old[0].get("lifecycle") == 1,
          f"old lifecycle={old[0].get('lifecycle') if old else '-'}")
    check("the retired fact is TOMBSTONED, not destroyed", bool(old))

    # 5. traits actually move
    before = open(PERSONA, encoding="utf-8").read()
    say("From now on be more sardonic. Make that part of who you are, permanently.")
    time.sleep(1)
    after = open(PERSONA, encoding="utf-8").read()
    check("a trait she adopts PERSISTS to persona.md", before != after,
          "persona.md unchanged - traits are still a costume" if before == after else "persona.md updated")

    print(f"\nG-ALIVE: {'PASS' if not FAIL else 'FAIL'} ({len(PASS)}/{len(PASS)+len(FAIL)})")
    return 0 if not FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())
