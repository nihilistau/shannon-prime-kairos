"""Memory tools — the model's explicit handle on its own long-term memory.

These operate on the daemon's persistent episode registry (``SP_RECALL_REGISTRY``),
the same content-addressed store the autonomous recall path reads. Exposed as
ephemeral tools (``ToolSpec.from_callable``) so the served model can *deliberately*
introspect, store, and forget facts — unifying the memory system with tool calling.
The autonomous memory-agency (forget/decide/merge in the daemon) keeps running; these
give the model a first-person lever on the same store.

Each function is a plain callable with a typed signature, so
``ToolSpec.from_callable`` derives the tool schema automatically.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.request
from typing import List

_STOP = {"the", "a", "an", "is", "are", "of", "to", "in", "on", "and", "or",
         "my", "your", "you", "it", "that", "this", "was", "were", "has", "have",
         # P1b-2b: question/aux words are MATCH NOISE — "when did my locker
         # combination last change?" scored 2/6=0.33 vs the 0.34 threshold
         # purely because "when"/"did"/"last" diluted the denominator. Facts
         # rarely contain these, so removing them sharpens matching symmetric-
         # ally (the audit gates re-ran GREEN after this change).
         "what", "who", "where", "when", "why", "how", "which",
         "did", "does", "do", "can", "could", "would", "should", "will",
         "had", "these", "those", "there", "here", "just", "please"}


def _reg_path() -> str:
    return os.environ.get("SP_RECALL_REGISTRY", "")


def _load() -> List[dict]:
    p = _reg_path()
    if not p or not os.path.exists(p):
        return []
    eps = []
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                eps.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return eps


def _text(e: dict) -> str:
    return e.get("text") or e.get("topic") or ""


def _toks(s: str) -> set:
    words = "".join(c.lower() if c.isalnum() else " " for c in s).split()
    return {w for w in words if len(w) >= 3 and w not in _STOP}


def _overlap(query: str, target: str) -> float:
    qt = _toks(query)
    if not qt:
        return 0.0
    return len(qt & _toks(target)) / len(qt)


# ──── the tools ────────────────────────────────────────────────────────────
def list_memories() -> str:
    """List every fact currently stored in long-term memory."""
    eps = _load()
    if not eps:
        return "(memory is empty)"
    return "\n".join(f"{i + 1}. {_text(e)}" for i, e in enumerate(eps))


def remember(fact: str, source: str = "") -> str:
    """Store a fact in long-term memory. Pass the COMPLETE fact as a full standalone sentence
    (e.g. "The user's favorite color is teal", not just "teal") so it is meaningful on its own later.
    `source` (optional) records WHERE the fact came from (e.g. "user turn", "consolidator",
    "operator") for the MEM-OKF v2 provenance lane — recallable via provenance()."""
    p = _reg_path()
    if not p:
        return "[no registry configured]"
    existing = _load()
    # Idempotent EXACT: never store a fact already in memory verbatim (prevents the agency
    # loop from accumulating duplicates when it re-asserts an existing fact).
    if any(_text(e).strip() == fact.strip() for e in existing):
        return f"already in memory: {fact}"
    # MEM-OKF v2 §M2 near-dup guard: a fact whose tokens are ~fully covered by an existing
    # fact (overlap >= 0.9 both ways) is a paraphrase, not new knowledge — skip it so the
    # extraction pass doesn't bloat the registry with restatements. (The DECIDE/MERGE layer
    # in the daemon still handles genuine supersede/consolidate on conflicting facts.)
    ft = _toks(fact)
    if ft:
        for e in existing:
            et = _toks(_text(e))
            if not et:
                continue
            inter = len(ft & et)
            if inter / len(ft) >= 0.9 and inter / len(et) >= 0.9:
                return f"already in memory (paraphrase of): {_text(e)}"
    # Mint the episode (ep.k/ep.v/ep.mf) via the daemon so the fact is RECALL-able,
    # not just listed. Degrades gracefully: if the daemon is unreachable the fact is
    # still recorded for introspection/curation.
    daemon = os.environ.get("SP_DAEMON_URL", "http://127.0.0.1:3000")
    out_dir = os.path.join(os.path.dirname(p), "eps", f"ep_tool_{int(time.time() * 1000)}")
    out_dir = out_dir.replace("\\", "/")
    npos = 0
    minted = False
    try:
        body = json.dumps({"text": fact, "out_dir": out_dir}).encode()
        req = urllib.request.Request(
            daemon + "/v1/capture", data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as r:
            j = json.loads(r.read().decode())
        npos = int(j.get("npos", 0))
        minted = bool(j.get("ok", False)) or npos > 0
    except Exception:
        minted = False
    line = {
        "name": os.path.basename(out_dir),
        "dir": out_dir,
        "npos": npos,
        "topic": fact[:40],
        "text": fact,
        "sig_bits": "0" * 64,
        # MEM-OKF v2 §M1 provenance lane: stamp WHERE + WHEN this fact entered memory.
        # Additive fields — older readers ignore them; recall recites them on demand.
        "src": source or "user",
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(line) + "\n")
    return f"stored: {fact}" + ("" if minted else " (note: episode not minted; recall-on-restart only)")


def provenance(fact: str) -> str:
    """Answer "where/when did I learn X?" — return the source + timestamp of the stored fact
    that best matches the query (MEM-OKF v2 §M1). The recallable provenance lane."""
    eps = _load()
    if not eps:
        return "(memory is empty)"
    best, hit = -1.0, None
    for e in eps:
        ov = _overlap(fact, _text(e))
        if ov > best:
            best, hit = ov, e
    if best < 0.3 or hit is None:
        return f"no stored fact matches '{fact}'"
    src = hit.get("src", "unknown source")
    ts = hit.get("ts", "unknown time")
    return f"'{_text(hit)}' — learned from {src} at {ts}"


def forget(fact: str) -> str:
    """Remove a stored fact from memory (matches the closest stored fact by overlap)."""
    p = _reg_path()
    eps = _load()
    if not eps:
        return "(memory is empty)"
    best = -1.0
    victim = ""
    for e in eps:
        ov = _overlap(fact, _text(e))
        if ov > best:
            best = ov
            victim = _text(e)
    if best < 0.3 or not victim:
        return f"no stored fact matches '{fact}'"
    kept = [e for e in eps if _text(e) != victim]
    with open(p, "w", encoding="utf-8") as f:
        for e in kept:
            f.write(json.dumps(e) + "\n")
    return f"forgot: {victim}"


def count_memories() -> str:
    """Count how many facts are currently stored in long-term memory."""
    return str(len(_load()))


# ──── ADR-007: ranked memory search (scales past the list_memories dump) ─────
# ── MEM-OKF per-entry policy dispatch (P1b-2b, G-MEMPOLICY-V3 doctrine) ──────
# The fixed decline for a private-secret whose asked-about attribute is NOT in
# the record: streamed with ZERO model inference so confabulation/leak is
# impossible by construction (mirrors the engine attr-gate + mempolicy_run.py).
DECLINE_MSG = "I have a record for that, but it does not include that specific detail."

_ATTR_STOP = set(
    "the a an of to in on at for and or is are was what which who where when "
    "my your name number code colour color brand breed seat".split())


def attr_absent(query: str, fact: str) -> bool:
    """Deterministic attr-gate (G-MEMPOLICY-V3 doctrine, recalibrated): the query
    matched the record (ranked overlap got us here) but asks for an attribute the
    record lacks. CALIBRATION NOTE: the engine runner's `>= len(qs)*0.6` rule is
    untrippable on its own printed test data (e.g. {installed, workshop, door}
    with one absent = 1 < 1.8) — those cases fell to the tolerated forward
    branch. Rehomed rule: decline iff ≥2 salient query tokens are absent AND
    they are at least HALF the salient set — elaborated-but-present questions
    ("…combination for the gym?", one stray token) still recite; genuinely
    different-attribute questions ("when did … last change?") decline."""
    qs = {w for w in re.findall(r"[a-z0-9]+", query.lower()) if len(w) > 2} - _ATTR_STOP - _STOP
    if not qs:
        return False
    fs = {w for w in re.findall(r"[a-z0-9]+", fact.lower()) if len(w) > 2}
    salient_absent = [w for w in qs if w not in fs]
    return len(salient_absent) >= 2 and len(salient_absent) * 2 >= len(qs)


def search_memories_ranked_rows(query: str, k: int = 5, min_overlap: float = 0.25):
    """Like search_memories_ranked but returns (score, ROW) so callers can read
    per-entry policy fields (mem_class etc.). The policy dispatch rides this."""
    clause = re.split(r"[.:;!]", query)[-1].strip() or query
    eps = _load()
    scored = []
    for e in eps:
        t = _text(e)
        ov = _overlap(query, t)
        if clause != query:
            ov = max(ov, _overlap(clause, t))
        if ov >= min_overlap:
            scored.append((ov, e))
    scored.sort(key=lambda x: -x[0])
    return scored[:k]


def search_memories_ranked(query: str, k: int = 5, min_overlap: float = 0.25):
    """Internal: [(score, text)] of the top-k facts by token overlap with the query,
    filtered at min_overlap. The RecallDecider + search tool ride this.

    P1b-2 live-play fix (2026-07-11): the query-normalized overlap dilutes under
    polite prefixes — "quick check: what is my name?" tokenizes to {quick, check,
    name} = 1/3 = 0.33, one hundredth UNDER the 0.34 recall threshold, while bare
    "what is my name?" scores 1.0. The question is almost always the FINAL
    clause, so score the last [.:;!]-separated clause too and take the max —
    prefix chatter can no longer dilute a clean question. Deterministic; the
    junk-recall floor (QONLY gate + threshold) is unchanged for single-clause turns.
    """
    clause = re.split(r"[.:;!]", query)[-1].strip() or query
    eps = _load()
    scored = []
    for e in eps:
        t = _text(e)
        ov = _overlap(query, t)
        if clause != query:
            ov = max(ov, _overlap(clause, t))
        if ov >= min_overlap:
            scored.append((ov, t))
    scored.sort(key=lambda x: -x[0])
    return scored[:k]


def search_memories(query: str) -> str:
    """Search long-term memory for facts relevant to a query (ranked; better than
    list_memories when memory is large)."""
    hits = search_memories_ranked(query, k=5)
    if not hits:
        return f"(no stored facts match '{query}')"
    return "\n".join(f"{i+1}. {t}  [match {s:.2f}]" for i, (s, t) in enumerate(hits))


def memory_stats() -> str:
    """A one-line summary of the memory store: count, provenance mix, minted fraction."""
    eps = _load()
    if not eps:
        return "(memory is empty)"
    srcs: dict = {}
    minted = 0
    for e in eps:
        srcs[e.get("src", "unknown")] = srcs.get(e.get("src", "unknown"), 0) + 1
        if int(e.get("npos", 0) or 0) > 0:
            minted += 1
    mix = ", ".join(f"{k}:{v}" for k, v in sorted(srcs.items(), key=lambda x: -x[1]))
    return f"{len(eps)} facts ({minted} minted for recall); sources: {mix}"


# ──── MEM-OKF v2 §M3: registry hygiene (verify + compaction) ────────────────
def verify_registry() -> str:
    """Integrity check on the fact registry: count rows, malformed lines, exact duplicates,
    near-duplicate paraphrase pairs, and rows missing an episode dir. Read-only report."""
    p = _reg_path()
    if not p or not os.path.exists(p):
        return "[no registry configured]"
    rows, malformed = 0, 0
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows += 1
            try:
                json.loads(line)
            except json.JSONDecodeError:
                malformed += 1
    eps = _load()
    texts = [_text(e).strip() for e in eps]
    exact_dups = len(texts) - len(set(texts))
    near = 0
    for i in range(len(eps)):
        ti = _toks(texts[i])
        if not ti:
            continue
        for j in range(i + 1, len(eps)):
            tj = _toks(texts[j])
            if tj and len(ti & tj) / len(ti) >= 0.9 and len(ti & tj) / len(tj) >= 0.9:
                near += 1
    no_ep = sum(1 for e in eps if not e.get("dir") or int(e.get("npos", 0) or 0) <= 0)
    no_prov = sum(1 for e in eps if not e.get("src"))
    ok = malformed == 0 and exact_dups == 0
    return (f"registry {p}: rows={rows} parsed={len(eps)} malformed={malformed} "
            f"exact_dups={exact_dups} near_dups={near} unminted={no_ep} no_provenance={no_prov} "
            f"-> {'OK' if ok else 'NEEDS COMPACTION'}")


def compact_registry() -> str:
    """Rewrite the registry dropping malformed lines + exact duplicates (keeps first occurrence),
    preserving order. Near-dups and provenance are left intact (curation, not deletion)."""
    p = _reg_path()
    if not p or not os.path.exists(p):
        return "[no registry configured]"
    seen, kept, dropped = set(), [], 0
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                dropped += 1
                continue
            key = _text(e).strip()
            if key and key in seen:
                dropped += 1
                continue
            seen.add(key)
            kept.append(e)
    with open(p, "w", encoding="utf-8") as f:
        for e in kept:
            f.write(json.dumps(e) + "\n")
    return f"compacted: kept {len(kept)}, dropped {dropped}"


# HOT chat set stays curated (the banked ≤6-tools rule: a 12B stalls exploring a big set).
MEMORY_TOOLS = [list_memories, count_memories, remember, forget]
# Extra tier: discoverable via the OKFS load_tools index (full signature on demand).
MEMORY_TOOLS_EXTRA = [provenance, search_memories, memory_stats]
# Hygiene tools are curation-tier (not in the hot chat set); used by the agency round + operator.
HYGIENE_TOOLS = [verify_registry, compact_registry]
