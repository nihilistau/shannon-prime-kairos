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
    from harness.skills import lifecycle as lc
    # LIVE (not retired), and FRAMED. It used to dump every row raw — including superseded
    # ones — so she read back tombstones as current, and read HIS first-person facts ("My
    # name is Knack") as if they were her own. The owner is stamped on the row; render it.
    eps = [e for e in _load() if not e.get("lifecycle")]
    if not eps:
        return "(memory is empty)"
    return "\n".join(f"{i + 1}. {lc.render(e)}" for i, e in enumerate(eps))


def remember(fact: str, source: str = "") -> str:
    """Store a fact in long-term memory. Pass the COMPLETE fact as a full standalone sentence
    (e.g. "The user's favorite color is teal", not just "teal") so it is meaningful on its own later.
    `source` (optional) records WHERE the fact came from (e.g. "user turn", "consolidator",
    "operator") for the MEM-OKF v2 provenance lane — recallable via provenance()."""
    p = _reg_path()
    if not p:
        return "[no registry configured]"
    # ADMISSION AT THE STORE (2026-07-12). The daemon's B4 gate now refuses impersonal
    # sentences — and she immediately stored one THROUGH THIS TOOL instead (G-ADMISSION
    # caught an ep_tool_ row holding "The kind nurse painted the tall building..."). An
    # invariant guarded in only ONE of the paths into memory is not guarded. Every path
    # enforces it now.
    from harness.skills import lifecycle as lc
    ok, why = lc.is_memorable(fact)
    if not ok:
        return f"not stored — {why}"
    # ── THE IDENTITY FIREWALL (2026-07-12) ──────────────────────────────────────
    # She answered "what is your name?" with "My name is Shannon." — correctly — and then
    # stored that sentence HERE, in the USER store. It was stamped speaker=user, classed
    # identity, and superseded all three rows that said the user is Knack. The store came
    # out of it asserting that KNACK IS CALLED SHANNON.
    #
    # Which door she writes to is the ONLY signal for whose fact it is, and she picked the
    # wrong one. The prompt already tells her; a prompt is advice, and the price of one
    # slip is the user's identity. So the door refuses it, and names the right door.
    if _AUTHOR != lc.SPEAKER_SELF:
        ok, why = lc.admit_to_user_store(fact, _self_names())
        if not ok:
            return f"not stored — {why}"
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
    # ── MEM-OKF v2 LIFECYCLE (2026-07-12) ───────────────────────────────────────
    # SUPERSEDE-ON-CONFLICT. A fact that fills the same slot with a DIFFERENT value
    # retires the old one — tombstoned, never deleted, so "what did I used to think?"
    # stays answerable. Without this the registry was an append-only tape: it could
    # accumulate "My cat's name is Tuffy" AND "My cat's name is Milo" and recall would
    # cheerfully surface whichever matched first.
    from harness.skills import lifecycle as lc
    speaker = lc.infer_speaker(fact, _AUTHOR)
    retired = lc.find_superseded(fact, speaker, existing)

    line = {
        "name": os.path.basename(out_dir),
        "dir": out_dir,
        "npos": npos,
        "topic": fact[:40],
        "sig_bits": "0" * 64,
    }
    lc.stamp(line, fact, speaker, source, supersedes=[r.get("name", "") for r in retired])

    # INTEROP (load-bearing): the DAEMON already excludes superseded episodes from the
    # live recall set — but it keys on the integer `lifecycle` field (recall.rs:587,
    # routes.rs:2342: `if ep.lifecycle != 0 { continue }`), NOT on `superseded_by`.
    # A tombstone that only carries `superseded_by` is invisible to the engine and the
    # retired fact keeps getting recalled. Stamp BOTH: `lifecycle` for the engine,
    # `superseded_by`/`superseded_at` for the audit trail.
    line["lifecycle"] = 0
    if retired:
        rows = _load()
        names = {r.get("name") for r in retired}
        with open(p, "w", encoding="utf-8") as f:
            for r in rows:
                if r.get("name") in names:
                    r["lifecycle"] = 1                     # the engine reads THIS
                    r["superseded_by"] = line["name"]      # the audit trail reads these
                    r["superseded_at"] = line["ts"]
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")

    note = ""
    if retired:
        old = lc.strip_prefix(_text(retired[0]))
        note = f" (superseded: '{old}')"
    return (f"stored: {fact}{note}"
            + ("" if minted else " (note: episode not minted; recall-on-restart only)"))


# WHO IS SPEAKING THIS TURN. The gateway sets this before dispatching tools. It is the
# load-bearing bit for identity: the SAME sentence ("I am male") is a fact about the
# USER when the user says it and a fact about SHANNON when she says it. Inferring the
# owner from the words at READ time is exactly how she started speaking as the user.
_AUTHOR = "user"


def set_author(who: str) -> None:
    global _AUTHOR
    _AUTHOR = "self" if who == "self" else "user"


def _self_names() -> set:
    """HER names — the ones that may never be filed as the user's identity. Read from the
    live persona so a rename renames the firewall too; the literals are the floor, not the
    source of truth."""
    names = {"shannon", "shannon-prime"}
    try:
        from harness.personality.persona_file import parse_persona
        path = os.environ.get("SP_PERSONA_FILE") or os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "persona.md")
        with open(path, encoding="utf-8") as f:
            _, state = parse_persona(f.read())
        for k in ("name", "self_name"):
            v = (state or {}).get(k)
            if isinstance(v, str) and v.strip():
                names.add(v.strip().lower())
    except Exception:
        pass
    return names


def remember_about_self(fact: str) -> str:
    """Store a fact about YOURSELF (Shannon) — your own traits, your history, what you
    think or have come to believe. Use this for things true of YOU, not of the user.
    e.g. remember_about_self("I find astronomy genuinely moving") — NOT the user's facts."""
    set_author("self")
    try:
        return remember(fact, source="self")
    finally:
        set_author("user")


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


def recall(query: str) -> str:
    """Look up what you KNOW about something — the fast, targeted way to answer a question
    from memory. Use this for any question about the user or about yourself
    (recall("what is the user's name") -> Knack told me: The user's name is Knack).
    Prefer this over list_memories, which dumps everything.

    WHY THIS TOOL EXISTS (2026-07-12). Her whole live toolset for READING memory was
    list_memories() — a dump of every row. It is expensive and undiscriminating, so she
    simply did not call it: asked "what is my name?" she skipped memory entirely and
    answered "I am Shannon-Prime." from her persona. She had no cheap way to LOOK SOMETHING
    UP, so she guessed. The ranked search had existed the whole time, parked in
    MEMORY_TOOLS_EXTRA and wired into no live toolset — the same drawer the personality
    tools were found in.

    And it renders through lifecycle.render(), which is the other half of the identity fix:
    a row that reads "My name is Knack" — first person, because HE said it — comes back
    from an unframed search looking like something SHE said. Framing the owner at READ time
    ("Knack told me: ..." / "About myself: ...") is what stops his facts arriving in her
    voice. Retired rows are excluded: superseded is superseded."""
    from harness.skills import lifecycle as lc
    hits = [(s, e) for s, e in search_memories_ranked_rows(query, k=12, min_overlap=0.25)
            if not e.get("lifecycle")]
    if not hits:
        return f"(nothing in memory about '{query}')"
    hits = _target_and_rank(query, hits)
    return "\n".join(f"{i + 1}. {lc.render(e)}" for i, (s, e) in enumerate(hits[:5]))


# ── WHO IS THE QUESTION ABOUT? (2026-07-12) ───────────────────────────────────
# The trace that forced this. Asked "what is my name?", recall returned:
#
#     1. Knack told me: My cat's name is Tuffy.
#     2. Knack told me: The user's name is Knack
#     3. About myself: My name is Shannon.
#
# ...and she answered "My name is Shannon." Of course she did — of the three, row 3 is the
# one whose SURFACE FORM matches the question. Pure token overlap cannot tell "my name" in
# HIS mouth from "my name" in HERS; it just sees the words line up.
#
# But the store already knows whose each fact is — `speaker` is stamped on every row. The
# missing step is reading the PRONOUN IN THE QUESTION: when he says "my", he is asking
# about HIM; when he says "your", he is asking about HER. Scope the search to that person
# and the ambiguity is gone at the source, rather than being left for the model to resolve
# by guessing — which is precisely the guess that keeps coming out wrong.
#
# The relationship penalty is the second half: "My cat's name is Tuffy" tied with "The
# user's name is Knack" at 1.00, because the query token was {name} and both rows have it.
# A row that drags in an entity the question never mentioned (a cat) is answering a
# question that was not asked.
_ASKS_SELF = re.compile(r"\b(your|yours|you|you're|youre)\b", re.I)
_ASKS_USER = re.compile(r"\b(my|mine|me|i|i'm|im)\b", re.I)
_REL_NOUN = re.compile(
    r"\b(wife|husband|partner|girlfriend|boyfriend|brother|sister|mother|father|mum|mom|"
    r"dad|son|daughter|friend|cat|dog|pet)\b", re.I)


# THE USER'S ACTUAL WORDS THIS TURN. The gateway sets this before the agent runs.
#
# WHY IT HAS TO BE HIS SENTENCE AND NOT HER QUERY (2026-07-12, from the trace). Asked
# "what is YOUR name?", she called recall(query="What is my name?") — she rewrites the
# question into her own first person, which is the natural thing to do. Asked "what is MY
# name?", she called recall(query="What is my name?") — the identical string. Two opposite
# questions, one query. So the pronoun in the string SHE passes carries no information
# about who is being asked after; it only tells you whose mouth the paraphrase is in.
#
# The pronoun is only reliable where it was UTTERED. In HIS sentence "my" means Knack and
# "your" means Shannon, always. So ownership is resolved from the human's words, and her
# query is used for what it is actually good for: matching the content.
_QUESTION = ""


def set_question(text: str) -> None:
    global _QUESTION
    _QUESTION = text or ""


def _query_target(query: str):
    """Whose fact is this question asking for? Resolved from HIS sentence, not from her
    paraphrase of it — see _QUESTION. 'your' -> hers. 'my' -> his."""
    from harness.skills import lifecycle as lc
    src = _QUESTION or query          # his words if we have them; hers only as a fallback
    if _ASKS_SELF.search(src):
        return lc.SPEAKER_SELF
    if _ASKS_USER.search(src):
        return lc.SPEAKER_USER
    return None


def _target_and_rank(query: str, hits):
    from harness.skills import lifecycle as lc
    target = _query_target(query)
    if target:
        owned = [(s, e) for s, e in hits
                 if (e.get("speaker") or lc.SPEAKER_USER) == target]
        if owned:                      # only narrow when the person HAS a matching fact
            hits = owned

    q_rel = set(m.lower() for m in _REL_NOUN.findall(query))
    qt = _toks(query)

    def adjust(s, e):
        t = _text(e)
        # a row that introduces a relative/pet the question never mentioned is off-target
        row_rel = set(m.lower() for m in _REL_NOUN.findall(t))
        if row_rel - q_rel:
            s -= 0.40
        # an identity question wants the identity row, not everything containing "name"
        if "name" in qt and e.get("mem_class") == "identity":
            s += 0.30
        return s

    return sorted(((adjust(s, e), e) for s, e in hits), key=lambda x: -x[0])


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
# remember_about_self is READY-NOW, not an extra. It is the SELF lane — the one she
# never had. Leaving it behind a load_tools() call is exactly how she ended up with 404
# memories of the user and none of herself. count_memories drops to the index tier to
# keep the ready-now set small (list_memories subsumes it).
# recall() JOINS THE LIVE SET. Without it her only way to READ memory was list_memories —
# a dump of everything — so she did not read at all, and answered from persona instead.
# A memory she cannot cheaply look up is a memory she does not have.
MEMORY_TOOLS = [remember, remember_about_self, recall, list_memories, forget]
# Extra tier: discoverable via the OKFS load_tools index (full signature on demand).
MEMORY_TOOLS_EXTRA = [provenance, search_memories, memory_stats]
# Hygiene tools are curation-tier (not in the hot chat set); used by the agency round + operator.
HYGIENE_TOOLS = [verify_registry, compact_registry]
