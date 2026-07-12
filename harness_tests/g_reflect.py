"""G-REFLECT — she thinks about him when the room is quiet. She rarely mentions it.

THINKING IS NOT SPEAKING, and this gate exists to keep them apart.

She reflects silently on an idle clock: reads what she knows about him, writes down what she
has come to believe. That happens whether or not he ever hears about it — it is how the model
of him gets built, and MOST of what she concludes should simply become part of what she knows,
unremarked. A person who told you every single thing they had ever noticed about you would be
unbearable to live with.

Only a genuinely SURPRISING conclusion earns an interruption. The bar is not "did she think of
something" — she thinks on a clock; she will always have thought of something. The bar is
whether the model itself did not see it coming, measured in bits, which is the one property of
a conclusion that cannot be faked.

    An unprompted "I've been thinking about you" that lands on something obvious is worse than
    silence: it teaches him to ignore the channel, and then the good one never gets heard.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_TMP = tempfile.mkdtemp()
os.environ["SP_RECALL_REGISTRY"] = os.path.join(_TMP, "registry.jsonl")

from harness.kairos import impulse as I        # noqa: E402
from harness.kairos import scheduler as S      # noqa: E402
from harness.model.person import PersonModel   # noqa: E402
from harness.tuning import registry as tune    # noqa: E402

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" :: {detail}" if detail else ""))


def main() -> int:
    print("G-REFLECT - she thinks when it is quiet, and rarely mentions it.\n")

    tune.STORE = os.path.join(_TMP, "tuning.json")
    tune.set_many({"kairos.enabled": True, "kairos.cooldown_s": 0.0,
                   "reflect.enabled": True, "reflect.idle_s": 600.0,
                   "reflect.cooldown_s": 1800.0, "reflect.speak_bits": 3.0})
    cfg = S.live_config()

    # ── 1. A MUSING IS NOT A PROMISE ────────────────────────────────────────────
    # A due reminder outranks the chain limit and the never-interrupt-a-question rule,
    # because it is a promise he asked her to keep. A musing does NOT. It is just something
    # she noticed, and a thought that interrupts him is worse than a thought he never hears.
    insight = {"text": "Knack builds things to be companions, not tools", "bits": 4.2}

    st = I.TurnState()
    I.note_user(st, 1000.0)
    imp = I.decide(cfg=cfg, state=st, now=1000.1, reply_text="Sure.",
                   eot_margin=None, insight=insight)
    check("a surprising conclusion IS a reason to speak",
          imp.speaks and imp.action == I.MUSE, imp.reason)

    # NB: note_user() RESETS the chain — his turn ending her chain is the entire point of a
    # conversation. Setting chain=1 and THEN calling note_user wipes it, and the first cut
    # of this check did exactly that and "failed" the code for being right. Speak first,
    # then chain.
    st_chained = I.TurnState()
    I.note_user(st_chained, 1000.0)
    I.note_spoke(st_chained, 1000.05)          # she has now spoken unprompted once
    imp = I.decide(cfg=cfg, state=st_chained, now=1000.1, reply_text="Sure.",
                   eot_margin=None, insight=insight)
    check("...but the CHAIN LIMIT still silences it (a reminder would have overridden this)",
          imp.action == I.SILENT, imp.reason)

    imp = I.decide(cfg=cfg, state=st, now=1000.1,
                   reply_text="So what did you decide about the NUC?",   # she asked HIM
                   eot_margin=None, insight=insight)
    check("...and so does 'she asked him a question' — she does not talk over him",
          imp.action == I.SILENT, imp.reason)

    # ── 2. SHE MOSTLY KEEPS IT TO HERSELF ───────────────────────────────────────
    imp = I.decide(cfg=cfg, state=st, now=1000.1, reply_text="Sure.",
                   eot_margin=None, insight=None)
    check("having concluded NOTHING new, she says nothing",
          not imp.speaks, imp.reason)

    # ── 3. THE NUDGE: A THOUGHT, NOT A LOOKUP, AND NOT PUT IN HIS MOUTH ─────────
    n = I.muse_nudge(insight)
    check("the nudge hands her the CONCLUSION to say in her own voice",
          insight["text"] in n and "your own voice" in n)
    check("...and forbids telling him he said it (he never did)",
          "he never actually said it" in n or "do not tell him that he did" in n)
    check("...and still lets her drop it if it sounds hollow out loud",
          "say nothing at all" in n)

    # ── 4. THE NEIGHBOUR WHO DID NOT WAVE ──────────────────────────────────────
    now = time.time()

    def iso(d):
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - d * 86400))

    pm = PersonModel()
    pm.absorb({"text": "I am training for the marathon", "mem_class": "preference",
               "mentions": 8, "first_seen": iso(44), "last_seen": iso(30)})
    sil = pm.silences(now=now)
    check("(setup) a thing he has gone quiet on is detected", bool(sil))

    nudge = I.muse_nudge({"text": sil[0]["claim"], "bits": sil[0]["bits"], "silence": sil[0]})
    check("a SILENCE becomes a gentle question, not an announcement",
          "ASK him" in nudge and "has not mentioned it" in nudge)
    check("...and she is told not to reveal that she was analysing him",
          "Do not announce that you were analysing him" in nudge)
    check("...and to shut up if it feels like prying rather than caring",
          "prying rather than caring" in nudge)

    # ── 5. NO NEW EVIDENCE, NO NEW THINKING ────────────────────────────────────
    # Re-reading the same facts just re-derives the same conclusion and calls it a
    # discovery. Harmless in the STORE (reinforcement makes a re-derived belief stronger,
    # not duplicated) — deadly in the CHANNEL, where the same thought arriving twice is how
    # a companion becomes a bore.
    S._STATE.clear(); S._LAST.clear()
    S._LAST_REFLECT_AT = 0.0
    S._LAST_EVIDENCE = -1

    t0 = time.monotonic()
    st2 = S._STATE["s"]
    I.note_user(st2, t0 - 5.0)                 # he spoke 5 seconds ago: the room is NOT quiet
    check("she does not reflect while he is still talking (idle floor)",
          S.reflect_tick(t0) is None, "reflection is a whole model turn — never race him")

    I.note_user(st2, t0 - 1200.0)              # 20 minutes of quiet
    S._LAST_EVIDENCE = S._evidence_count()     # ...but nothing new has been said
    check("she does not re-think the same evidence and call it a discovery",
          S.reflect_tick(t0) is None, "no new evidence, no new thinking")

    total = len(PASS) + len(FAIL)
    print(f"\nG-REFLECT: {'PASS' if not FAIL else 'FAIL'} ({len(PASS)}/{total})")
    return 0 if not FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())
