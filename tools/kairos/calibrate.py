"""KAIROS CALIBRATION — set the continuation threshold from DATA, not from a guess.

The whole design rests on one number: how far below the stop/continue logit margin does
a turn have to sit before we call it "she stopped mid-thought"?

I will not pick that constant by feel. Twice today a guessed number cost a day (the
`no_repeat_ngram=3` ban; a "-44% preamble" claim measured on an unpinned benchmark). So:

  1. run a spread of ORDINARY turns — the kind where she genuinely finishes her thought
  2. run turns DELIBERATELY CUT OFF at max_tokens, mid-sentence
  3. look at the two distributions

If they separate, the threshold goes between them and she will be silent on ordinary
turns BY CONSTRUCTION — not because I told her to be. If they do NOT separate, the
eot_margin is not the signal and I say so instead of shipping it.

    python tools/kairos/calibrate.py          # needs a warm stack with SP_KAIROS=1
"""
from __future__ import annotations

import json
import statistics
import urllib.request

DAEMON = "http://127.0.0.1:3000/v1/chat"

# Turns where she should COMFORTABLY finish.
#
# THE BUDGET MUST BE GENEROUS. The first cut of this file gave these 20 tokens, and she
# ran straight past it — so three "finished" turns were actually GUILLOTINED, landed in
# the finished group at margin -12/-7/-3, and made the distributions look like they
# overlapped. I then nearly concluded the signal was no good. A control that is itself
# truncated is not a control. Give her 250 tokens; a turn only counts as FINISHED if she
# stops on her own, with room to spare.
FINISHED = [
    ("What is 2+2? Just the number.", 250),
    ("What colour is the sky on a clear day? One word.", 250),
    ("Name one planet. One word.", 250),
    ("What is the capital of France? One word.", 250),
    ("Say hello in exactly three words.", 250),
    ("Give me one word for the opposite of hot.", 250),
]

# Turns CUT OFF mid-thought: a long open-ended ask, throttled to a few tokens so the
# generation is guillotined in the middle of a sentence.
CUT_OFF = [
    ("Describe a thunderstorm over the ocean in vivid detail, at length.", 12),
    ("Tell me the full history of the Roman empire, in detail.", 12),
    ("Explain how a jet engine works, step by step, thoroughly.", 12),
    ("Tell me a long story about a lighthouse keeper.", 12),
    ("List every planet with a detailed description of each.", 12),
    ("Explain quantum entanglement properly, from first principles.", 12),
]


def _hit_ceiling(text: str, max_tokens: int) -> bool:
    """Did she run out of budget rather than stop? ~4 chars/token. A FINISHED control that
    hit its ceiling is not a control — it is a cut-off turn wearing the wrong label."""
    return len(text) > 3.4 * max_tokens


def turn(prompt: str, max_tokens: int):
    body = json.dumps({
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens, "temperature": 0, "auto_recall": False,
    }).encode()
    req = urllib.request.Request(DAEMON, data=body,
                                 headers={"Content-Type": "application/json"})
    raw = urllib.request.urlopen(req, timeout=300).read().decode("utf-8", "replace")

    margin, text = None, []
    ev = None
    for line in raw.splitlines():
        if line.startswith("event:"):
            ev = line[6:].strip()
            continue
        if not line.startswith("data:"):
            continue
        p = line[5:].strip()
        if p == "[DONE]":
            break
        try:
            j = json.loads(p)
        except Exception:
            continue
        if ev == "kairos":
            margin = j.get("eot_margin")
            ev = None
            continue
        ev = None
        if j.get("delta"):
            text.append(j["delta"])
    return margin, "".join(text)


def main() -> int:
    print("KAIROS CALIBRATION — does eot_margin actually separate 'finished' from 'cut off'?\n")
    groups = {}
    for label, cases in (("FINISHED (she is done)", FINISHED), ("CUT OFF (guillotined)", CUT_OFF)):
        print(f"  {label}")
        vals = []
        for prompt, mt in cases:
            m, txt = turn(prompt, mt)
            if m is None:
                print("    !! no kairos event — is SP_KAIROS=1? (profile: kairos)")
                return 1
            # discard a "FINISHED" control that actually hit its token ceiling
            if "FINISHED" in label and _hit_ceiling(txt, mt):
                print(f"    margin {m:8.3f}   [DISCARDED — hit the ceiling, not a finished turn]")
                continue
            vals.append(m)
            print(f"    margin {m:8.3f}   {txt.strip()[:44]!r}")
        if not vals:
            print("    !! every control was truncated — raise max_tokens")
            return 1
        groups[label] = vals
        print()

    fin = groups["FINISHED (she is done)"]
    cut = groups["CUT OFF (guillotined)"]
    print(f"  FINISHED : median {statistics.median(fin):7.3f}   min {min(fin):7.3f}   max {max(fin):7.3f}")
    print(f"  CUT OFF  : median {statistics.median(cut):7.3f}   min {min(cut):7.3f}   max {max(cut):7.3f}")

    # THE RIGHT QUESTION is not "are the ranges disjoint?" — it is "is there a threshold
    # at which she NEVER interrupts a finished turn?" False positives (talking when she
    # was done) are the failure that matters; a missed continuation just means silence,
    # which is the safe default. So: search for the threshold with ZERO false positives,
    # and among those take the one that catches the most genuine cut-offs.
    best = None
    for t in [x / 4.0 for x in range(-80, 21)]:          # -20.0 .. +5.0, quarter steps
        fp = sum(1 for m in fin if m < t)                 # finished turns she'd interrupt
        tp = sum(1 for m in cut if m < t)                 # cut-off turns she'd resume
        if fp == 0 and (best is None or tp > best[2]):
            best = (t, fp, tp)

    print(f"\n  medians: FINISHED {statistics.median(fin):+.2f}   CUT OFF {statistics.median(cut):+.2f}"
          f"   (gap {statistics.median(fin) - statistics.median(cut):.1f})")
    if best and best[2] > 0:
        t, fp, tp = best
        print(f"\n  ** eot_margin IS the signal. **")
        print(f"  ** continue_margin = {t:.2f}")
        print(f"     -> {fp}/{len(fin)} finished turns interrupted   (she NEVER talks over herself)")
        print(f"     -> {tp}/{len(cut)} genuine cut-offs resumed")
        print(f"     Ordinary turns are silent BY CONSTRUCTION — not because a rule said so,")
        print(f"     but because the forward itself says she had nothing left to add. **")
    else:
        print("\n  ** NO SAFE THRESHOLD. Any setting that resumes a cut-off turn would also")
        print("     interrupt a finished one. eot_margin alone is NOT sufficient — the head")
        print("     must read the hidden state instead. Do not ship. **")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
