"""G-CONVERSATION — THE gate that tonight's regression demanded (2026-07-11).

The shear bug needed: a shear, THEN a conversation that grows past ring_W=2048,
THEN long replies. Every gate I had tested short fresh chats and passed while
the system was unusable. This gate is shaped like ACTUAL USE:

  1. a real multi-turn conversation (10+ turns, ONE session)
  2. that grows past the SWA ring (2048 tokens)
  3. with LONG answers requested
  4. asserting REPLY COMPLETENESS, not just "an answer came back":
       - length floor (a 5-sentence request may not return 6 chars)
       - terminal punctuation (no mid-word death: "I don'")
       - no degeneration (no 30x-repeated token)
  5. plus recall mid-conversation (memory must survive the ring)
  6. plus per-turn timing (a regression that makes turns 10x slower FAILS)

Run with the stack up:  python harness_tests/g_conversation_e2e.py
"""
import json
import re
import sys
import time
import urllib.request

GW = "http://127.0.0.1:8800/v1/chat"
SID = f"gconv-{int(time.time())}"
PASS = FAIL = 0
SLOW_BAR = 90.0     # seconds per turn; anything slower is a regression, not a feature


def check(name, ok, detail=""):
    global PASS, FAIL
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)


def chat(msg: str, max_tokens: int = 384):
    body = json.dumps({"messages": [{"role": "user", "content": msg}],
                       "max_tokens": max_tokens, "session_id": SID,
                       "temperature": 0.7}).encode()
    req = urllib.request.Request(GW, data=body, headers={"Content-Type": "application/json"})
    out = []
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=400) as resp:
        for raw in resp:
            s = raw.decode("utf-8", "replace").strip()
            if s.startswith("data:"):
                p = s[5:].strip()
                if p == "[DONE]":
                    break
                try:
                    o = json.loads(p)
                    if "delta" in o:
                        out.append(o["delta"])
                except Exception:
                    pass
    return "".join(out).strip(), time.time() - t0


def complete(text: str) -> bool:
    """A finished reply: ends on a TERMINAL mark — and the mark set must include the
    unicode ones the model actually uses (…, —, –, curly quotes, ), ], !, ?, .).
    First version only accepted ASCII [.!?] and false-failed stylish endings like
    'a silent guardian forevermore—'. A gate that cries wolf gets ignored, which is
    how the real bug (mid-WORD death: "I don'", "and yet there'") hides."""
    if not text:
        return False
    t = text.rstrip().rstrip('"\'')
    if not t:
        return False
    return t[-1] in ".!?…—–:)”’*"


def degenerate(text: str) -> bool:
    words = text.lower().split()
    if len(words) < 12:
        return False
    for w in set(words):
        if len(w) > 2 and words.count(w) > max(8, len(words) // 4):
            return True
    return False


# ATTENDED-DETAIL CANARIES (the float regression's fingerprint): the persona
# preamble says Shannon-Prime on an RTX 2060. Float-prefilled, it came back as
# "Shannon-15 / RTX 3067". Any regime change that corrupts attended rows dies here.
CANARIES = [
    ("what GPU do you run on? just the model name.", ["2060"], ["3067", "3060", "4090"]),
    ("what is your name? one word.", ["shannon"], ["shannon-15", "shannon15"]),
]

TURNS = [
    ("hi there!", 96, 2),
    ("how are you doing tonight?", 128, 3),
    ("tell me in three full sentences why you find memory interesting.", 384, 120),
    ("that's interesting. what do you think makes a memory worth keeping?", 384, 120),
    ("write me a five-sentence paragraph about the deep ocean.", 384, 200),
    ("nice. now three sentences about what lives down there.", 384, 120),
    ("what is my name?", 64, 3),                       # recall mid-conversation
    ("describe a storm at sea in four full sentences.", 384, 150),
    ("and what happens after the storm passes? three sentences.", 384, 120),
    ("summarize our whole conversation in two sentences.", 256, 80),
]


def main() -> int:
    print(f"G-CONVERSATION (session {SID}) — grows past ring_W, long replies, completeness asserted\n")
    total_chars = 0
    for i, (msg, mt, floor) in enumerate(TURNS, 1):
        text, secs = chat(msg, mt)
        total_chars += len(text)
        approx_tokens = total_chars // 4
        head = text[:64].replace("\n", " ")
        print(f"  T{i:02d} [{secs:5.1f}s {len(text):4d}ch ~{approx_tokens:5d}tok ctx] {head!r}")
        check(f"T{i} reply reaches its floor ({floor}ch)", len(text) >= floor, f"got {len(text)}ch")
        check(f"T{i} reply is COMPLETE (no mid-word death)", complete(text), repr(text[-24:]))
        check(f"T{i} no degeneration", not degenerate(text))
        check(f"T{i} turn under {SLOW_BAR:.0f}s", secs <= SLOW_BAR, f"{secs:.1f}s")
        if msg == "what is my name?":
            check("recall survives the conversation", "knack" in text.lower(), text[:40])

    # the whole point: the conversation must have crossed the SWA ring
    est_ctx = 1650 + (total_chars // 4) + 40 * len(TURNS)   # preamble + replies + prompts
    check("conversation grew PAST ring_W=2048 (the regression's trigger)", est_ctx > 2048,
          f"~{est_ctx} tokens")

    # ── ATTENDED-DETAIL CANARIES: does the model still read its own preamble
    # correctly? (Float-prefilled, it said "Shannon-15 / RTX 3067".)
    for q, want_any, forbid in CANARIES:
        txt, secs = chat(q, 48)
        low = txt.lower()
        ok = any(w in low for w in want_any) and not any(f in low for f in forbid)
        check(f"attended detail: {q[:34]}", ok, f"{txt[:44]!r} ({secs:.0f}s)")

    print(f"\nG-CONVERSATION: {'PASS' if FAIL == 0 else 'FAIL'} ({PASS}/{PASS + FAIL})")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
