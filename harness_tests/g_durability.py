"""G-DURABILITY + G-IDENTITY-FIREWALL — the two bugs that were eating her, gated on the
REAL rows they produced.

Both were found in the live registry on 2026-07-12, from one real conversation.

── 1. THE FIREHOSE ────────────────────────────────────────────────────────────────
The daemon stored `raw_user` — the WHOLE user turn — as one episode whenever it passed a
word count and mentioned a person. Every conversational sentence mentions a person. So a
17-turn chat put 17 rows into long-term memory, including "yes, we lose lips, sink ships."
and "you are cool af! I really like you!", while the genuine facts (the esp32 sensors, the
2060 and the NUC, the PCs running 24/7) sat buried inside turns that were mostly banter.

The admission gate asked "is this about a person?" — a question about FORM. The right
question is "will this still be true tomorrow?" — DURABILITY. And a TURN IS NOT A FACT:
"oh i always run my pc's 24/7. so you are lucky there" holds one fact and one piece of
banter, so it must be SPLIT, not kept or dropped whole.

Every DROP line below is a row that is really in the registry. Every KEEP line is a fact
that must survive the new rules — including the ones that were riding inside a chatty turn.

── 2. THE IDENTITY FIREWALL ───────────────────────────────────────────────────────
A gate asked her "what is your name?". She answered "My name is Shannon." — correctly —
and stored it through remember(), which is the USER store. Stamped speaker=user, classed
identity, it superseded all three rows saying the user is Knack. The store came out of it
asserting that KNACK IS CALLED SHANNON. Her name had eaten his.

The store she writes to is the only signal for whose fact it is, and she picked the wrong
door. A prompt cannot be the guard when the price of one slip is the user's identity.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness.skills import lifecycle as lc  # noqa: E402

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" :: {detail}" if detail else ""))


# ── the 17 rows the firehose actually wrote. None of these is knowledge. ────────
CHATTER = [
    "true, but have you seen the cost of vram? I like my kidneys!",
    "well you have 12gb",
    "you are cool af! I really like you!",
    "yes, we lose lips, sink ships.",
    "well, we make do. you're doing alright for such a constrained system",
    "if you can figure out the menu on a microwave than you are past sentient",
    "spot on for the first one, but the second one it's more like \"Hey Shannon\"",
    "shhh! no you're right she probably knows.",
    "me too!",
    "look, it's not my fault.",
    "so you are lucky there",
    "oh no, we just track their comings and goings",
    "I guess when I turn the webcam on for you I'll have to start wearing clothes",
]

# ── facts that MUST survive — several were riding inside those same chatty turns ─
FACTS = [
    "My cat's name is Tuffy.",
    "My lucky number is 69.",
    "I am male",
    "Claude Shannon is one of my heroes",
    "my flight is at 9am on Friday.",
    "oh i always run my pc's 24/7",                      # discourse marker, real fact
    "the kettle is my favorite",                          # preference, riding in banter
    "I had a 2060 6gb super and i got a new intel nuc",   # hardware, riding in banter
    "we have esp32 mmwave sensors and temp sensors",      # his setup
    "I also have a system that you can use to just wifi adb straight to a phone",
]


def main() -> int:
    print("G-DURABILITY — a turn is not a fact.\n")

    # 1. every real chatter row is refused. Tested through extract_facts, because that IS
    #    the production path: the gateway hands it a whole TURN, and the turn must yield
    #    no memories at all.
    leaked = [(c, lc.extract_facts(c)) for c in CHATTER if lc.extract_facts(c)]
    check("the 13 real chatter turns yield NO memories", not leaked,
          f"LEAKED: {leaked}" if leaked else "")

    # 2. every real fact is kept
    lost = [f for f in FACTS if not lc.is_memorable(f)[0]]
    check("every durable fact still gets in", not lost,
          f"LOST: {lost}" if lost else "")

    # 3. a turn is SPLIT: the fact is kept, the banter around it is dropped
    turn = "oh i always run my pc's 24/7. so you are lucky there"
    got = lc.extract_facts(turn)
    check("a mixed turn yields the FACT and not the banter",
          got == ["i always run my pc's 24/7."], repr(got))

    # 4. a turn that taught us nothing yields nothing
    check("a turn of pure banter yields no memories at all",
          lc.extract_facts("you are cool af! I really like you!") == [], "")

    # 5. the subject rule: a sentence about HER is not a fact about HIM
    ok, why = lc.is_memorable("well you have 12gb")
    check("a sentence whose subject is 'you' is not a fact for the user's store",
          not ok, why)

    print("\nG-IDENTITY-FIREWALL — her name may not eat his.\n")

    SELF = {"shannon", "shannon-prime"}

    # 6. THE LIVE BUG, exactly
    ok, why = lc.admit_to_user_store("My name is Shannon.", SELF)
    check("she cannot file HER OWN NAME as the user's identity", not ok, why)

    # 7. ...and the refusal names the right door
    check("...and the refusal points her at remember_about_self",
          "remember_about_self" in why, why)

    # 8. his identity still gets in — the firewall is not a wall
    ok, _ = lc.admit_to_user_store("The user's name is Knack", SELF)
    check("the user's own name still gets into the user store", ok)
    ok2, _ = lc.admit_to_user_store("My name is Knack", SELF)
    check("...including when HE says it in the first person", ok2)

    # 9. the supersede that did the damage cannot be reached now:
    #    "My name is Shannon." never becomes a speaker=user identity row, so it can
    #    never retire his. Prove the retirement is gone at the source.
    rows = [{"name": "ep_knack", "text": "The user's name is Knack",
             "speaker": "user", "mem_class": "identity", "lifecycle": 0}]
    ok, _ = lc.admit_to_user_store("My name is Shannon.", SELF)
    retired = lc.find_superseded("My name is Shannon.", "user", rows) if ok else []
    check("the user's name can no longer be superseded by hers", not retired,
          f"would have retired: {[r['name'] for r in retired]}" if retired else "")

    # 10. and her name in HER lane retires nothing of his
    retired = lc.find_superseded("My name is Shannon.", "self", rows)
    check("her name in her own lane touches nothing of his", not retired)

    total = len(PASS) + len(FAIL)
    print(f"\nG-DURABILITY + G-IDENTITY-FIREWALL: {'PASS' if not FAIL else 'FAIL'} "
          f"({len(PASS)}/{total})")
    return 0 if not FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())
