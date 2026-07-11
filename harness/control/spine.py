"""The HARNESS SPINE — ADR-007: one decide → execute → verify pipeline for the agent.

The engine grew a Spine (ADR-002, engine spine.rs): an immutable LatentView folded through
priority-ordered Deciders into a discrete LatentDecision, applied by an Executor the deciders
can't touch. The harness had the same logic SCATTERED: persona tags parsed in one interceptor,
hygiene inline in the agency tick, recall ad-hoc. This module is the harness-side mirror —
typed, priority-folded, receipted — plus the ADR-006 stage the engine version doesn't have yet:
a VERIFIER that checks the executor's own claim of success (verify-before-accept as law).

Shape (deliberately tiny — a fold, not a framework):

    TurnView (immutable facts about the turn)
      → [Decider.decide(view) -> list[Decision]]   (pure; CANNOT touch the world)
      → Executor.execute(decision) -> result        (the only side-effecting stage)
      → Verifier.verify(decision, result) -> bool   (objective post-check; a failed verify
                                                     marks the receipt VERIFY_FAIL, never hides it)
      → SpineReceipt (auditable record of every decision/result/verdict)

Everything is additive: callers opt in per-seam. No existing path changes behavior unless it
routes through run_spine.
"""
from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# ADR-008: the RECEIPT RING — every spine decision this process makes, observable.
# run_spine appends automatically; /v1/spine (gateway) + the operator panel read it.
_RECEIPT_RING: deque = deque(maxlen=200)
_SEQ = 0                      # monotone id per ring entry (the persistence watermark rides it)
_PERSISTED_SEQ = 0            # highest seq already flushed to the telemetry-okf store


def get_recent_receipts(k: int = 50) -> List[Dict[str, Any]]:
    """The last k spine receipts as JSON-able dicts (newest last)."""
    items = list(_RECEIPT_RING)[-k:]
    return [{"ts": ts, "kind": r.kind, "decider": r.decider, "ok": r.ok,
             "verified": r.verified, "result": r.result, "ms": round(r.ms, 1)}
            for _seq, ts, r in items]


def persist_receipts(root: str = "") -> int:
    """ADR-005 flywheel: flush unpersisted ring receipts into the DURABLE telemetry-okf store
    (content-addressed + idempotent via the existing TelemetrySink — reused, not rebuilt).
    Each receipt becomes a `kind: "spine"` record beside the engine's turn/decision records,
    so the flywheel's training/audit corpus includes what the harness DECIDED and whether the
    verify held. Returns the number of NEW records sunk. Receipts survive restarts; re-flushes
    dedup by content hash. (Spine results carry operational text + registry-tier facts only —
    the private-secret lane never routes through spine payloads; the ADR-005 redaction law is
    upheld by construction, and the sink never un-redacts regardless.)"""
    global _PERSISTED_SEQ
    import json as _json
    import os as _os
    root = root or _os.environ.get("SP_TELEMETRY_OKF_ROOT") or _os.path.join(
        _os.path.dirname(_os.path.dirname(_os.path.dirname(__file__))), "memory-okf-telemetry")
    try:
        from harness.telemetry.sink import TelemetrySink
        sink = TelemetrySink(root)
    except Exception as exc:
        logger.warning("[spine] telemetry sink unavailable: %s", exc)
        return 0
    new = 0
    hi = _PERSISTED_SEQ
    for seq, ts, r in list(_RECEIPT_RING):
        if seq <= _PERSISTED_SEQ:
            continue
        rec = _json.dumps({"kind": "spine", "ts": ts, "decider": r.decider, "decision": r.kind,
                           "ok": r.ok, "verified": r.verified, "result": r.result,
                           "ms": round(r.ms, 1)}, sort_keys=True)
        _, is_new = sink.sink(rec)
        if is_new:
            new += 1
        hi = max(hi, seq)
    _PERSISTED_SEQ = hi
    if new:
        logger.info("[spine] persisted %d receipt(s) -> %s", new, root)
    return new


# ──── the data ────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class TurnView:
    """Immutable facts a Decider may read. Frozen: deciders CANNOT mutate the turn."""
    phase: str                      # "pre" | "post" | "tick"
    user_text: str = ""             # last user message (pre/post)
    reply: str = ""                 # the model's reply (post)
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Decision:
    """A discrete, symbolic decision (ADR-002: the boundary object). kind routes to an executor."""
    kind: str
    payload: Dict[str, Any] = field(default_factory=dict)
    decider: str = ""
    priority: int = 50


@dataclass
class SpineReceipt:
    """One decision's auditable outcome."""
    kind: str
    decider: str
    ok: bool
    verified: Optional[bool]        # None = no verifier registered for this kind
    result: str
    ms: float


class Decider:
    """Pure decision stage. Subclass or wrap a function; MUST NOT side-effect."""
    name = "decider"
    priority = 50

    def decide(self, view: TurnView) -> List[Decision]:  # pragma: no cover - interface
        return []


class FnDecider(Decider):
    def __init__(self, name: str, fn: Callable[[TurnView], List[Decision]], priority: int = 50):
        self.name, self._fn, self.priority = name, fn, priority

    def decide(self, view: TurnView) -> List[Decision]:
        return self._fn(view) or []


# ──── the fold ────────────────────────────────────────────────────────────────
def run_spine(
    view: TurnView,
    deciders: List[Decider],
    executors: Dict[str, Callable[[Decision], str]],
    verifiers: Optional[Dict[str, Callable[[Decision, str], bool]]] = None,
) -> List[SpineReceipt]:
    """Fold the view through the deciders (priority order), execute each decision, verify each
    result. Never raises — a failing stage becomes an honest receipt, not a crash."""
    verifiers = verifiers or {}
    receipts: List[SpineReceipt] = []
    decisions: List[Decision] = []
    for d in sorted(deciders, key=lambda d: d.priority):
        try:
            for dec in d.decide(view):
                dec.decider = dec.decider or d.name
                dec.priority = d.priority
                decisions.append(dec)
        except Exception as exc:
            logger.warning("[spine] decider %s raised: %s", d.name, exc)
            receipts.append(SpineReceipt(kind="(decide)", decider=d.name, ok=False,
                                         verified=None, result=f"decider error: {exc}", ms=0.0))
    for dec in decisions:
        t0 = time.time()
        ex = executors.get(dec.kind)
        if ex is None:
            receipts.append(SpineReceipt(kind=dec.kind, decider=dec.decider, ok=False,
                                         verified=None, result="no executor", ms=0.0))
            continue
        try:
            result = str(ex(dec))
            ok = True
        except Exception as exc:
            result, ok = f"executor error: {exc}", False
        verified: Optional[bool] = None
        vf = verifiers.get(dec.kind)
        if vf is not None and ok:
            try:
                verified = bool(vf(dec, result))
            except Exception as exc:
                verified = False
                result += f" [verifier error: {exc}]"
            if verified is False:
                logger.warning("[spine] VERIFY_FAIL %s/%s: %s", dec.decider, dec.kind, result[:120])
        receipts.append(SpineReceipt(kind=dec.kind, decider=dec.decider, ok=ok,
                                     verified=verified, result=result[:400],
                                     ms=(time.time() - t0) * 1000.0))
    global _SEQ
    now = time.time()
    for r in receipts:
        _SEQ += 1
        _RECEIPT_RING.append((_SEQ, now, r))
    return receipts


# ──── the stock deciders / executors / verifiers (the seams we already own) ────
def persona_tag_decider() -> Decider:
    """POST-turn: if the reply carries [MOOD]/[VOICE]/[TRAIT] tags, decide a persona_shift."""
    import re
    tag_re = re.compile(r"\[(?:MOOD|VOICE|TRAIT):[^\]]+\]")

    def fn(view: TurnView) -> List[Decision]:
        if view.phase != "post" or not tag_re.search(view.reply or ""):
            return []
        return [Decision(kind="persona_shift", payload={"reply": view.reply})]
    return FnDecider("persona_tags", fn, priority=30)


def hygiene_decider() -> Decider:
    """TICK: if the registry verify-report says NEEDS COMPACTION, decide a compaction."""
    def fn(view: TurnView) -> List[Decision]:
        if view.phase != "tick":
            return []
        from harness.skills.memory import verify_registry
        report = verify_registry()
        if "NEEDS COMPACTION" in report:
            return [Decision(kind="compact_registry", payload={"report": report})]
        return []
    return FnDecider("hygiene", fn, priority=40)


def recall_decider(min_overlap: float = 0.34) -> Decider:
    """PRE-turn: if stored facts strongly match the user's message, decide a context injection
    (the harness-side text-in-context recall; the engine's L5 path stays authoritative when on)."""
    def fn(view: TurnView) -> List[Decision]:
        if view.phase != "pre" or not view.user_text:
            return []
        from harness.skills.memory import (search_memories_ranked_rows, attr_absent,
                                           DECLINE_MSG, _text)
        hits = search_memories_ranked_rows(view.user_text, k=3, min_overlap=min_overlap)
        if not hits:
            return []
        # ── MEM-OKF per-entry policy dispatch (P1b-2b; G-MEMPOLICY-V3 doctrine).
        # The harness is the ONE recall authority post-rehoming, so it must honor
        # the per-entry classes the engine dispatch honored:
        #   private-secret + absent attr  -> ZERO-INFERENCE fixed decline (the
        #       turn never reaches the model; confab/leak impossible)
        #   private-secret + present attr -> recite (fact enters the note)
        #   counterfact                   -> authoritative override framing
        #   persona / untagged            -> plain note (today's behavior)
        _top_score, top = hits[0]
        if top.get("mem_class") == "private-secret" and attr_absent(view.user_text, _text(top)):
            return [Decision(kind="decline_recall", payload={"message": DECLINE_MSG})]
        facts = []
        for _s, row in hits:
            t = _text(row)
            mc = row.get("mem_class", "")
            if mc == "private-secret" and attr_absent(view.user_text, t):
                continue  # never surface a secret's text for an attribute it lacks
            if mc == "counterfact":
                t = ("Fact on record (authoritative for this conversation, "
                     "overrides prior knowledge): " + t)
            facts.append(t)
        if not facts:
            return []
        return [Decision(kind="inject_recall", payload={"facts": facts})]
    return FnDecider("recall", fn, priority=20)


def toolset_decider() -> Decider:
    """PRE-turn (ADR-008): pick WHICH tool tier the turn advertises. The banked rule is a 12B
    picks reliably from ≤6 tools — this decider makes those six the RIGHT six for the turn:
    coding words → the coding set; memory words → the memory set (+extras); else → core.
    Deterministic keyword routing (no model call, no latency): the tiers are coarse on purpose —
    a wrong pick degrades to load_tools discovery, never to a hard failure."""
    coding_kw = ("code", "file", "edit", "fix", "bug", "test", "pytest", "function", "script",
                 "refactor", "compile", "build", "implement", "write a", "debug", "error", "diff")
    memory_kw = ("remember", "forget", "memory", "memories", "recall", "know about me",
                 "what do you know", "where did you learn", "provenance", "stored")

    def fn(view: TurnView) -> List[Decision]:
        if view.phase != "pre" or not view.user_text:
            return []
        low = view.user_text.lower()
        tier = "core"
        if any(k in low for k in coding_kw):
            tier = "coding"
        elif any(k in low for k in memory_kw):
            tier = "memory"
        if tier == "core":
            return []                      # default set — no decision needed (null floor)
        return [Decision(kind="select_toolset", payload={"tier": tier})]
    return FnDecider("toolset", fn, priority=10)


def toolset_for(tier: str):
    """Resolve a toolset tier to (core_specs, extra_specs) for run_with_tools/agent streams."""
    from harness.mcp.tools import ToolSpec
    if tier == "coding":
        from harness.skills.builtin.coding import (read_file, write_file, edit_file,
                                                   search, run_tests, run_command)
        core = [ToolSpec.from_callable(f) for f in
                (read_file, write_file, edit_file, search, run_tests, run_command)]
    elif tier == "memory":
        from harness.skills.memory import MEMORY_TOOLS, MEMORY_TOOLS_EXTRA
        core = [ToolSpec.from_callable(f) for f in (MEMORY_TOOLS + MEMORY_TOOLS_EXTRA[:2])]
    else:
        return None, None                  # caller keeps its defaults
    from harness.agent import all_tools
    core_names = {t.name for t in core}
    extra = [t for t in all_tools() if t.name not in core_names]
    return core, extra


def stock_executors() -> Dict[str, Callable[[Decision], str]]:
    def ex_persona(dec: Decision) -> str:
        from harness.personality.interceptor import apply_personality_tags
        _, state = apply_personality_tags(dec.payload.get("reply", ""))
        return "persona state now: " + "; ".join(f"{k}={v}" for k, v in state.items() if v)

    def ex_compact(dec: Decision) -> str:
        from harness.skills.memory import compact_registry
        return compact_registry()

    def ex_inject(dec: Decision) -> str:
        # The caller reads the decision's payload to build the turn; executing it is a no-op
        # marker (the injection happens in the prompt assembly, which the caller owns).
        return f"recall context ready: {len(dec.payload.get('facts', []))} fact(s)"

    def ex_toolset(dec: Decision) -> str:
        return f"toolset tier: {dec.payload.get('tier', 'core')}"

    return {"persona_shift": ex_persona, "compact_registry": ex_compact,
            "inject_recall": ex_inject, "select_toolset": ex_toolset}


def stock_verifiers() -> Dict[str, Callable[[Decision, str], bool]]:
    """ADR-006 law: the executor's claim is CHECKED, not trusted."""
    def vf_persona(dec: Decision, result: str) -> bool:
        # re-read persona.md and confirm the tagged mood/voice actually landed
        import re
        from harness.personality.persona_file import parse_persona
        from harness.personality.interceptor import _persona_path, _MOOD, _VOICE
        try:
            from pathlib import Path
            _, state = parse_persona(Path(_persona_path()).read_text(encoding="utf-8"))
        except Exception:
            return False
        reply = dec.payload.get("reply", "")
        moods = _MOOD.findall(reply)
        if moods and state.get("mood", "").strip() != moods[-1].strip():
            return False
        voices = _VOICE.findall(reply)
        if voices and state.get("voice", "").strip() != voices[-1].strip():
            return False
        return True

    def vf_compact(dec: Decision, result: str) -> bool:
        from harness.skills.memory import verify_registry
        return "NEEDS COMPACTION" not in verify_registry()

    return {"persona_shift": vf_persona, "compact_registry": vf_compact}


def run_pre_turn(user_text: str, *, recall: bool = False, toolset: bool = False):
    """The gateway's pre-turn spine (ADR-008). Returns (receipts, decisions) — the caller reads
    the decisions' payloads (recall facts / toolset tier) to assemble the turn; the spine only
    DECIDES + receipts. Flags select which deciders arm (both default-off at the call site)."""
    deciders: List[Decider] = []
    if toolset:
        deciders.append(toolset_decider())
    if recall:
        deciders.append(recall_decider())
    view = TurnView(phase="pre", user_text=user_text)
    decisions: List[Decision] = []
    for d in sorted(deciders, key=lambda d: d.priority):
        try:
            for dec in d.decide(view):
                dec.decider = dec.decider or d.name
                decisions.append(dec)
        except Exception as exc:
            logger.warning("[spine] pre-turn decider %s raised: %s", d.name, exc)
    receipts = run_spine(view, deciders, stock_executors(), stock_verifiers())
    return receipts, decisions


def run_post_turn(user_text: str, reply: str) -> List[SpineReceipt]:
    """The gateway's post-turn spine: persona tags (extensible)."""
    view = TurnView(phase="post", user_text=user_text, reply=reply)
    return run_spine(view, [persona_tag_decider()], stock_executors(), stock_verifiers())


def run_tick() -> List[SpineReceipt]:
    """The KAIROS tick spine: hygiene (extensible)."""
    view = TurnView(phase="tick")
    return run_spine(view, [hygiene_decider()], stock_executors(), stock_verifiers())
