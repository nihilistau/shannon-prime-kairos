"""MEM-OKF v2 LIFECYCLE — the part that makes memory *living* instead of a tape.

THE AUDIT THAT FORCED THIS (2026-07-12). The registry held 487 rows. Of those:

    404  ep_live_   (B4 nightshift AUTO-CAPTURE)
      1  ep_tool_   (the remember() tool)

**The model had deliberately remembered exactly ONE thing in its life** — and 404/405
rows were framed `"The user said: ..."`. So:

  * it never CHOSE what to keep (no authorship),
  * it never SUPERSEDED a fact that changed (no revision),
  * it had no SELF lane at all — every memory was the user speaking, which is precisely
    why it slides into speaking as the user, or mis-genders itself: the only voice in
    its long-term memory is yours.

This module supplies the three verbs a memory needs to be alive:

    SPEAKER   — who does this fact belong to: the user, or Shannon herself?
    SUPERSEDE — a new fact that contradicts an old one RETIRES it (tombstone, not
                delete: `superseded_by` on the old, `supersedes` on the new).
    CLASS     — identity / preference / event / relationship / self, so recall can
                weight them and the operator can see them.

Nothing is ever destroyed. Superseded rows stay on disk with a pointer forward, so
"what did I used to think?" remains answerable — that is the provenance lane.
"""
from __future__ import annotations

import re
import time
from typing import Iterable, Optional

USER_PREFIX = "The user said: "

# ── SPEAKER ────────────────────────────────────────────────────────────────────
# A fact is about SHANNON when she is the subject ("I am...", "my voice is...") and
# the row was authored by her. It is about the USER when it came from a user turn.
# The distinction is stored, never inferred at read time — inference at read time is
# exactly how the identity confusion happened.
SPEAKER_USER = "user"
SPEAKER_SELF = "self"

_SELF_SUBJECT = re.compile(
    r"^\s*(?:i\b|i'm|i've|my\b|mine\b|shannon\b|shannon-prime\b)", re.I)


def infer_speaker(fact: str, author: str) -> str:
    """`author` is who is speaking THIS TURN ('user' or 'self'). The author wins:
    a fact the USER states in the first person ("I am male") is a fact about the USER,
    and a fact SHANNON states in the first person is a fact about SHANNON. Same words,
    different owner — which is exactly the ambiguity that broke identity."""
    return SPEAKER_SELF if author == SPEAKER_SELF else SPEAKER_USER


# ── CLASS ──────────────────────────────────────────────────────────────────────
# ORDER MATTERS. relationship is tested BEFORE identity: "My cat's name is Tuffy" is a
# fact about a RELATIONSHIP (the cat), while "My name is Knack" is IDENTITY. Both match
# "name is", so the presence of a relationship noun is what decides — identity only wins
# when the sentence is about the speaker themselves.
_CLASS_RULES = (
    ("relationship", re.compile(r"\b(wife|husband|partner|girlfriend|boyfriend|brother|sister|"
                                r"mother|father|mum|mom|dad|son|daughter|friend|cat|dog|pet)\b", re.I)),
    ("identity", re.compile(r"\b(name is|am called|i am (?:a |an )?(?:male|female|man|woman)|"
                            r"pronouns?|gender|birthday|born (?:in|on))\b", re.I)),
    ("event", re.compile(r"\b(yesterday|today|tomorrow|last (?:week|night|year)|"
                         r"flight|appointment|meeting|at \d|on (?:mon|tue|wed|thu|fri|sat|sun))\b", re.I)),
    ("preference", re.compile(r"\b(favou?rite|prefer|like|love|hate|enjoy|can't stand|lucky)\b", re.I)),
)


def classify(fact: str) -> str:
    for name, rx in _CLASS_RULES:
        if rx.search(fact):
            return name
    return "fact"


# ── SUPERSEDE ──────────────────────────────────────────────────────────────────
# Two facts CONFLICT when they assert different values for the SAME subject+attribute.
# "My cat's name is Tuffy" vs "My cat's name is Milo" -> supersede.
# "My cat's name is Tuffy" vs "My lucky number is 7" -> unrelated, both live.
#
# We key on (speaker, class, attribute-phrase). The attribute phrase is the text up to
# the copula — the part that says WHAT is being asserted about WHOM.
_COPULA = re.compile(r"\b(is|are|was|were|=|:)\b", re.I)


def attribute_key(fact: str, speaker: str) -> Optional[str]:
    """The 'slot' this fact fills. None when the fact has no slot shape (a story, an
    opinion, a one-off) — those never supersede anything; they just accumulate."""
    m = _COPULA.search(fact)
    if not m:
        return None
    subj = fact[:m.start()].strip().lower()
    subj = re.sub(r"^(the user'?s?|my|i)\s+", "", subj).strip()
    subj = re.sub(r"[^a-z0-9' ]+", "", subj)
    if not subj or len(subj) < 3:
        return None
    return f"{speaker}::{subj}"


def value_of(fact: str) -> str:
    m = _COPULA.search(fact)
    return fact[m.end():].strip().rstrip(".").lower() if m else fact.strip().lower()


def find_superseded(new_fact: str, speaker: str, rows: Iterable[dict]) -> list[dict]:
    """Rows this new fact RETIRES: same slot, different value, not already retired."""
    key = attribute_key(new_fact, speaker)
    if not key:
        return []
    newv = value_of(new_fact)
    out = []
    for r in rows:
        if r.get("superseded_by"):
            continue
        if r.get("speaker", SPEAKER_USER) != speaker:
            continue
        txt = strip_prefix(r.get("text") or r.get("topic") or "")
        if attribute_key(txt, speaker) != key:
            continue
        if value_of(txt) == newv:
            continue                      # same value = not a conflict, just a restatement
        out.append(r)
    return out


# ── ADMISSION (the store enforces its own invariant) ───────────────────────────
# The daemon's B4 gate now refuses impersonal sentences — and the model promptly stored
# one THROUGH THE TOOL instead (g_admission caught it: an `ep_tool_` row holding "The
# kind nurse painted the tall building..."). She is finally writing, but she has no
# judgement yet about what counts as a fact.
#
# The fix belongs HERE, not in the prompt. A prompt is advice; the store is law. Every
# path into long-term memory — auto-capture, store verb, remember() — must enforce the
# same invariant, or the one that doesn't becomes the leak. That is the same shape as
# the two-recall-authorities bug and the two-admission-authorities bug: an invariant
# guarded in one place is not guarded.
_PERSONAL_REF = re.compile(
    r"\b(i|i'm|i've|im|my|me|mine|myself|you|you're|your|yours|we|our|us)\b", re.I)
# A proper noun is decided by the WORD, not by its POSITION. Keying on "capitalised and
# not sentence-initial" wrongly refused "Knack's lucky number is 7741" — a real fact that
# happens to begin with the name. Instead: capitalised words minus the ones that are
# merely starting a sentence.
_CAP = re.compile(r"\b[A-Z][a-z]{2,}\b")
_CAP_STOP = {
    "The", "This", "That", "These", "Those", "There", "Here", "They", "Them", "Their",
    "She", "Her", "His", "Him", "Its", "And", "But", "For", "Not", "Now", "Then",
    "When", "While", "After", "Before", "Because", "But", "One", "Two", "Three",
    "Today", "Yesterday", "Tomorrow", "Some", "Any", "Every", "Each", "Both", "Also",
}


def _has_proper_noun(t: str) -> bool:
    return any(w not in _CAP_STOP for w in _CAP.findall(t))


def is_memorable(fact: str) -> tuple[bool, str]:
    """A memory is ABOUT SOMEONE. An impersonal declarative ("The kind nurse painted the
    tall building as the sun went down") is a SENTENCE, not a memory — grammatical, in
    range, and about nobody. 375 of 487 registry rows were exactly that."""
    t = (fact or "").strip()
    if len(t.split()) < 3:
        return False, "too short to be a standalone fact"
    if _PERSONAL_REF.search(t) or _has_proper_noun(t):
        return True, ""
    return False, ("that is a sentence, not a memory — it is not about anyone. "
                   "Store facts about Knack, or about yourself.")


# ── framing ────────────────────────────────────────────────────────────────────
def strip_prefix(text: str) -> str:
    return text[len(USER_PREFIX):] if text.startswith(USER_PREFIX) else text


def render(row: dict) -> str:
    """How a memory should READ back to the model. This is the identity fix: a self
    memory must come back in Shannon's own voice, not as something 'the user said'."""
    t = strip_prefix(row.get("text") or row.get("topic") or "")
    if row.get("speaker") == SPEAKER_SELF:
        return f"About myself: {t}"
    return f"Knack told me: {t}"


def stamp(row: dict, fact: str, speaker: str, src: str,
          supersedes: Optional[list[str]] = None) -> dict:
    """Attach the full v2 lifecycle lane to a registry row."""
    # NO "The user said: " prefix. That framing is the disease, not the record: it put
    # the ownership INSIDE the sentence, where a reader had to re-derive it every time —
    # and 404/405 rows carried it, so every memory read back as the user talking. The
    # owner now lives in `speaker`, and `render()` frames it at READ time. Bare fact on
    # disk also restores the exact-duplicate guard, which the prefix had silently broken.
    row["text"] = fact
    row["speaker"] = speaker
    row["mem_class"] = classify(fact)
    row["src"] = src or ("self" if speaker == SPEAKER_SELF else "user turn")
    row["ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    row["verified"] = False
    if supersedes:
        row["supersedes"] = supersedes
    return row
