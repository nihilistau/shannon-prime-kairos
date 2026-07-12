"""A MODEL OF THE PERSON — the thing facts are evidence FOR.

THE OPERATOR, ON BEING TOLD "I like fun" HAD BEEN FILED AS JUNK:

    "there is subtlety to what you are trying to throw away. I DO indeed like fun, and one
     could say that is an important thing to remember... A human being creates a model of
     the person they are talking to and they runs things through that model, updating
     weights with new information. So maybe something along the lines of a model of a human
     being, or a model of me."

He is right, and it is the missing layer. Right now the store is a FLAT LIST OF FACTS with a
salience score, and salience can only ever measure how often and how recently a thing was
said. It cannot measure whether the thing MATTERS, because mattering is not a property of a
sentence — it is a property of a sentence RELATIVE TO A MODEL. "I like fun" is important
precisely because it is one of the few things that says what kind of person he is; "my
access code is 4471" is a string.

── WHERE THIS SITS IN THE LITERATURE (checked, not remembered) ────────────────────
Generative Agents (Park et al.) score memory as RECENCY + IMPORTANCE + RELEVANCE, where
importance is a 1-10 score the LLM assigns at write time, plus REFLECTION: periodically the
agent asks itself the salient questions about what it has seen and writes higher-level
insights back into memory. We have recency and frequency (which is ACT-R base-level
activation, and Anderson & Schooler showed that really is how need-probability behaves in a
real environment). We have NO importance term and NO reflection. That is the gap.

"Learning What to Remember" (2026) sharpens it: the forgetting decision is made AT
CONSOLIDATION TIME, BEFORE THE FUTURE QUERY IS KNOWN — so ranking by similarity-and-recency
is structurally mis-specified. Their seven cognitively-grounded factors include VALUE
ALIGNMENT — does this cohere with what I know this person cares about — and a learned value
model retains 0.770 of gold evidence where recency alone retains 0.368. Less than half.

── THE ONE IDEA THIS FILE IS BUILT ON ────────────────────────────────────────────
A fact is important TO THE DEGREE IT CHANGES THE MODEL.

That is Bayesian surprise / information gain, and it makes importance DERIVABLE instead of
guessed at. It matters that it is derivable: the alternative on offer (ask the 12B to score
1-10) is a judgement, and this system has already been badly burned trusting her judgement —
she told the operator she had added notes she had not added. A number she invents is a
number nobody can check. A number computed from what the model did and did not already know
is a number with a receipt.

    "I like fun"                first time  -> opens a DIMENSION of him. High surprise.
    "I like fun"                fifth time  -> confirms it. Low surprise, high confidence.
    "my flight is at 9am Friday"            -> moves nothing about who he is. Episodic
                                               utility until Friday, then worthless.
    "I am a woman" (from HER)               -> does not belong to this model at all.

── WHAT THIS IS AND IS NOT ───────────────────────────────────────────────────────
This is a SCAFFOLD. It is deliberately plain Python — slots, evidence, confidence — because
the operator said he expects to invent the clever part himself and hand it over. It is built
so that the clever part can be dropped in behind `surprise()` and `render()` without moving
anything else: the routing, the evidence trail and the gate stay valid whatever scores it.

It does NOT: embed anything, call a model, or guess. It reads the fact store, which is
already owner-stamped, class-tagged and salience-scored, and it arranges those facts into a
person instead of a list.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Optional

from harness.skills import lifecycle as lc


# ── THE SLOTS ─────────────────────────────────────────────────────────────────
# Frame/slot theory (Minsky), which is also what the operator reached for unprompted when
# he said "kind of object orientated". A person is not a bag of sentences; it is a small
# number of DIMENSIONS with evidence attached to each.
#
# The order is the order of durability, and it is also roughly the order of how much each
# tells you about who someone IS. That is not a coincidence — it is the whole point.
SLOTS = (
    ("identity",     ("identity",)),                    # what he is: name, gender
    ("dispositions", ("preference",)),                  # what he LIKES: fun, music, Oolong
    ("relationships", ("relationship",)),               # who is around him: Tuffy
    ("possessions",  ("fact",)),                        # what he HAS: a 2060, a NUC
    ("happenings",   ("event", "episodic-event")),      # what happened: a flight on Friday
)
_CLASS_TO_SLOT = {c: s for s, classes in SLOTS for c in classes}


@dataclass
class Dimension:
    """One facet of him, and the evidence for it."""
    name: str
    claims: list = field(default_factory=list)     # [(text, mentions, salience)]

    @property
    def confidence(self) -> float:
        """How sure are we? Not "how many facts" — HOW OFTEN HE SAID THEM. A thing said
        five times by one person is better evidence than five things said once."""
        if not self.claims:
            return 0.0
        said = sum(m for _t, m, _s in self.claims)
        return min(1.0, said / (said + 3.0))           # 1 claim -> .25, 3 -> .50, 9 -> .75


@dataclass
class PersonModel:
    who: str = "Knack"
    dims: dict = field(default_factory=dict)

    # ── BUILD: facts are EVIDENCE, not entries ────────────────────────────────
    @classmethod
    def from_registry(cls, path: str = "", speaker: str = lc.SPEAKER_USER) -> "PersonModel":
        p = path or os.environ.get("SP_RECALL_REGISTRY", "")
        m = cls()
        if not p or not os.path.exists(p):
            return m
        with open(p, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if r.get("lifecycle"):
                    continue                            # a retired fact is not evidence
                if (r.get("speaker") or lc.SPEAKER_USER) != speaker:
                    continue                            # HER facts do not model HIM
                m.absorb(r)
        return m

    def absorb(self, row: dict) -> None:
        slot = _CLASS_TO_SLOT.get(row.get("mem_class", ""), "possessions")
        d = self.dims.setdefault(slot, Dimension(slot))
        d.claims.append((lc.strip_prefix(row.get("text", "")),
                         int(row.get("mentions", 1) or 1),
                         lc.salience(row)))

    # ── SURPRISE: how much would this fact MOVE the model? ────────────────────
    def surprise(self, fact: str, mem_class: str = "") -> float:
        """IMPORTANCE, DERIVED. In [0,1].

        Not "how important does this sound" — that is a judgement, and judgements cannot be
        checked. This is "how much does the model not already know it", which has a receipt.

        A fact that opens a dimension we have nothing in is a large update. A fact that adds
        a new claim to a thin dimension is a moderate one. A fact we have effectively heard
        before is confirmation — valuable (it raises confidence) but not NEWS.
        """
        cls = mem_class or lc.classify(fact)
        slot = _CLASS_TO_SLOT.get(cls, "possessions")
        d = self.dims.get(slot)
        if d is None or not d.claims:
            return 1.0                                  # a whole facet of him we did not have

        toks = {w for w in "".join(c.lower() if c.isalnum() else " "
                                  for c in fact).split() if len(w) >= 3}
        if not toks:
            return 0.0
        best = 0.0
        for t, _m, _s in d.claims:
            tt = {w for w in "".join(c.lower() if c.isalnum() else " "
                                    for c in t).split() if len(w) >= 3}
            if tt:
                best = max(best, len(toks & tt) / len(toks))
        novelty = 1.0 - best                            # 0 = we have heard this exact thing

        # A THIN DIMENSION LEARNS FASTER. The second thing we learn about what he likes tells
        # us far more than the twentieth. This is the same diminishing-returns shape as the
        # log in salience(), and for the same reason.
        thinness = 1.0 / (1.0 + len(d.claims))
        return round(min(1.0, 0.35 * novelty + 0.65 * (novelty * (0.3 + thinness))), 4)

    # ── RENDER: the model, as she would actually hold it ──────────────────────
    def render(self, top: int = 3) -> str:
        """A compact picture of him — the thing a human carries around and runs new
        information against, instead of re-deriving him from a list of sentences every time.

        THIS is what should be injected into her context, not the raw facts. A list of
        sentences is what a database returns; a person is what a friend remembers."""
        if not self.dims:
            return ""
        lines = [f"What you know about {self.who}:"]
        for slot, _classes in SLOTS:
            d = self.dims.get(slot)
            if not d or not d.claims:
                continue
            best = sorted(d.claims, key=lambda c: -c[2])[:top]
            items = "; ".join(t for t, _m, _s in best)
            lines.append(f"  {slot} (confidence {d.confidence:.0%}): {items}")
        return "\n".join(lines)

    def stats(self) -> dict:
        return {s: {"claims": len(d.claims), "confidence": round(d.confidence, 2)}
                for s, d in self.dims.items()}
