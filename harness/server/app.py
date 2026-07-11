"""
SSE Gateway
==========

The harness's server side: an OpenAI-compatible HTTP gateway that wraps the
Shannon-Prime native daemon. External callers get the familiar
``POST /v1/chat/completions`` (streaming SSE or blocking); internally each
request is governed by the interceptor pipeline and forwarded to ``sp-daemon``.

This is the "custom server" half of replacing LMStudio: the daemon speaks
Shannon-Prime native ``/v1/chat``; this gateway speaks OpenAI so existing tools
(and the harness CLI) can talk to it unchanged.

Uses Flask if installed; otherwise a stdlib ``http.server`` fallback so the
gateway runs with zero third-party deps.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Iterator

from harness.inference import InferenceConfig, get_client
from harness.observability import get_logger

logger = get_logger(__name__)


# ──── Request handling (framework-agnostic core) ─────────────────────────
def _to_config(body: Dict[str, Any]) -> InferenceConfig:
    return InferenceConfig(
        temperature=body.get("temperature"),
        top_p=body.get("top_p"),
        max_tokens=body.get("max_tokens", 512),
        stop=body.get("stop"),
        seed=body.get("seed"),
        model=body.get("model"),
        # Shannon-Prime extensions, passed through if present
        byteexact=body.get("byteexact"),
        auto_recall=body.get("auto_recall"),
    )


def _chunk(delta: str, model: str, finish: str | None = None) -> str:
    obj = {
        "id": f"chatcmpl-{int(time.time()*1000)}",
        "object": "chat.completion.chunk",
        "model": model,
        "choices": [{
            "index": 0,
            "delta": {"content": delta} if delta else {},
            "finish_reason": finish,
        }],
    }
    return f"data: {json.dumps(obj)}\n\n"


def _agent_text(body: Dict[str, Any]) -> str:
    """Run the request through the AGENT loop (Gemma tool calling) unless tools are disabled.
    This is the unification: the model CALLS its tools (memory/system/web) in the chat, instead
    of a passthrough with no tool calling. Set body['tools']=false (or 'use_tools':false) to skip."""
    use_tools = body.get("tools", body.get("use_tools", True)) is not False
    msgs = body.get("messages", [])
    if not use_tools:
        return get_client().chat(messages=msgs, config=_to_config(body)).text
    from harness.agent import agent_chat
    from harness.inference import InferenceConfig
    cfg = InferenceConfig(
        temperature=body.get("temperature", 0.0),
        max_tokens=body.get("max_tokens", 256),
        auto_recall=False,  # the model uses tools, not the daemon's heuristic recall
    )
    return agent_chat(msgs, config=cfg)


def stream_completion(body: Dict[str, Any]) -> Iterator[str]:
    """Yield OpenAI-style SSE chunks. Runs the agent (tool calling) then streams the final answer."""
    model = body.get("model", "gemma4-12b-b1")
    try:
        text = _agent_text(body)
    except Exception as exc:
        logger.error("[gateway] stream failed (operation=completions): %s", exc)
        text = f"[error: {exc}]"
    for i in range(0, len(text), 24):  # chunked after the agent loop completes
        yield _chunk(text[i:i + 24], model)
    yield _chunk("", model, finish="stop")
    yield "data: [DONE]\n\n"


def blocking_completion(body: Dict[str, Any]) -> Dict[str, Any]:
    """Return a full OpenAI-style chat-completion object (through the agent tool loop)."""
    model = body.get("model", "gemma4-12b-b1")
    try:
        text = _agent_text(body)
    except Exception as exc:
        text = f"[error: {exc}]"
    return {
        "id": f"chatcmpl-{int(time.time()*1000)}",
        "object": "chat.completion",
        "model": model,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": text},
            "finish_reason": "stop",
        }],
        "usage": {},
    }


# ──── PK2 §U: read-only introspection surfaces for the operator UI ─────────
# The console needs to SHOW the new subsystems (memory, task queue, persona). These are
# small JSON endpoints the UI polls; all read-only except persona POST (the editor).
def _memory_json() -> Dict[str, Any]:
    """The fact registry as JSON rows (text + provenance) for the memory-browser pane."""
    try:
        from harness.skills.memory import _load, _text, verify_registry
        rows = [{"text": _text(e), "src": e.get("src", ""), "ts": e.get("ts", ""),
                 "npos": e.get("npos", 0)} for e in _load()]
        return {"count": len(rows), "facts": rows, "health": verify_registry()}
    except Exception as exc:
        return {"error": str(exc), "count": 0, "facts": []}


def _tasks_json() -> Dict[str, Any]:
    """The agentic work queue (task_loop states) for the task pane."""
    try:
        from harness.control.task_loop import list_tasks
        ts = list_tasks()
        return {"count": len(ts), "tasks": [
            {"id": t.task_id, "goal": t.goal, "status": t.status,
             "steps": len(t.steps), "result": t.result} for t in ts]}
    except Exception as exc:
        return {"error": str(exc), "count": 0, "tasks": []}


def _persona_path() -> str:
    import os
    return os.environ.get("SP_PERSONA_FILE") or os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "persona.md")


def _persona_get() -> Dict[str, Any]:
    try:
        with open(_persona_path(), encoding="utf-8") as f:
            return {"ok": True, "persona": f.read(), "path": _persona_path()}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _spine_json() -> Dict[str, Any]:
    """ADR-008: the recent spine receipts (decide→execute→verify audit trail) for the panel."""
    try:
        from harness.control.spine import get_recent_receipts
        rs = get_recent_receipts(50)
        return {"count": len(rs), "receipts": rs}
    except Exception as exc:
        return {"error": str(exc), "count": 0, "receipts": []}


def _progress_json() -> Dict[str, Any]:
    """HINDSIGHT build progress (phases, migration map, git lanes) for /dashboard.html."""
    try:
        from harness.observability.progress import progress_json
        return progress_json()
    except Exception as exc:
        return {"error": str(exc)}


def _persona_state() -> Dict[str, Any]:
    """The parsed ## Personality state block (voice/mood/traits) — the UI's personality chip."""
    try:
        from harness.personality.persona_file import parse_persona
        with open(_persona_path(), encoding="utf-8") as f:
            _, state = parse_persona(f.read())
        return {"ok": True, "state": state}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "state": {}}


def _persona_set(text: str) -> Dict[str, Any]:
    """The persona editor: write persona.md (voice changes on the next turn). Records a
    provenance memory that the operator edited it (MEM-OKF v2 §M1 / §P1)."""
    try:
        with open(_persona_path(), "w", encoding="utf-8") as f:
            f.write(text)
        try:
            from harness.skills.memory import remember
            remember("The operator edited Shannon-Prime's persona.", source="operator")
        except Exception:
            pass
        return {"ok": True, "bytes": len(text)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ──── Flask app (preferred) ───────────────────────────────────────────────
def create_flask_app():
    from flask import Flask, Response, jsonify, request  # type: ignore

    app = Flask("harness-gateway")

    @app.get("/health")
    def health():
        return jsonify({"ok": True, "daemon": get_client().health()})

    @app.get("/v1/models")
    def models():
        from harness.config import get_config
        m = get_config().get("inference.default_model", "gemma4-12b-b1")
        return jsonify({"object": "list", "data": [{"id": m, "object": "model"}]})

    @app.post("/v1/chat/completions")
    def completions():
        body = request.get_json(force=True)
        if body.get("stream"):
            return Response(stream_completion(body), mimetype="text/event-stream")
        return jsonify(blocking_completion(body))

    @app.get("/v1/memory")
    def memory():
        return jsonify(_memory_json())

    @app.get("/v1/tasks")
    def tasks():
        return jsonify(_tasks_json())

    @app.get("/v1/persona")
    def persona_get():
        return jsonify(_persona_get())

    @app.get("/v1/persona/state")
    def persona_state():
        return jsonify(_persona_state())

    @app.get("/v1/spine")
    def spine():
        return jsonify(_spine_json())

    @app.post("/v1/persona")
    def persona_set():
        return jsonify(_persona_set(request.get_json(force=True).get("persona", "")))

    return app


# ──── Stdlib agent server (zero-dep) ──────────────────────────────────────
# ── HINDSIGHT 2026-07-10: CANONICAL SESSION TRANSCRIPTS ──
# The gateway was stateless: the client echoed its own history back, which NEVER matches
# what the daemon actually saw (spine recall notes + tool rounds are transient) — so the
# turn AFTER any recall/tool turn diverged from the persist-KV committed cache and paid a
# full preamble re-prefill (the live "minutes then [aborted]" pattern). With a session_id,
# the gateway keeps the CANONICAL append-only transcript (notes + tool rounds included)
# and the daemon sees a strict extension every turn = O(new tokens) prefill.
_CHAT_SESSIONS: Dict[str, list] = {}
_CHAT_SESSIONS_MAX = 32


def _session_transcript(body: Dict[str, Any]) -> list:
    """Resolve the canonical message list for this request (mutated in place by the turn)."""
    sid = body.get("session_id")
    msgs = list(body.get("messages", []))
    if not sid:
        return msgs                        # stateless fallback (old behavior)
    canon = _CHAT_SESSIONS.get(sid)
    if canon is None:
        if len(_CHAT_SESSIONS) >= _CHAT_SESSIONS_MAX:
            _CHAT_SESSIONS.pop(next(iter(_CHAT_SESSIONS)))
        canon = msgs                       # first sight: seed from the client's history
        _CHAT_SESSIONS[sid] = canon
    else:
        new_user = next((m for m in reversed(msgs) if m.get("role") == "user"), None)
        if new_user is not None:
            canon.append(dict(new_user))   # append ONLY the new user turn
    return canon


def _voice_status() -> Dict[str, Any]:
    """ADR-KAI4: is the GNA ear loadable, and on which device?"""
    try:
        from harness.voice.service import voice_status
        return voice_status()
    except Exception as exc:
        return {"ear": {"ok": False, "error": str(exc)}}


def _voice_corpus() -> Dict[str, Any]:
    """ADR-KAI4 P1.6: the in-vocab sentences to read aloud for real-voice training."""
    import os as _os
    p = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.dirname(__file__))),
                      "var", "voice", "corpus.jsonl")
    try:
        sents = [json.loads(l)["text"] for l in open(p, encoding="utf-8") if l.strip()]
        # a compact, phonetically varied reading set (prioritize wake + questions)
        import random
        wake = [s for s in sents if "shannon" in s]
        rest = [s for s in sents if "shannon" not in s]
        random.Random(7).shuffle(rest)
        pick = wake[:15] + rest[:85]
        return {"ok": True, "sentences": pick, "total_corpus": len(sents)}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "sentences": []}


def _voice_record_status() -> Dict[str, Any]:
    try:
        from harness.voice.record import record_status
        return record_status()
    except Exception as exc:
        return {"total": 0, "error": str(exc)}


def _native_chat_sse(body: Dict[str, Any]) -> Iterator[bytes]:
    """The console's native /v1/chat: {messages} -> SSE data: {...} -> [DONE], run through the
    streaming AGENT (tool calling).

    ADR-006 §D3 — SSE v2 TYPED EVENTS. The stream now carries, alongside the {delta} token
    events (unchanged, backward-compatible), typed events a product UI can render:
      {"tool": {...}}     a tool call the model made (render as a card)
      {"persona": {...}}  the live personality state (render as a chip)
    A client that only reads `delta` is unaffected (it ignores the others)."""
    from harness.agent import agent_chat_stream
    from harness.inference import InferenceConfig
    import queue as _queue
    import threading as _threading
    # WARM GATE: never race the load-time prefill on the one resident session
    # (that race cost the operator ~5 min/turn and corrupted persist bookkeeping).
    if not _WARM.is_set():
        _t_wait = time.time()
        while not _WARM.wait(4.0):
            yield ("data: " + json.dumps({"hb": int(time.time()), "warming": True}) + "\n\n").encode()
            if time.time() - _t_wait > 900:
                break
        logger.info("[gateway] warm gate released after %.0fs", time.time() - _t_wait)
    # auto_recall PASSTHROUGH (ADR-008 composition gate): default False (the agent uses tools,
    # not the daemon's recall), but a client may arm the daemon-side L5 path per request —
    # required to gate recall∘L5 composition through the gateway.
    # P5a certified-float serving (2026-07-11): profile decode.byteexact=false
    # maps to SP_GATEWAY_BYTEEXACT=0 — serving turns run the float path (cold
    # 2.1k-token float prefill proved coherent; certification = g_float_parity).
    # An EXPLICIT client byteexact always wins (auditable checkbox, gate probes),
    # and the daemon's own default stays byteexact for anything not via here.
    import os as _os0
    _bx = body.get("byteexact")
    if _bx is None and _os0.environ.get("SP_GATEWAY_BYTEEXACT") == "0":
        _bx = False
    cfg = InferenceConfig(temperature=body.get("temperature", 0.6),
                          repetition_penalty=body.get("repetition_penalty", 1.3),
                          eot_bias=body.get("eot_bias", 4.0),
                          max_tokens=body.get("max_tokens", 192),
                          byteexact=_bx,
                          auto_recall=bool(body.get("auto_recall", False)))
    typed = body.get("typed_events", True) is not False   # opt-out for pure-delta clients

    # persona-state event (once, up front) so the UI can show voice/mood/traits for this turn.
    if typed:
        try:
            path = _persona_path()
            with open(path, encoding="utf-8") as f:
                from harness.personality.persona_file import parse_persona
                _, state = parse_persona(f.read())
            if state:
                yield ("data: " + json.dumps({"persona": state}) + "\n\n").encode()
        except Exception:
            pass

    # The agent's on_tool callback fires on a worker thread; funnel tool events through a queue
    # so they interleave with the streamed answer tokens on the SSE wire.
    evq: "_queue.Queue" = _queue.Queue()

    def on_tool(name, args, result):
        evq.put({"tool": {"name": name, "args": args, "result": str(result)[:600]}})

    # ── ADR-008 PRE-TURN SPINE (both default-off; null floor = wave-3 behavior) ──
    #  SP_SPINE_RECALL=1  : ranked memory recall → inject the facts as a system note +
    #                       emit a typed {"recall": facts} event (observable, gateable).
    #  SP_SPINE_TOOLSET=1 : adaptive tool tier — the turn advertises the RIGHT ≤6 tools
    #                       (coding/memory/core) instead of one fixed set.
    import os as _os
    msgs = _session_transcript(body)
    turn_tools = None
    turn_extra = None
    user_text = next((m.get("content", "") for m in reversed(msgs)
                      if m.get("role") == "user"), "")
    want_recall = _os.environ.get("SP_SPINE_RECALL", "0") == "1"
    want_toolset = _os.environ.get("SP_SPINE_TOOLSET", "0") == "1"
    # HINDSIGHT recall hygiene (live console): spine recall fired on greetings/acks and
    # surfaced junk episodes ("hi there!" x3) into the note. QONLY-style gate: only
    # inject recall on turns that actually ASK something (mirrors the daemon L5 QONLY).
    _t = (user_text or "").strip().lower()
    _first = _t.split()[0] if _t.split() else ""
    _looks_q = _t.endswith("?") or _first in {
        "what", "who", "where", "when", "why", "how", "which", "do", "does",
        "did", "is", "are", "am", "can", "could", "remind", "recall", "tell"}
    if want_recall and not _looks_q:
        want_recall = False
    # ── HINDSIGHT 2026-07-10: PROFILE-SELECTED RECALL AUTHORITY ──
    # SP_GATEWAY_AUTHORITY=spine (the kairos agent profile) makes the HARNESS the one
    # recall authority and refuses the client's auto_recall passthrough. Why: the
    # daemon-L5 delivery re-prefills an AUGMENTED prompt and then CLEARS the persist
    # committed cache (routes.rs recalled-turn clear), so with the console checkbox on,
    # EVERY interrogative turn cost ~2 full preamble prefills and the following turn a
    # third — the live "minutes then [aborted]" pattern. Spine recall injects its note
    # BEFORE the new user message, so the prompt stays a STRICT EXTENSION of the
    # committed cache = O(suffix) prefill. Default 'l5' keeps the old passthrough
    # (G-PK2-RECALL-L5-COMPOSE behavior) byte-for-byte.
    if _os.environ.get("SP_GATEWAY_AUTHORITY", "l5").lower() == "spine" and cfg.auto_recall:
        cfg.auto_recall = False
        if typed:
            yield ("data: " + json.dumps({"authority": "spine"}) + "\n\n").encode()
    # ONE-AUTHORITY GUARD (G-PK2-RECALL-L5-COMPOSE, 2026-07-08): free composition of BOTH
    # recall authorities is REFUTED on the metal — with L5 armed, its systemecho SYSTEM
    # delivery overrides the harness note, and an L5 selection cross-pick surfaces to the
    # user ("favorite color?" -> "Human blood is green"). Rule made structural: when the
    # request arms the daemon's recall (auto_recall=true => L5 is the authority), the spine
    # recall auto-disarms. Receipt: the {"authority":"L5"} event.
    if cfg.auto_recall and want_recall:
        want_recall = False
        if typed:
            yield ("data: " + json.dumps({"authority": "L5"}) + "\n\n").encode()
    if (want_recall or want_toolset) and user_text:
        try:
            from harness.control.spine import run_pre_turn, toolset_for
            _, decisions = run_pre_turn(user_text, recall=want_recall, toolset=want_toolset)
            for dec in decisions:
                if dec.kind == "decline_recall":
                    # P1b-2b MEM-OKF attr-gate (private-secret, absent attribute):
                    # the fixed decline streams with ZERO model inference — the
                    # turn never reaches the daemon, so confabulation/leak of the
                    # secret's other attributes is impossible by construction.
                    msg_text = dec.payload.get("message", "")
                    if typed:
                        yield ("data: " + json.dumps({"recall_decline": True}) + "\n\n").encode()
                    yield ("data: " + json.dumps({"delta": msg_text}) + "\n\n").encode()
                    msgs.append({"role": "assistant", "content": msg_text})
                    yield b"data: [DONE]\n\n"
                    return
                if dec.kind == "inject_recall":
                    facts = dec.payload.get("facts", [])
                    if facts:
                        note = ("Relevant facts from your long-term memory (use them faithfully; "
                                "never contradict them): " + " | ".join(facts))
                        # inject as a SYSTEM note right before the last user message —
                        # IN PLACE, so the canonical session transcript keeps it (the
                        # daemon's persist cache and the next turn's prompt stay aligned).
                        msgs.insert(len(msgs) - 1, {"role": "system", "content": note})
                        if typed:
                            yield ("data: " + json.dumps({"recall": facts}) + "\n\n").encode()
                elif dec.kind == "select_toolset":
                    core, extra = toolset_for(dec.payload.get("tier", "core"))
                    if core:
                        turn_tools, turn_extra = core, extra
                        if typed:
                            yield ("data: " + json.dumps(
                                {"toolset": dec.payload.get("tier")}) + "\n\n").encode()
        except Exception as exc:
            logger.warning("[gateway] pre-turn spine skipped: %s", exc)

    # PHASE TIMING (live-play 2026-07-11: 40 s turns for 3-token answers — the
    # cost is NOT decode. Name every phase so the thief cannot hide again.)
    _t_phase = time.time()
    _t_start = _t_phase

    def _phase(name: str) -> None:
        nonlocal _t_phase
        now = time.time()
        logger.info("[gateway] phase %-14s %.1fs", name, now - _t_phase)
        _t_phase = now

    _phase("pre-turn")

    reply_parts: list = []

    def _run():
        try:
            kw = {"config": cfg, "on_tool": on_tool, "mutate_messages": True}
            if turn_tools is not None:
                kw["tools"] = turn_tools
            for delta in agent_chat_stream(msgs, **kw):
                reply_parts.append(delta)
                evq.put({"delta": delta})
            # close the canonical transcript with the final answer (session mode keeps it;
            # stateless mode discards the local list — harmless either way).
            final = "".join(reply_parts).strip()
            if final:
                msgs.append({"role": "assistant", "content": final})
        except Exception as exc:
            logger.error("[gateway] native chat failed: %s", exc)
            evq.put({"delta": f"[error: {exc}]"})
        evq.put(None)   # sentinel

    t = _threading.Thread(target=_run, daemon=True)
    t.start()
    while True:
        # ADR-006 §D3 heartbeat: during a long prefill nothing streams for minutes and the UI
        # looks dead. Emit {"hb": ts} keep-alives while we wait (typed clients show a spinner;
        # pure-delta clients never see them).
        try:
            ev = evq.get(timeout=5.0)
        except _queue.Empty:
            if typed:
                yield ("data: " + json.dumps({"hb": int(time.time())}) + "\n\n").encode()
            continue
        if ev is None:
            break
        if not typed and "delta" not in ev:
            continue
        yield ("data: " + json.dumps(ev) + "\n\n").encode()
    # ADR-007 post-turn SPINE: persona tags in the reply are persisted (decide → execute →
    # VERIFY per ADR-006) and, on a verified shift, the new state is emitted as a final
    # persona event so the UI chip updates live.
    if typed:
        try:
            from harness.control.spine import run_post_turn
            msgs = body.get("messages", [])
            user_text = next((m.get("content", "") for m in reversed(msgs)
                              if m.get("role") == "user"), "")
            receipts = run_post_turn(user_text, "".join(reply_parts))
            if any(r.kind == "persona_shift" and r.ok and r.verified is not False for r in receipts):
                from harness.personality.persona_file import parse_persona
                with open(_persona_path(), encoding="utf-8") as f:
                    _, state = parse_persona(f.read())
                yield ("data: " + json.dumps({"persona": state, "changed": True}) + "\n\n").encode()
        except Exception as exc:
            logger.warning("[gateway] post-turn spine skipped: %s", exc)
        # ADR-005 flywheel: flush spine receipts (pre-turn recall/toolset + post-turn persona)
        # to the durable telemetry-okf tier. Cheap (content-addressed dedup), best-effort.
        try:
            from harness.control.spine import persist_receipts
            persist_receipts()
        except Exception:
            pass
    yield b"data: [DONE]\n\n"


# ── WARM GATE (operator, 2026-07-11 midnight) ────────────────────────────────
# The prewarm used to run on a BACKGROUND thread while the gateway already
# served traffic: the operator's first message RACED it on the one resident
# session, the persist guard missed (pos != committed), and BOTH paid a full
# ~5-minute cold prefill. "Why is prefill run on the first message and not on
# load?" — exactly. It is a LOAD-time step now:
#   * chat requests WAIT on this event (heartbeats keep the UI alive), so a
#     user turn can never race or interleave with the prefill;
#   * /health reports {"warm": bool} so serve.py can hold "ready" until hot.
import threading as _thr  # module-level (the chat handler imports its own alias locally)
_WARM = _thr.Event()


def warm_state() -> dict:
    return {"warm": _WARM.is_set()}


def _await_warm(timeout: float = 900.0) -> bool:
    """Block until the preamble is hot. Chat turns call this BEFORE touching the
    daemon; the alternative (racing the prewarm) costs minutes and corrupts the
    persist bookkeeping."""
    if _WARM.is_set():
        return True
    logger.info("[gateway] turn is WAITING for the load-time prefill (no racing the cache)")
    return _WARM.wait(timeout)


def _prewarm() -> None:
    """Pre-warm the static persona+tools prefix into the daemon's persist cache so the
    FIRST real user turn reuses it (persist longest-common-prefix) instead of paying the
    O(n) cold prefill live. Runs on a thread but GATES all chat traffic via _WARM."""
    import threading
    import time

    def _go():
        try:
            from harness.agent import core_tools, extra_tools, load_agent_system
            from harness.mcp.tools import build_tool_system
            from harness.inference import InferenceConfig
            from harness.inference.client import get_client
            client = get_client()
            for _ in range(120):                       # wait up to ~120s for the daemon to be up
                if client.health():
                    break
                time.sleep(1)
            system_content, _ = build_tool_system(core_tools(), extra_tools(),
                                                  system_prefix=load_agent_system())
            msgs = [{"role": "system", "content": system_content},
                    {"role": "user", "content": "hi"}]
            # The preamble KV is the thing whose DETAIL matters (persona, hardware,
            # tool names). It is ALWAYS prefilled byte-exact, whatever the serving
            # regime — float-prefilling it is what produced "Shannon-15 / RTX 3067".
            cfg = InferenceConfig(temperature=0.6, repetition_penalty=1.3, eot_bias=4.0,
                                  max_tokens=1, auto_recall=False, byteexact=True)
            t0 = time.time()
            logger.info("[gateway] LOAD-TIME prefill of the persona+tools prefix "
                        "(chat traffic is gated until this completes)...")
            client.chat(messages=msgs, config=cfg)
            logger.info("[gateway] prefill complete in %.0fs; prefix is HOT — turns are fast now.",
                        time.time() - t0)
        except Exception as exc:
            logger.warning("[gateway] pre-warm failed (non-fatal; first turn pays the prefill): %s", exc)
        finally:
            _WARM.set()   # ALWAYS release the gate: a failed prewarm must not wedge the gateway

    threading.Thread(target=_go, daemon=True).start()


def _run_stdlib(host: str, port: int) -> None:
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    def _cors(h):
        h.send_header("Access-Control-Allow-Origin", "*")
        h.send_header("Access-Control-Allow-Headers", "Content-Type")
        h.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):  # quiet
            pass

        def do_OPTIONS(self):  # noqa: N802  CORS preflight
            self.send_response(204); _cors(self); self.end_headers()

        def _body(self):
            length = int(self.headers.get("Content-Length", 0))
            return json.loads(self.rfile.read(length) or b"{}")

        def do_POST(self):  # noqa: N802
            if self.path == "/v1/chat":  # console-native, agent-driven, streaming
                body = self._body()
                self.send_response(200); _cors(self)
                self.send_header("Content-Type", "text/event-stream"); self.end_headers()
                for chunk in _native_chat_sse(body):
                    self.wfile.write(chunk); self.wfile.flush()
            elif self.path == "/v1/voice/record":  # ADR-KAI4 P1.6: save a real training sample
                body = self._body()
                try:
                    from harness.voice.record import save_recording
                    res = save_recording(body.get("text", ""), body.get("audio_b64", ""))
                except Exception as exc:
                    res = {"ok": False, "error": str(exc)}
                payload = json.dumps(res).encode()
                self.send_response(200); _cors(self)
                self.send_header("Content-Type", "application/json"); self.end_headers()
                self.wfile.write(payload)
            elif self.path == "/v1/voice":  # ADR-KAI4 P0: one VAD-segmented utterance
                body = self._body()
                self.send_response(200); _cors(self)
                self.send_header("Content-Type", "text/event-stream"); self.end_headers()
                try:
                    from harness.voice.service import voice_turn
                    transcript = _session_transcript({"session_id": body.get("session_id"),
                                                      "messages": body.get("messages", [])})
                    for chunk in voice_turn(body, transcript):
                        self.wfile.write(chunk); self.wfile.flush()
                except Exception as exc:
                    self.wfile.write(("data: " + json.dumps(
                        {"error": f"voice: {exc}"}) + "\n\ndata: [DONE]\n\n").encode())
                    self.wfile.flush()
            elif self.path == "/v1/persona":  # PK2 §P1 persona editor (write persona.md)
                body = self._body()
                payload = json.dumps(_persona_set(body.get("persona", ""))).encode()
                self.send_response(200); _cors(self)
                self.send_header("Content-Type", "application/json"); self.end_headers()
                self.wfile.write(payload)
            elif self.path == "/v1/chat/completions":  # OpenAI surface (also agent-driven)
                body = self._body()
                if body.get("stream"):
                    self.send_response(200); _cors(self)
                    self.send_header("Content-Type", "text/event-stream"); self.end_headers()
                    for chunk in stream_completion(body):
                        self.wfile.write(chunk.encode()); self.wfile.flush()
                else:
                    payload = json.dumps(blocking_completion(body)).encode()
                    self.send_response(200); _cors(self)
                    self.send_header("Content-Type", "application/json"); self.end_headers()
                    self.wfile.write(payload)
            else:
                self.send_error(404)

        def do_GET(self):  # noqa: N802
            _json_routes = {
                "/health": lambda: {"ok": True, "agent": True, "warm": _WARM.is_set(),
                                    "daemon": get_client().health()},
                "/v1/voice/status": _voice_status,   # ADR-KAI4: ear device/artifacts state
                "/v1/voice/corpus": _voice_corpus,   # ADR-KAI4 P1.6: sentences to read for training
                "/v1/voice/record/status": _voice_record_status,
                "/v1/memory": _memory_json,      # PK2 §U1 memory-browser data
                "/v1/tasks": _tasks_json,        # PK2 §U1 task-queue data
                "/v1/persona": _persona_get,     # PK2 §P1 persona editor (load)
                "/v1/persona/state": _persona_state,  # ADR-006 personality chip
                "/v1/spine": _spine_json,        # ADR-008 receipts audit trail
                "/v1/progress": _progress_json,  # HINDSIGHT dashboard data (phases/migration/git)
            }
            fn = _json_routes.get(self.path)
            if fn is not None:
                self.send_response(200); _cors(self)
                self.send_header("Content-Type", "application/json"); self.end_headers()
                self.wfile.write(json.dumps(fn()).encode())
            elif self._serve_console_static():
                pass
            else:
                self.send_error(404)

        # ── console statics on the gateway (dashboard lives here; daemon-independent) ──
        _STATIC_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css",
                         ".js": "application/javascript", ".svg": "image/svg+xml",
                         ".json": "application/json"}

        def _serve_console_static(self) -> bool:
            import os as _os
            path = self.path.split("?", 1)[0]
            if path == "/":
                path = "/dashboard.html"
            name = path.lstrip("/")
            # single flat filename only — no traversal, no subdirs
            if not name or "/" in name or "\\" in name or name.startswith("."):
                return False
            ext = _os.path.splitext(name)[1].lower()
            ctype = self._STATIC_TYPES.get(ext)
            if ctype is None:
                return False
            root = _os.path.join(_os.path.dirname(_os.path.dirname(
                _os.path.dirname(_os.path.abspath(__file__)))), "console")
            fp = _os.path.join(root, name)
            if not _os.path.isfile(fp):
                return False
            with open(fp, "rb") as f:
                data = f.read()
            self.send_response(200); _cors(self)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return True

    logger.info("[gateway] stdlib AGENT server on %s:%d (operation=serve)", host, port)
    # Pre-warm is OPT-IN (SP_GATEWAY_PREWARM=1) until the byteexact-on prefill is fast OR the LCP
    # rewind is proven byte-exact: with byteexact required, a pre-warm grinds the GPU ~5 min.
    import os as _os
    if _os.environ.get("SP_GATEWAY_PREWARM") == "1":
        _prewarm()  # background: hydrate the persona+tools prefix into the persist cache
    ThreadingHTTPServer((host, port), Handler).serve_forever()


def run(host: str = "127.0.0.1", port: int = 8800) -> None:
    """Start the agent gateway (zero-dep stdlib server with native /v1/chat + OpenAI surface)."""
    _run_stdlib(host, port)


if __name__ == "__main__":
    run()
