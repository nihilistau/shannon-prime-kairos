"""verdict — Phase B of docs/INVARIANT-MEMORY.md: THE evaluator. Rules are DATA.

The committed verdict table (harness_tests/fixtures/sem/verdict-table.json, frozen by
sem_enum.py --freeze, pinned by G-SEM-TABLE) is the law. This module is the ONE
implementation of the signature: it computes a row's CELL from the system's OPERATIONAL
relations and looks the ruling up. The enumerator imports THESE functions — if a second
copy of sigma() ever exists, it will drift, and that is the two-paths bug with a
mathematician's hat on.

NORMALIZATION LAW (read off the running code, not invented):
    status   missing -> observed     (lifecycle.testimony_wins: `or STATUS_OBSERVED` —
                                      77 of her 81 live rows predate the status field)
    speaker  missing -> user         (same seam, same default)
    mem_class missing -> fact        (lifecycle.salience's default)

THE EVALUATOR NEVER GUESSES. A cell absent from the table returns None (UNMAPPED) and
shadow mode COUNTS it — it does not invent a ruling. An unmapped cell reaching the
counter is Phase A's completeness failing in the field, which is exactly the news you
want loudly.

SHADOW MODE (SP_SEM_LAW=1, mapped in serve.py): the seam calls shadow() on its FINAL
result set. One direction is checked, and it is the load-bearing one:

    EVERYTHING ADMITTED MUST BE TABLE-ADMISSIBLE.

(The other direction — something the table would admit that the seam did not — is not
checkable here: absence may lawfully be the lexical match-gate, and the match-gate is
admission-by-MATCH, not policy.) Divergences and unmapped cells are counters plus
optional witness lines (SP_SEM_LAW_LOG). Shadow NEVER raises, NEVER alters results,
NEVER blocks speech. Cutover (the seam consulting ruling() as its filter) is Phase B2,
and its precondition is a zero-divergence receipt from this shadow.
"""
import json
import os
import threading

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TABLE_PATH = os.path.join(_ROOT, "harness_tests", "fixtures", "sem", "verdict-table.json")

_LOCK = threading.RLock()
_TABLE = {"mtime": None, "cells": None}
_STATS = {"checked": 0, "divergent": 0, "unmapped": 0}


# ── the ONE signature implementation ───────────────────────────────────────────────────
def sigma(row: dict) -> dict:
    """Normalized signature coordinates of a row (the normalization law above)."""
    return {
        "speaker": row.get("speaker") or "user",
        "status": row.get("status") or "observed",
        "lifecycle": 1 if row.get("lifecycle") else 0,
        "mem_class": row.get("mem_class") or "fact",
    }


def _ground_truth():
    from harness.skills import lifecycle as lc
    return getattr(lc, "_GROUND_TRUTH", frozenset({"observed", "confirmed"}))


def competition(row: dict, rows: list) -> str:
    """OPERATIONAL competition coordinate: does a LIVE ground-truth row of the SAME
    speaker cover this row's topic (testimony_wins's exact relation)? Only meaningful
    for non-ground-truth rows; ground truth gets '.' (not applicable)."""
    from harness.skills import lifecycle as lc
    s = sigma(row)
    if s["status"] in _ground_truth():
        return "."
    mine = lc.topic_of(lc.strip_prefix(row.get("text") or row.get("topic") or ""))
    for r in rows:
        if r is row or r.get("name") == row.get("name"):
            continue
        rs = sigma(r)
        if rs["lifecycle"] == 0 and rs["status"] in _ground_truth() \
                and rs["speaker"] == s["speaker"]:
            theirs = lc.topic_of(lc.strip_prefix(r.get("text") or r.get("topic") or ""))
            if len(mine & theirs) >= 2:
                return "1"
    return "0"


def attr(row: dict, query: str) -> str:
    """OPERATIONAL attr coordinate: attr_absent() itself, secrets only."""
    if sigma(row)["mem_class"] != "private-secret":
        return "."
    from harness.skills import memory as M
    return "-" if M.attr_absent(query, row.get("text") or "") else "+"


def cell(row: dict, query: str, rows: list) -> str:
    s = sigma(row)
    return "speaker=%s|status=%s|lifecycle=%d|class=%s|competition=%s|attr=%s" % (
        s["speaker"], s["status"], s["lifecycle"], s["mem_class"],
        competition(row, rows), attr(row, query))


# ── the table ──────────────────────────────────────────────────────────────────────────
def load_table() -> dict:
    with _LOCK:
        try:
            mt = os.path.getmtime(TABLE_PATH)
        except Exception:
            return {}
        if _TABLE["mtime"] == mt and _TABLE["cells"] is not None:
            return _TABLE["cells"]
        try:
            with open(TABLE_PATH, encoding="utf-8") as f:
                cells = {c: v["ruling"] for c, v in json.load(f)["table"].items()}
        except Exception:
            cells = {}
        _TABLE.update(mtime=mt, cells=cells)
        return cells


def ruling(row: dict, query: str, rows: list):
    """The law's answer for this row under this query: {'seam','spoken','declined'}
    or None (UNMAPPED — never guessed)."""
    return load_table().get(cell(row, query, rows))


# ── shadow (read-only, unarmed unless SP_SEM_LAW=1) ───────────────────────────────────
def stats() -> dict:
    with _LOCK:
        return dict(_STATS)


def _witness(kind: str, q: str, c: str):
    p = os.environ.get("SP_SEM_LAW_LOG", "")
    if not p:
        return
    try:
        d = os.path.dirname(p)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps({"kind": kind, "query": q[:120], "cell": c}) + "\n")
    except Exception:
        pass


def shadow(query: str, admitted_rows: list, all_rows: list) -> None:
    """Called by the seam on its FINAL results. Checks: everything admitted is
    table-admissible. Counters + optional witnesses; never raises, never alters."""
    try:
        if os.environ.get("SP_SEM_LAW", "0") != "1":
            return
        table = load_table()
        if not table:
            return
        with _LOCK:
            for e in admitted_rows:
                c = cell(e, query, all_rows)
                r = table.get(c)
                _STATS["checked"] += 1
                if r is None:
                    _STATS["unmapped"] += 1
                    _witness("unmapped", query, c)
                elif not r.get("seam", False):
                    _STATS["divergent"] += 1
                    _witness("divergent", query, c)
    except Exception:
        pass                     # the law's shadow may never cost her a sentence
