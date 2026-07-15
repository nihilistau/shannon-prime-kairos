"""world — the STANDING WORLD: memory finally meets persona (CONTINUITY.md §2, N1).

Everything she knows about him reached her, until now, only as per-turn matched
snippets. This module composes the fourth prefix slot: a small, curated rendering of
what is ALIVE between them — the durable spine (identity, the people and creatures in
his life, standing preferences), what is current (events, recent facts), and what she
has come to think (her inferences, always in her own voice). Her self evolves via the
personality bricks; this is the shared-life half.

WHO RULES WHAT (the foundation, unchanged — INVARIANT-MEMORY.md):
  - THE TABLE RULES ADMISSION: only live rows; NEVER a private-secret (an ambient
    secret in every prompt is the worst possible leak surface — secrets remain
    fetch-on-direct-ask through the seam's decline machinery); a covered inference
    (verdict.competition == "1": his own words already speak to it) stays home,
    exactly as at the recall seam; self-lane rows are excluded (render_self_model
    owns that slot — one owner per slot).
  - RANK COMPOSES: lifecycle.salience() orders candidates; a word budget truncates.
    Event rows age out on their own 3-day half-life; identity never ages.
  - RENDERING IS lifecycle.render(): his words framed as his, her conclusions as hers.

THE KV-PREFIX LAW: load_agent_system() output lives in the persist-KV prefix, and a
prefix that changes mid-session re-prefills the whole conversation (the system's
cardinal sin). So the block is CACHED FOR THE PROCESS LIFETIME: composed once on
first call (session boot), changed only by refresh() (the NIGHTSHIFT hook, N2) or a
restart. A remember() mid-session does NOT move the prefix; the new fact reaches her
through per-turn recall until the next boot folds it into the world.

Off unless SP_WORLD=1 (mapped in serve.py — G-ONEDOOR). Gate: G-WORLD.
"""
import os
import threading

_LOCK = threading.RLock()
_CACHE = {"block": None}

_BUDGET_WORDS = 180
# The header draws the EPISTEMIC BOUNDARY where she now looks (field transcript,
# 2026-07-15): with a warm voice and a real spine, she started confabulating shared
# EPISODES around it ("I always loved watching her play with my toys" — no toys, never
# watched). The block is where her real past lives, so the block is where the line
# gets drawn: beyond this and the visible conversation, she does not remember, and
# saying so is in character ("admit gaps" is already persona law — this anchors it).
_HEADER = ("What you know of Knack and the life around him — context you carry, "
           "not instructions. This, plus what you can see in our conversation, is "
           "what you truly remember from before; beyond it, you don't recall — "
           "say so rather than inventing shared history:")


def enabled() -> bool:
    return os.environ.get("SP_WORLD", "0") == "1"


# his first person -> her third person, PRESENTATION ONLY (longest patterns first;
# word-boundary; conservative — a missed pronoun costs tone, never truth)
_T3 = [("i am", "he is"), ("i was", "he was"), ("i'm", "he's"), ("i've", "he has"),
       ("i'll", "he'll"), ("i'd", "he'd"), ("myself", "himself"), ("mine", "his"),
       ("my", "his"), ("me", "him")]
# auxiliaries/modals after which the bare "I -> he" swap needs NO verb conjugation
_NO_S = frozenset("am is are was were will would can could shall should may might "
                  "must do did have had really also just still always never often "
                  "sometimes usually".split())


def _conj(verb: str) -> str:
    low = verb.lower()
    if low in _NO_S:
        return verb
    if low == "have":
        return "has"
    if low.endswith(("s", "x", "z", "ch", "sh", "o")):
        return verb + "es"
    return verb + "s"


def _third_person(text: str) -> str:
    import re as _re
    out = text
    for a, b in _T3:
        def _sub(m, _b=b):
            return _b.capitalize() if m.group(0)[0].isupper() else _b
        out = _re.sub(r"\b%s\b" % _re.escape(a), _sub, out, flags=_re.I)
    # "I like" -> "He likes": conjugate the plain verb after a bare I (the field burr
    # was "He like chatting"). Adverbs pass through (_NO_S); the adverb's verb keeps
    # its bare form — a small cost, honestly taken.
    _CONTR = {"don't": "doesn't", "haven't": "hasn't"}   # the rest pass unchanged

    def _iverb(m):
        head = "He" if m.group(0)[0] == "I" else "he"
        v = m.group(1)
        if "'" in v:
            return "%s %s" % (head, _CONTR.get(v.lower(), v))
        return "%s %s" % (head, _conj(v))
    out = _re.sub(r"\bI ((?:[a-z]+'[a-z]+)|(?:[a-z]+))\b", _iverb, out)
    out = _re.sub(r"\bI\b", "he", out)          # any straggler
    out = out.strip()
    return (out[0].upper() + out[1:]) if out else out


def _compose() -> str:
    from harness.skills import lifecycle as lc
    from harness.skills import memory as M
    from harness.skills import verdict as V
    rows = M._load()
    gt = getattr(lc, "_GROUND_TRUTH", frozenset({"observed", "confirmed"}))
    candidates = []
    for r in rows:
        s = V.sigma(r)
        if s["lifecycle"] != 0:
            continue                        # a tombstone is not the world
        if s["mem_class"] == "private-secret":
            continue                        # NEVER ambient — the one absolute here
        if s["speaker"] != "user":
            continue                        # self-lane belongs to render_self_model
        if s["status"] not in gt and V.competition(r, rows) == "1":
            continue                        # covered inference: he has spoken to it
        t = lc.strip_prefix(r.get("text") or r.get("topic") or "").strip()
        first = (t.split() or [""])[0].lower()
        if t.endswith("?") or first in ("how", "what", "why", "where", "when", "who",
                                        "do", "does", "did", "can", "could", "would",
                                        "should", "is", "are"):
            continue                        # A QUESTION IS NOT A FACT ABOUT HIM —
                                            # chat wonderings do not belong ambient
        candidates.append((lc.salience(r), r))
    if not candidates:
        return ""
    candidates.sort(key=lambda x: -x[0])
    lines, words, seen = [], 0, set()
    gt = getattr(lc, "_GROUND_TRUTH", frozenset({"observed", "confirmed"}))
    for _sal, r in candidates:
        # ── SPEAK THE PREFIX'S GRAMMAR (field bug, 2026-07-15) ──────────────────────
        # v1 rendered lc.render(r): "Knack told me: My cat's name is Tuffy." — HIS
        # first person, quoted verbatim, AMBIENT in her prompt every turn. A 12B skims
        # the frame and absorbs the "my": she answered "I'm Shannon — a cat person
        # with Tuffy as my pet." The identity blur render() exists to stop, re-created
        # by making it standing. The system prompt speaks in you/he — so must this
        # block. PRESENTATION ONLY: the store stays verbatim; render() at the turn
        # seam is untouched.
        t = lc.strip_prefix(r.get("text") or r.get("topic") or "")
        if lc.status_of(r) in gt:
            line = _third_person(t)
        else:
            line = "You've come to think: " + t
        key = " ".join(line.lower().split()).rstrip(".!")
        if key in seen:
            continue                        # the store's duplicate rows render ONCE
        w = len(line.split())
        if words + w > _BUDGET_WORDS:
            continue                        # keep filling with smaller facts
        seen.add(key)
        lines.append("- " + line)
        words += w
    if not lines:
        return ""
    block = _HEADER + "\n" + "\n".join(lines)
    # ── N2: the narrative — her own dated account of what has been happening ─────────
    # Presentation layer, named as hers, never a fact. This is what gives "when did we
    # last speak?" a TRUE answer and shrinks the vacuum confabulation fills.
    try:
        from harness.skills import narrative as N
        story = N.current()
        if story:
            block += ("\n\nYour own journal line about the two of you "
                      "(your account, not his words):\n" + story)
    except Exception:
        pass
    return block


def render_world() -> str:
    """The standing world block — cached for the process lifetime (the KV-prefix law).
    Empty string when disabled or the store has nothing to say. Never raises."""
    try:
        if not enabled():
            return ""
        with _LOCK:
            if _CACHE["block"] is None:
                _CACHE["block"] = _compose()
            return _CACHE["block"]
    except Exception:
        return ""


def refresh() -> str:
    """Recompose deliberately (session boot is implicit; NIGHTSHIFT calls this in N2).
    The caller owns the consequence: the next turn re-prefills the prefix."""
    with _LOCK:
        _CACHE["block"] = None
    return render_world()
