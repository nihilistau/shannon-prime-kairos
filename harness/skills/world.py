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
        candidates.append((lc.salience(r), r))
    if not candidates:
        return ""
    candidates.sort(key=lambda x: -x[0])
    lines, words, seen = [], 0, set()
    for _sal, r in candidates:
        line = lc.render(r)
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
    return _HEADER + "\n" + "\n".join(lines)


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
