"""OPERATOR MAINTENANCE — the buttons, and the real work behind them.

The operator asked for: change moods and save; click to add/remove memory entries;
perform compaction, cleanup, nightshift.

Every one of these does REAL work and returns a RECEIPT (what changed, and how much). A
maintenance button that reports "done!" and cannot tell you what it did is how a system
rots quietly — and this store has already rotted once (487 rows, 375 of them ASR test
corpus, recalled mid-answer as fact).

Nothing here deletes. Cleanup QUARANTINES (restorable). Compaction TOMBSTONES (superseded,
kept for provenance). The only destructive verb is forget(), and that is the operator's
explicit choice, one row at a time.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any

from harness.skills import lifecycle as lc


def _reg() -> str:
    return os.environ.get("SP_RECALL_REGISTRY", "")


def _rows() -> list[dict]:
    p = _reg()
    out = []
    if not p or not os.path.exists(p):
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


def _write(rows: list[dict]) -> None:
    p = _reg()
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, p)


def _backup() -> str:
    p = _reg()
    b = f"{p}.bak-{time.strftime('%Y%m%d-%H%M%S')}"
    if os.path.exists(p):
        import shutil
        shutil.copy2(p, b)
    return os.path.basename(b)


# ──── stats ───────────────────────────────────────────────────────────────────
def stats() -> dict[str, Any]:
    rows = _rows()
    live = [r for r in rows if not r.get("lifecycle")]
    return {
        "total": len(rows),
        "live": len(live),
        "superseded": sum(1 for r in rows if r.get("lifecycle")),
        "self": sum(1 for r in live if r.get("speaker") == "self"),
        "user": sum(1 for r in live if r.get("speaker") != "self"),
        "legacy_no_speaker": sum(1 for r in live if not r.get("speaker")),
        "classes": {c: sum(1 for r in live if r.get("mem_class") == c)
                    for c in sorted({r.get("mem_class", "?") for r in live})},
    }


# ──── COMPACTION — collapse duplicates, supersede conflicts ────────────────────
def compact() -> dict[str, Any]:
    """Fold the store: drop exact duplicates, retire near-duplicate paraphrases, and
    supersede facts that fill the same slot with a different value.

    TOMBSTONES, never deletes: a retired row keeps its text and gains lifecycle=1 +
    superseded_by, so 'what did I used to think?' stays answerable. lifecycle=1 is what the
    DAEMON reads to exclude a row from recall (recall.rs:587, routes.rs:2342) — this is the
    field that matters."""
    rows = _rows()
    bak = _backup()
    live = [r for r in rows if not r.get("lifecycle")]

    seen: dict[str, dict] = {}
    dupes = paraphrases = superseded = 0

    for r in live:
        txt = lc.strip_prefix(r.get("text") or r.get("topic") or "").strip()
        if not txt:
            continue
        key = txt.lower()
        if key in seen:                                  # exact duplicate
            r["lifecycle"] = 1
            r["superseded_by"] = seen[key].get("name", "")
            r["superseded_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            dupes += 1
            continue
        seen[key] = r

    # near-duplicate paraphrase (>=0.9 token overlap both ways) and slot conflicts
    survivors = [r for r in live if not r.get("lifecycle")]
    for i, r in enumerate(survivors):
        if r.get("lifecycle"):
            continue
        rt = lc.strip_prefix(r.get("text") or "")
        rsp = r.get("speaker", "user")
        for older in survivors[:i]:
            if older.get("lifecycle"):
                continue
            ot = lc.strip_prefix(older.get("text") or "")
            if older.get("speaker", "user") != rsp:
                continue                                  # never merge across speakers
            a, b = lc._PERSONAL_REF and set(rt.lower().split()), set(ot.lower().split())
            if a and b:
                inter = len(a & b)
                if inter / len(a) >= 0.9 and inter / len(b) >= 0.9:
                    older["lifecycle"] = 1               # the NEWER one wins
                    older["superseded_by"] = r.get("name", "")
                    paraphrases += 1
                    continue
            k1 = lc.attribute_key(rt, rsp)
            if k1 and k1 == lc.attribute_key(ot, rsp) and lc.value_of(rt) != lc.value_of(ot):
                older["lifecycle"] = 1
                older["superseded_by"] = r.get("name", "")
                older["superseded_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                superseded += 1

    _write(rows)
    s = stats()
    return {"ok": True, "backup": bak, "duplicates_retired": dupes,
            "paraphrases_retired": paraphrases, "conflicts_superseded": superseded,
            "live_now": s["live"], "superseded_total": s["superseded"]}


# ──── CLEANUP — quarantine what is not a memory ───────────────────────────────
def cleanup() -> dict[str, Any]:
    """Quarantine rows that are not memories: ASR/voice test corpus, impersonal
    declaratives, instructions, chatter. REVERSIBLE — everything lands in quarantine.jsonl
    with a reason, and the registry is backed up first. Nothing is destroyed."""
    rows = _rows()
    bak = _backup()
    keep, junk = [], []
    for r in rows:
        if r.get("lifecycle"):
            keep.append(r)                                # already retired; leave it
            continue
        txt = lc.strip_prefix(r.get("text") or r.get("topic") or "")
        ok, why = lc.is_memorable(txt)
        (keep if ok else junk).append(r if ok else {**r, "quarantine_reason": why})

    if junk:
        q = os.path.join(os.path.dirname(_reg()), "quarantine.jsonl")
        with open(q, "a", encoding="utf-8") as f:
            for r in junk:
                r["quarantined_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        _write(keep)

    from collections import Counter
    why = Counter(r.get("quarantine_reason", "?")[:44] for r in junk)
    return {"ok": True, "backup": bak, "quarantined": len(junk), "kept": len(keep),
            "reasons": dict(why.most_common(6)), "restorable": True}


# ──── NIGHTSHIFT — consolidate the day into durable facts ─────────────────────
def nightshift() -> dict[str, Any]:
    """The consolidation pass: read back what she has learned and fold it into the store.
    Runs compaction first (there is no point consolidating a store full of duplicates),
    then the personality curator, which is what lets traits drift on evidence instead of
    standing still."""
    out: dict[str, Any] = {"ok": True, "steps": []}
    c = compact()
    out["steps"].append({"step": "compact", **{k: c[k] for k in
                        ("duplicates_retired", "paraphrases_retired", "conflicts_superseded")}})
    try:
        from harness.personality.curator import consolidate_personality
        res = consolidate_personality()
        out["steps"].append({"step": "personality", "result": str(res)[:160]})
    except Exception as exc:
        out["steps"].append({"step": "personality", "skipped": str(exc)[:120]})
    out["stats"] = stats()
    return out


# ──── memory add / remove (one row at a time, from the panel) ─────────────────
def add(fact: str, speaker: str = "user") -> dict[str, Any]:
    from harness.skills import memory as M
    M.set_author("self" if speaker == "self" else "user")
    try:
        res = M.remember(fact, source="operator")
    finally:
        M.set_author("user")
    return {"ok": not res.startswith("not stored"), "result": res, "stats": stats()}


def forget(name: str) -> dict[str, Any]:
    """Retire ONE row by name. Tombstone, not delete — the operator can see what he
    retired, and recall will skip it (lifecycle=1 is what the daemon reads)."""
    rows = _rows()
    hit = None
    for r in rows:
        if r.get("name") == name:
            r["lifecycle"] = 1
            r["superseded_by"] = "operator"
            r["superseded_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            hit = r
            break
    if hit:
        _write(rows)
    return {"ok": bool(hit), "retired": lc.strip_prefix(hit.get("text", "")) if hit else "",
            "stats": stats()}
