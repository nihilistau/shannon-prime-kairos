"""NOTES — the shared board. Ideas, reminders, things that matter, written by either of them.

A NOTE IS NOT A FACT, AND THIS IS WHY IT HAS ITS OWN LANE.

The fact registry answers "what is true about Knack?" and its admission gate is deliberately
brutal about it: a durable fact must assert a standing state about a person, or it is
refused. That gate is correct, and it would refuse almost every note ever written —
"buy a 3090 if they ever come back in stock" asserts nothing standing about anybody. Put
notes in the fact store and one of two things happens: the durability gate refuses them, or
you loosen the gate and the firehose comes back. Both are bad, and the second is worse.

So: same MEM-OKF v2 SPINE (speaker, ts, lifecycle-as-tombstone, supersede-by-update,
provenance), different LANE. Notes are recallable, so she can answer "what did I ask you to
remind me about?" — but cleanup, compaction and the durability rules never touch them.
Nothing here deletes: remove() tombstones, exactly like the fact store.

    speaker   who wrote it — 'user' (Knack) or 'self' (Shannon). Stamped from the CALLER,
              never inferred from the words: the same sentence means different things
              depending on whose it is, and inferring it at read time is precisely what
              made her start speaking as him.
    due_at    a note with a due date is a REMINDER. Overdue ones give kairos something
              real to say when the room has been quiet — see harness/kairos.
    raised    she has already brought this one up. She reminds; she does not nag.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any, Optional

# ── the lane ──────────────────────────────────────────────────────────────────
CATEGORIES = ("idea", "reminder", "task", "important", "note")

# A colour per category, so the board reads at a glance. The UI may override per-note.
CATEGORY_COLOUR = {
    "idea":      "#7dd3fc",   # sky
    "reminder":  "#fbbf24",   # amber
    "task":      "#4ade80",   # green
    "important": "#f87171",   # red
    "note":      "#c084fc",   # violet
}

SPEAKER_USER = "user"
SPEAKER_SELF = "self"


def _store() -> str:
    """Beside the fact registry, never inside it."""
    reg = os.environ.get("SP_RECALL_REGISTRY") or ""
    if reg:
        return os.path.join(os.path.dirname(reg), "notes.jsonl")
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(root, "var", "memory", "notes.jsonl")


def _load_all() -> list[dict]:
    p = _store()
    out: list[dict] = []
    if not os.path.exists(p):
        return out
    with open(p, encoding="utf-8", errors="replace") as f:
        for ln in f:
            ln = ln.strip()
            if ln:
                try:
                    out.append(json.loads(ln))
                except Exception:
                    pass
    return out


def _write_all(rows: list[dict]) -> None:
    p = _store()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, p)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ── AUTHOR. Stamped from the caller, never guessed from the text. ─────────────
# The fact store learned this the hard way: she wrote "My name is Shannon." into the USER
# lane and supersede retired his name, because the only signal for ownership was which
# door she happened to walk through. Here the author is set by the gateway for the turn
# (user) and flipped by her own tools (self), so a note she writes is HERS on disk.
_AUTHOR = SPEAKER_USER


def set_author(who: str) -> None:
    global _AUTHOR
    _AUTHOR = SPEAKER_SELF if who == SPEAKER_SELF else SPEAKER_USER


# ── the verbs ─────────────────────────────────────────────────────────────────
def live() -> list[dict]:
    """Every note that has not been tombstoned, newest activity first."""
    rows = [r for r in _load_all() if not r.get("lifecycle")]
    rows.sort(key=lambda r: (r.get("updated_at") or r.get("ts") or ""), reverse=True)
    return rows


def get(note_id: str) -> Optional[dict]:
    return next((r for r in _load_all() if r.get("id") == note_id), None)


def add(title: str, body: str = "", category: str = "note",
        due_at: str = "", colour: str = "", speaker: str = "") -> dict:
    """Pin something to the board. Returns the note."""
    title = (title or "").strip()
    if not title:
        raise ValueError("a note needs a title")
    cat = (category or "note").strip().lower()
    if cat not in CATEGORIES:
        cat = "note"
    # a note with a due date IS a reminder, whatever it was called
    if due_at and cat == "note":
        cat = "reminder"
    row = {
        "id": uuid.uuid4().hex[:12],
        "title": title[:120],
        "body": (body or "").strip(),
        "category": cat,
        "colour": colour or CATEGORY_COLOUR.get(cat, "#8b93a3"),
        "speaker": speaker or _AUTHOR,      # WHO PUT IT THERE
        "ts": _now(),
        "updated_at": _now(),
        "due_at": (due_at or "").strip(),   # ISO8601; empty = not a reminder
        "done": False,
        "raised": False,                    # kairos has already brought it up
        "lifecycle": 0,                     # 0 live, 1 tombstoned
        "src": "note",
    }
    rows = _load_all()
    rows.append(row)
    _write_all(rows)
    return row


def update(note_id: str, **fields: Any) -> Optional[dict]:
    """Edit in place. UPDATE IS NOT A NEW NOTE — the board is a board, not a tape: if every
    edit minted a row the list would fill with the history of its own typos. (The fact
    store supersedes instead, because a CHANGED FACT is a real event with provenance. A
    corrected shopping note is not.) The previous body is kept in `prev` for one step of
    undo, which is as much history as a note deserves."""
    rows = _load_all()
    hit = None
    for r in rows:
        if r.get("id") == note_id:
            hit = r
            break
    if hit is None:
        return None
    allowed = ("title", "body", "category", "colour", "due_at", "done", "raised")
    prev = {k: hit.get(k) for k in ("title", "body") if k in fields}
    for k, v in fields.items():
        if k in allowed and v is not None:
            hit[k] = v
    if "category" in fields and not fields.get("colour"):
        hit["colour"] = CATEGORY_COLOUR.get(hit.get("category", "note"), hit.get("colour"))
    if prev:
        hit["prev"] = prev
    hit["updated_at"] = _now()
    _write_all(rows)
    return hit


def remove(note_id: str) -> Optional[dict]:
    """TOMBSTONE, never delete — the same rule as the fact store. A note you took off the
    board is not a note that never existed."""
    rows = _load_all()
    for r in rows:
        if r.get("id") == note_id:
            r["lifecycle"] = 1
            r["updated_at"] = _now()
            _write_all(rows)
            return r
    return None


def search(query: str, k: int = 6) -> list[dict]:
    """Ranked over title + body. Deliberately dumb and deliberately generous: a board is
    small, and a note you cannot find is a note you did not write."""
    q = {w for w in "".join(c.lower() if c.isalnum() else " " for c in (query or "")).split()
         if len(w) >= 3}
    if not q:
        return live()[:k]
    scored = []
    for r in live():
        hay = f"{r.get('title', '')} {r.get('body', '')} {r.get('category', '')}".lower()
        hit = sum(1 for w in q if w in hay)
        if hit:
            scored.append((hit / len(q), r))
    scored.sort(key=lambda x: -x[0])
    return [r for _, r in scored[:k]]


def due(now_iso: str = "", include_raised: bool = False) -> list[dict]:
    """Reminders that have come due and are not done.

    `raised` is what stops her nagging: kairos marks a reminder once it has been brought
    up, so it fires ONCE and then waits to be dealt with. A reminder that repeats itself
    every four minutes is not a reminder, it is an alarm nobody will keep switched on."""
    now = now_iso or _now()
    out = []
    for r in live():
        d = (r.get("due_at") or "").strip()
        if not d or r.get("done"):
            continue
        if not include_raised and r.get("raised"):
            continue
        if d <= now:
            out.append(r)
    out.sort(key=lambda r: r.get("due_at") or "")
    return out


def mark_raised(note_id: str) -> None:
    update(note_id, raised=True)


def stats() -> dict:
    rows = _load_all()
    lv = [r for r in rows if not r.get("lifecycle")]
    return {
        "total": len(rows),
        "live": len(lv),
        "removed": len(rows) - len(lv),
        "by_user": len([r for r in lv if r.get("speaker") == SPEAKER_USER]),
        "by_self": len([r for r in lv if r.get("speaker") == SPEAKER_SELF]),
        "reminders": len([r for r in lv if r.get("due_at") and not r.get("done")]),
        "overdue": len(due(include_raised=True)),
    }
