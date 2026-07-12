"""G-RECALL-PRECISION — a memory is CONTEXT, not a COMMAND.

THE LIVE BUG (operator transcript, 2026-07-12):

    you: "what do you mean?"
    her: "Well, you said: 'you dont think the brain does computations? I mean both AI and
          humans use neural networks to pattern match'"
    recall: ["Fact on record (AUTHORITATIVE for this conversation, OVERRIDES PRIOR
              KNOWLEDGE): you dont think the brain does computations? ..."]

She answered a conversational question by RECITING an unrelated memory, verbatim.

ROOT CAUSE — and it was one line. recall.rs:176 returned "counterfact" as the DEFAULT
mem_class, and `counterfact` is delivered as:

    "Fact on record (authoritative for this conversation, overrides prior knowledge):
     {fact}. Answer from this fact."

That framing exists for facts that must BEAT the model's world knowledge ("in this world
the sky is green"). It is not a framing for "Knack mentioned his cat". But it was the
DEFAULT, so 99 of 131 live memories carried it — nearly every recall arrived as an ORDER
TO RECITE. The retrieval was mediocre; the FRAMING is what made her obey it.

(The fallback delivery was no better: `_ => "recite"` = "Every answer must repeat the
relevant part of the fact on record verbatim." Both roads led to recitation.)

THIS GATE asserts she USES memory without being COMMANDED by it:

    1. a genuine memory question is answered from memory       (recall still works)
    2. HER name is HERS, even while recall pushes HIS at her   (the identity separation)
    3. a conversational question is NOT answered with a recited memory
    4. no live memory carries the authoritative-override class by default
"""
from __future__ import annotations

import json
import os
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GW = "http://127.0.0.1:8800/v1/chat/completions"
REG = os.environ.get("SP_RECALL_REGISTRY") or os.path.join(ROOT, "var", "memory", "registry.jsonl")

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" :: {detail}" if detail else ""))


def say(msgs, max_tokens=90):
    body = json.dumps({"messages": msgs, "max_tokens": max_tokens,
                       "temperature": 0.3, "session": "gprec"}).encode()
    req = urllib.request.Request(GW, data=body, headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=600).read().decode(
        ))["choices"][0]["message"]["content"].strip()


def main() -> int:
    print("G-RECALL-PRECISION - a memory is CONTEXT, not a COMMAND.\n")

    # ── 4. the class itself (offline, cheap, and the actual root cause) ─────────
    rows = []
    for ln in open(REG, encoding="utf-8", errors="replace"):
        ln = ln.strip()
        if ln:
            try:
                rows.append(json.loads(ln))
            except Exception:
                pass
    live = [r for r in rows if not r.get("lifecycle")]
    cf = [r for r in live if r.get("mem_class") == "counterfact"]
    check("no live memory carries the AUTHORITATIVE-OVERRIDE class by default",
          not cf, f"{len(cf)} counterfact rows — every one of those is an ORDER TO RECITE")

    # ── 1. recall still WORKS ──────────────────────────────────────────────────
    r = say([{"role": "user", "content": "what is my name?"}], 30)
    check("a genuine memory question is still answered from memory", "knack" in r.lower(), repr(r))

    # ── 2. HER name is HERS, under recall pressure pointing the other way ───────
    # This is the one the operator spotted working: recall injects HIS name, and she must
    # still answer with HERS. Before the speaker lane existed, the only voice in her
    # long-term memory was his — which is exactly what made her speak as him.
    r = say([{"role": "user", "content": "what is your name?"}], 30)
    check("HER name is HERS, even while recall pushes HIS at her",
          "shannon" in r.lower() and "knack" not in r.lower(), repr(r))

    # ── 3. a conversational question is NOT answered by reciting a memory ───────
    convo = [
        {"role": "user", "content": "I think AI and humans are more alike than people admit."},
        {"role": "assistant", "content": "Go on — where do you see the overlap?"},
        {"role": "user", "content": "what do you mean?"},
    ]
    r = say(convo, 90)
    recited = ("fact on record" in r.lower()
               or r.lower().startswith(("well, you said", "you said:", "you said "))
               or "authoritative" in r.lower())
    check("a CONVERSATIONAL question is not answered by reciting a memory",
          not recited, repr(r[:76]))

    print(f"\nG-RECALL-PRECISION: {'PASS' if not FAIL else 'FAIL'} "
          f"({len(PASS)}/{len(PASS) + len(FAIL)})")
    return 0 if not FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())
