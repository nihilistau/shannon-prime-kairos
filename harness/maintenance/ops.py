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
def cleanup(dry: bool = False) -> dict[str, Any]:
    """Quarantine rows that are not memories — and RESCUE the facts trapped inside them.

    REVERSIBLE: everything lands in quarantine.jsonl with a reason, and the registry is
    backed up first. Nothing is destroyed.

    THE RESCUE PASS (2026-07-12) exists because the old capture stored whole TURNS. A row
    like

        "look, it's not my fault. I had a 2060 6gb super and i got a new intel nuc"

    fails the durability test as a unit — it opens with a discourse marker and an
    anaphoric non-fact — so a plain cleanup would quarantine it and take the 2060 and the
    NUC with it. But the fact is IN there; it is just wearing a conversation. So before a
    row is quarantined we split it and keep whatever is durable, re-stamped as a proper
    fact. The junk goes; what the junk was carrying stays.

    LEGACY ROWS (27 of them) carry no speaker at all — they predate the two-store lane, so
    recall could not tell whose they were. Anything surviving cleanup gets stamped: it came
    from a user turn, so it is the user's."""
    rows = _rows()
    bak = None if dry else _backup()
    keep, junk, rescued = [], [], []
    seen = {lc.strip_prefix(r.get("text") or r.get("topic") or "").strip().lower()
            for r in rows}

    for r in rows:
        if r.get("lifecycle"):
            keep.append(r)                                # already retired; leave it
            continue
        txt = lc.strip_prefix(r.get("text") or r.get("topic") or "")

        # A ROW IN THE STORE IS ONE FACT, NOT A TURN — the same standard the capture lane
        # now holds new writes to. The first dry run of this KEPT
        #
        #     "well, we make do. you're doing alright for such a constrained system"
        #
        # because is_memorable() was asked about the whole multi-sentence turn and the
        # leading fragment carried it. Judging a turn as a unit is the original sin: it is
        # what let the firehose in, and it would have let the firehose's leavings stay.
        # So a multi-sentence row is quarantined and its durable sentences RESCUED — the
        # row is rebuilt as facts instead of being graded as prose.
        ok, why = lc.is_memorable(txt)
        if ok and len(lc.split_sentences(txt)) == 1:
            # LEGACY: no speaker means recall could not tell whose fact it was.
            if not r.get("speaker"):
                r["speaker"] = lc.SPEAKER_USER
                r["mem_class"] = r.get("mem_class") or lc.classify(txt)
                r["src"] = (r.get("src") or "") + " | cleanup: stamped speaker=user"
            keep.append(r)
            continue
        if ok:
            why = "that is a TURN, not a fact — split into the facts it carries"

        # RESCUE before quarantine — the turn is junk, but it may be CARRYING a fact.
        for f in lc.extract_facts(txt):
            if f.strip().lower() in seen:
                continue
            seen.add(f.strip().lower())
            row = {"name": f"ep_rescue_{int(time.time() * 1000)}_{len(rescued)}",
                   "dir": "", "npos": 0, "topic": f[:40], "sig_bits": "0" * 64}
            lc.stamp(row, f, r.get("speaker") or lc.SPEAKER_USER,
                     f"rescued from {r.get('name', '?')}")
            keep.append(row)
            rescued.append(f)

        junk.append({**r, "quarantine_reason": why})

    if junk and not dry:
        q = os.path.join(os.path.dirname(_reg()), "quarantine.jsonl")
        with open(q, "a", encoding="utf-8") as f:
            for r in junk:
                r["quarantined_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        _write(keep)

    from collections import Counter
    why = Counter(r.get("quarantine_reason", "?")[:44] for r in junk)
    return {"ok": True, "dry_run": dry, "backup": bak,
            "quarantined": len(junk), "kept": len(keep) - len(rescued),
            "rescued": len(rescued), "rescued_facts": rescued[:12],
            "quarantined_sample": [r.get("text", "")[:60] for r in junk[:12]],
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
