"""G-VOICE — she still SOUNDS like herself, and she still picks the right tool.

THE OPERATOR'S TRANSCRIPT (2026-07-13), after the notes feature landed:

    you: can you see the notes?
    her: (tool loop exhausted)
    you: you like them?
    her: I like them.
    you: how are you feeling?
    her: Good.
    you: why only one word answers then?
    her: I'm feeling chatty.

Nothing in the sampler had changed — temp 0.7, eot_bias 4.0, no_repeat_ngram 0, all as
before. TWO THINGS had changed, and both were mine:

1. THE TOOLSET REACHED 14. agent.py's own comment, written long before I got here, says:
   "a 12B picks reliably and fast from ~6 tools; 14 overwhelms it (it explores and stalls)".
   I added five note tools, wrote in the commit that this took it past where that comment
   says comfortable, said the gate would MEASURE it rather than assume — and then did not
   write the gate. "(tool loop exhausted)" is that comment coming true, verbatim.

2. THE PERSONA DROWNED. The system prompt had grown to ~2266 tokens, of which ~900 is the
   tool block and most of the rest is procedure I appended one lesson at a time (two
   stores, recall discipline, the board, tool etiquette). Her VOICE — the part that makes
   her someone — was a minority shareholder in her own system prompt. A model reads that
   as "you are a function-calling API", and answers like one.

So this gate measures the two things a feature must never cost: HER TOOLS STILL WORK, and
SHE STILL SOUNDS LIKE HERSELF. It uses the operator's real prompts, because those are the
ones that actually failed.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# THE PATH A HUMAN ACTUALLY TALKS DOWN. The console posts to /v1/chat (the native SSE
# route, _native_chat_sse) — NOT /v1/chat/completions. They are different lanes with
# different behaviour: the console path runs the SPINE RECALL, and the recall note is
# exactly what broke her voice. The first cut of this gate drove /v1/chat/completions and
# PASSED while the operator's console was answering him in single words.
#
# That is the console-fork lesson, one day later, in a different costume: a gate pointed at
# a path nobody uses agrees with you. Drive what the human drives.
GW = "http://127.0.0.1:8800/v1/chat"
PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" :: {detail}" if detail else ""))


# the console keeps ONE session and appends to it; so does this.
HISTORY: list = []


def say(text, session, max_tokens=200):
    """Speak the way console/index.html speaks: /v1/chat, SSE deltas, session_id."""
    HISTORY.append({"role": "user", "content": text})
    body = json.dumps({"messages": HISTORY, "session_id": session,
                       "max_tokens": max_tokens, "temperature": 0.7,
                       "top_p": 0.95, "top_k": 40, "repetition_penalty": 1.3,
                       "eot_bias": 4.0}).encode()
    req = urllib.request.Request(GW, data=body, headers={"Content-Type": "application/json"})
    out = []
    with urllib.request.urlopen(req, timeout=900) as r:
        for raw in r:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            try:
                ev = json.loads(payload)
            except Exception:
                continue
            if "delta" in ev:
                out.append(ev["delta"])
    reply = "".join(out).strip()
    HISTORY.append({"role": "assistant", "content": reply})
    return reply


def main() -> int:
    print("G-VOICE - she sounds like herself, and her tools still work.\n")
    sess = f"gv{int(time.time()) % 100000}"

    # ── 1. THE TOOL TURN THAT DIED ──────────────────────────────────────────────
    r = say("can you see the notes?", sess)
    check("a tool turn does not exhaust the loop",
          "tool loop exhausted" not in r.lower(), repr(r[:90]))
    check("...and she actually answers from the board",
          any(w in r.lower() for w in ("note", "board", "3090", "freezer", "nuc", "q4b")),
          repr(r[:90]))

    # ── 2. SHE STILL SOUNDS LIKE A PERSON ───────────────────────────────────────
    # A conversational turn needs NO tool and deserves more than a word. The floor is low
    # on purpose — this is not a demand that she be verbose, it is a demand that she not
    # have been reduced to a function-call API that occasionally says "Good."
    for q in ("how are you feeling?",
              "your memory is being improved all the time too",
              "why only one word answers then?"):
        r = say(q, sess)
        words = len(r.split())
        check(f"conversational turn is a REPLY, not a token: {q!r}",
              words >= 6, f"{words} words :: {r[:70]!r}")

    # ── 3. AND THE MEMORY LANE STILL WORKS (no regression from trimming) ────────
    r = say("what is my name?", sess, 40)
    check("she still looks his name up", "knack" in r.lower(), repr(r[:60]))

    total = len(PASS) + len(FAIL)
    print(f"\nG-VOICE: {'PASS' if not FAIL else 'FAIL'} ({len(PASS)}/{total})")
    return 0 if not FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())
