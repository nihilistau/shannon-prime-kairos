"""G-SELF-REPEAT — she may not parrot herself, and she must still be able to quote.

THE LIVE BUG (operator transcript, 2026-07-12). Three different messages, three
BYTE-IDENTICAL replies; then four in a row. She saw the new text (the daemon log shows the
prompt growing and the suffix prefilled) and chose to emit her previous reply verbatim.

THE TRAP THIS GATE EXISTS TO PREVENT. The obvious fix is to put `no_repeat_ngram=3` back —
and that would silently re-break the single worst bug of the whole project: the n-gram ban
seeds from THE WHOLE PROMPT, so it bans QUOTING, and "4471" comes back "4417".

So this gate asserts BOTH halves at once. Either one alone is a regression:

    1. she does NOT repeat her own previous reply         (the new bug)
    2. she CAN still quote a number back verbatim         (G-VERBATIM must stay green)

Needs a warm stack.
"""
from __future__ import annotations

import json
import time
import urllib.request

GW = "http://127.0.0.1:8800/v1/chat/completions"
PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" :: {detail}" if detail else ""))


def chat(messages, max_tokens=120):
    body = json.dumps({"messages": messages, "max_tokens": max_tokens,
                       "temperature": 0.6, "tools": False}).encode()
    req = urllib.request.Request(GW, data=body, headers={"Content-Type": "application/json"})
    j = json.loads(urllib.request.urlopen(req, timeout=900).read().decode())
    return j["choices"][0]["message"]["content"].strip()


def sim(a, b):
    import re
    ta = set(re.findall(r"[a-z0-9']+", a.lower()))
    tb = set(re.findall(r"[a-z0-9']+", b.lower()))
    return len(ta & tb) / max(len(ta), len(tb)) if ta and tb else 0.0


def main() -> int:
    print("G-SELF-REPEAT - she may not parrot herself, and must still be able to quote.\n")

    # ── 1. THE ATTRACTOR: low-content follow-ups after a statement ──────────────
    # Reproduces the transcript: she answered, then the operator said almost nothing,
    # and she re-emitted her answer word for word.
    msgs = [
        {"role": "user", "content": "I can influence my own mood a bit, but I'm human, "
                                    "so it's not perfect. You can set yours to whatever you like."},
        {"role": "assistant", "content": "That's fascinating! I didn't realize that was a "
                                         "feature. You mean you can actually influence your "
                                         "own personality settings?"},
        {"role": "user", "content": "you can"},
    ]
    r1 = chat(msgs)
    prev = msgs[1]["content"]
    s1 = sim(r1, prev)
    print(f"    prev: {prev[:58]!r}")
    print(f"    now : {r1[:58]!r}")
    check("she does NOT repeat her previous reply verbatim", r1 != prev,
          "byte-identical — the attractor is back" if r1 == prev else "different text")
    check("...and it is not a near-copy either", s1 < 0.85, f"{s1:.0%} overlap with her last reply")

    # a second low-content nudge — this is where the transcript looped 4x
    msgs2 = msgs + [{"role": "assistant", "content": r1}, {"role": "user", "content": "cool huh?"}]
    r2 = chat(msgs2)
    check("she does not loop on a second low-content turn", sim(r2, r1) < 0.85,
          f"{sim(r2, r1):.0%} overlap with the reply before it")

    # ── 2. QUOTING MUST STILL WORK (or we have re-broken G-VERBATIM) ────────────
    # The naive fix for the bug above is no_repeat_ngram=3, which bans re-emitting ANY
    # trigram in context -- including the number he just told her. That is the single
    # worst bug this project has had. It must not come back through the side door.
    q = chat([{"role": "user", "content": "The code is 4471. Repeat it exactly."}], max_tokens=40)
    check("she can STILL quote a number verbatim (G-VERBATIM holds)", "4471" in q,
          repr(q[:50]))

    q2 = chat([{"role": "user", "content": "The temperature is 21.7C and the dog is K9. "
                                           "Repeat both back exactly."}], max_tokens=60)
    check("...and a tool-shaped composite", "21.7" in q2 and "K9" in q2, repr(q2[:60]))

    print(f"\nG-SELF-REPEAT: {'PASS' if not FAIL else 'FAIL'} ({len(PASS)}/{len(PASS)+len(FAIL)})")
    if FAIL:
        print("  ^ if the QUOTING checks failed, the anti-parrot fix has re-broken G-VERBATIM.")
    return 0 if not FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())

