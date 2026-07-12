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


def _session_of(body: Dict[str, Any]) -> str:
    """THE session key. One function, because there were four sites and two rules:

        _agent_text / _kairos_after_turn :  session | session_id | default
        _native_chat_sse                 :  session | chat_id    | default

    ...and console.html sends `session_id`. So on the console path — the one a human
    actually uses — kairos filed her unprompted message under "default" while the console
    would have polled the outbox for its own uuid. She would have spoken, correctly, into a
    session nobody was listening to, and every symptom would have said "she never spoke".

    A key derived in more than one place is a key that disagrees with itself."""
    for k in ("session", "session_id", "chat_id"):
        v = body.get(k)
        if v:
            return str(v)
    return "default"


def _agent_text(body: Dict[str, Any]) -> str:
    """Run the request through the AGENT loop (Gemma tool calling) unless tools are disabled.
    This is the unification: the model CALLS its tools (memory/system/web) in the chat, instead
    of a passthrough with no tool calling. Set body['tools']=false (or 'use_tools':false) to skip."""
    use_tools = body.get("tools", body.get("use_tools", True)) is not False
    msgs = body.get("messages", [])
    # ROLEPLAY: may inject the scene's system prompt + this turn's director note, or return
    # the scenario OFFER outright. Wired at BOTH entry points (here and _native_chat_sse) —
    # a hook wired into one of two paths has been the single most reliable bug in this
    # system, four times over in one day.
    _human = _arm_turn(msgs)     # what he TYPED — taken before the tool loop touches msgs
    _offer = _roleplay_pre_turn(body, msgs)
    if _offer:
        return _offer
    if not use_tools:
        # ARM THE SELF-REPEAT BAN HERE TOO. It was armed only inside agent_chat_stream —
        # so this tools=False branch (which goes straight to the client) had no guard, and
        # the very gate written to prove the fix ran down the unguarded path and "passed"
        # on temperature luck. Same hole, third variant, one day. Arm it at EVERY path that
        # reaches the model, not at the one you happened to be looking at.
        from harness.agent import _arm_self_repeat_ban
        _cfg = _to_config(body)
        _arm_self_repeat_ban(_cfg, msgs)
        text = get_client().chat(messages=msgs, config=_cfg).text
        text = _repeat_guard(body, msgs, text, _cfg)
        _capture_after_turn(_human)
        _kairos_after_turn(body, text)
        return text
    from harness.agent import agent_chat
    from harness.inference import InferenceConfig
    cfg = InferenceConfig(
        temperature=body.get("temperature", 0.0),
        max_tokens=body.get("max_tokens", 256),
        auto_recall=False,  # the model uses tools, not the daemon's heuristic recall
    )
    text = agent_chat(msgs, config=cfg)
    text = _repeat_guard(body, msgs, text, cfg)
    _capture_after_turn(_human)
    _kairos_after_turn(body, text)
    return text


def _human_turn(msgs: list) -> str:
    """What the HUMAN actually typed this turn — and nothing else.

    THE FEEDBACK LOOP (2026-07-12). Capture used to take "the last message with role=user".
    But agent_chat_stream runs with mutate_messages=True on the console path (the canonical
    transcript must match what the daemon saw, for persist-KV strict extension), and the
    Gemma tool protocol feeds a tool RESULT back as a role=user message. So after any tool
    call, "the last user message" is HER OWN TOOL OUTPUT. The store filled with things like

        remember -> stored: I am a woman        <- her tool's receipt, filed as a fact about HIM

    She was eating her own exhaust: a write produced an output, the output looked like the
    user talking, and the output got written. Round and round.

    A protocol role is not a speaker. `role=user` means "this slot in the template", not
    "a human said this". The only text a human ever typed is the last user message AS IT
    ARRIVED — before the model ran and before the tool loop appended anything — so we take
    it at the top of the turn and hold it. Capture can then never see anything else."""
    return next((m.get("content", "") for m in reversed(msgs or [])
                 if m.get("role") == "user"), "")


def _arm_turn(msgs: list) -> str:
    """Hand the memory lane HIS ACTUAL WORDS for this turn.

    recall() needs them to resolve ownership. Asked "what is YOUR name?" she calls
    recall(query="What is my name?") — she rewrites the question into her own first person.
    Asked "what is MY name?" she calls recall(query="What is my name?"): the identical
    string. Two opposite questions, one query, so her paraphrase cannot say who is being
    asked after. His sentence can, and always could — in it, "my" is Knack and "your" is
    Shannon. Resolve the pronoun where it was uttered.

    Returns the human's turn so the caller can hand the SAME text to capture at the end —
    taken here, at the top, before the tool loop can append anything that merely wears
    role=user."""
    human = _human_turn(msgs)
    try:
        from harness.skills import memory as M
        M.set_question(human)
        M.set_author("user")
    except Exception:
        pass
    return human


def _capture_after_turn(human_text: str) -> None:
    """THE CAPTURE LANE (2026-07-12). Pull the durable facts out of the user's turn — and
    only those.

    Takes the human's text as an ARGUMENT, captured at the top of the turn by _arm_turn().
    It used to re-derive it from the message list, and by the end of a turn that list has
    tool outputs in it wearing role=user — so it captured her own tool receipts as facts
    about him. A function that goes looking for its input can be handed the wrong one; a
    function that is given it cannot.

    WHAT THIS REPLACES. The daemon (routes.rs, SP_B4_NIGHTSHIFT) stored `raw_user` — the
    WHOLE user turn, verbatim, as one episode — if it passed a word count and mentioned a
    person. Given a turn it had to keep all of it or none of it, so it kept all of it. One
    real conversation put 17 rows in, including:

        "yes, we lose lips, sink ships."
        "you are cool af! I really like you!"
        "well, we make do. you're doing alright for such a constrained system"

    and buried the actual facts (the esp32 sensors, the 2060 and the NUC, the PCs running
    24/7) inside turns that were mostly banter.

    Two authorities decided what a memory was: the daemon's word-count-and-a-pronoun, and
    the harness's lifecycle rules — which had the dedupe, the supersede, the two stores and
    the durability test. The daemon won every time, because it wrote first. An invariant
    guarded in one of two paths is not guarded; this codebase has now learned that three
    times. So the daemon stops writing (profiles: memory.growth = false) and capture happens
    HERE, once, through the same door as everything else: split the turn into sentences,
    keep the durable ones, and put each through remember() — which dedupes, supersedes, and
    respects the identity firewall."""
    try:
        if not (human_text or "").strip():
            return
        # BELT AND BRACES: even given the right text, never ingest a tool round.
        if "```tool_output" in human_text or "```tool_code" in human_text:
            return
        from harness.skills import lifecycle as lc
        from harness.skills import memory as M
        facts = lc.extract_facts(human_text)
        if not facts:
            return
        M.set_author("user")
        for f in facts[:4]:                       # a turn that yields 5+ facts is a paste
            try:
                M.remember(f, source="user turn")
            except Exception:
                pass
    except Exception:
        pass


def _repeat_guard(body: Dict[str, Any], msgs: list, text: str, cfg) -> str:
    """She may not say the same thing twice. See harness/quality/repeat_guard.py — the
    operator caught her returning three BYTE-IDENTICAL replies to three different
    messages. Narrow by design: this forbids repeating HER OWN LAST MESSAGE, and does
    nothing to her ability to quote him, a memory, a tool result, or a number (all of
    which the old no_repeat_ngram ban forbade, which is why it had to go)."""
    try:
        from harness.quality.repeat_guard import guard
        prev = next((m.get("content", "") for m in reversed(msgs)
                     if m.get("role") == "assistant"), "")
        if not prev:
            return text

        def _reroll(nudge: str) -> str:
            from harness.agent import agent_chat_stream
            from harness.inference import InferenceConfig as _IC
            hist = list(msgs) + [{"role": "system", "content": nudge}]
            return "".join(agent_chat_stream(
                hist, config=_IC(max_tokens=cfg.max_tokens, temperature=0.85,
                                 auto_recall=False), tools=[]))

        out, note = guard(text, prev, _reroll)
        if note:
            logger.warning("[repeat-guard] %s", note)
        return out
    except Exception as exc:
        logger.warning("[repeat-guard] skipped: %s", exc)
        return text


def _roleplay_pre_turn(body: Dict[str, Any], msgs: list) -> Optional[str]:
    """ROLEPLAY MODE. Returns a canned reply to stream instead of running the model (the
    scenario OFFER), or None to continue normally — after possibly injecting the scene's
    system prompt + this turn's DIRECTOR NOTE into `msgs`.

    The director note is recomputed from live scene state EVERY turn (the room, the rung,
    how many beats we have spent there, whether the scene is idling). That is the
    anti-drift mechanism: the model is never more than one turn away from being told again
    who it is and where it is standing. A system prompt alone drifts out in four turns."""
    try:
        from harness.roleplay import engine as rp
        from harness.tuning import registry as tune
        if not tune.get("roleplay.enabled"):
            return None

        session = _session_of(body)
        user = next((m.get("content", "") for m in reversed(msgs)
                     if m.get("role") == "user"), "")
        scene = rp.active(session)

        # OUT — checked first, always. A stop is a stop, at any heat, no exceptions.
        if scene and rp.wants_out(user):
            rp.leave(session)
            return None            # she answers as herself, normally, from here on

        # IN
        if not scene:
            pending = rp.is_pending(session)
            # She offered a menu last turn — so THIS turn is his pick. Without this state she
            # proposes and then cannot hear the answer ("the penthouse one" matches no ENTER
            # keyword, falls through to normal chat, and no scene ever starts).
            if not pending and not rp.wants_in(user):
                return None
            chosen = rp.pick_from(user)
            if not chosen:
                if pending:
                    rp.clear_pending(session)   # he changed his mind; drop it, do not nag
                    return None
                rp.mark_offered(session)
                return rp.offer(user)           # she OFFERS; a good host proposes
            rp.clear_pending(session)
            scene = rp.enter(session, chosen.id)
            if not scene:
                return None
            logger.info("[roleplay] ENTER %s (%s)", scene.scenario.id, scene.scenario.theme)

        # already in a scene, or just entered: compose the standing prompt + the note
        cap = int(tune.get("roleplay.max_heat"))
        note = rp.director_note(scene, user, cap)
        if note.startswith("SCENE BROKEN"):
            rp.leave(session)
            return None

        # TOOLS OFF INSIDE A SCENE. She is a person in a room, not an assistant with a
        # toolbox — a character does not call web_search mid-kiss. Live symptom: the first
        # scene turn HUNG, because the agent loop kept trying to take tool rounds against a
        # system prompt that gives it nothing to do. It is an immersion break and a
        # performance bug at the same time, and both are fixed by the same line.
        body["tools"] = False
        msgs.insert(0, {"role": "system", "content": rp.system_prompt(scene, cap)})
        if note:
            msgs.insert(len(msgs) - 1, {"role": "system", "content": note})
        logger.info("[roleplay] %s heat=%s beats=%d%s", scene.scenario.id,
                    scene.heat.name, scene.beats, " (hook fired)" if "IDLING" in note else "")
        return None
    except Exception as exc:
        logger.warning("[roleplay] skipped: %s", exc)
        return None


def _kairos_after_turn(body: Dict[str, Any], reply: str) -> None:
    """KAIROS on the OpenAI-compatible path.

    The first cut of this hooked ONLY _native_chat_sse (the console's /v1/chat) — and the
    live gate, which speaks /v1/chat/completions, produced ZERO kairos activity: the
    daemon was faithfully emitting the impulse and the gateway simply never looked. Two
    entry points, one hook, so the other became a hole. That is the same shape as the two
    recall authorities, the two admission paths, and the two write paths. An invariant
    wired into one of N entry points is wired into none of them.

    _agent_text() is where BOTH OpenAI paths (blocking + streaming) converge, so the hook
    goes here and cannot be bypassed by choosing a different endpoint."""
    try:
        from harness.kairos import scheduler as ks
        reply = (reply or "").strip()
        if not reply:
            return
        session = _session_of(body)

        def _continue(nudge: str) -> str:
            from harness.agent import agent_chat_stream, _arm_self_repeat_ban
            from harness.inference import InferenceConfig as _IC
            hist = list(body.get("messages", []))
            hist.append({"role": "assistant", "content": reply})
            hist.append({"role": "system", "content": nudge})
            _cfg = _IC(max_tokens=120, temperature=0.0, auto_recall=False)
            # ARM THE SELF-REPEAT BAN ON THE CONTINUATION TOO. Her first live continuation
            # resumed correctly ("...by the occasional wave crest that breaks into white
            # foam") and then re-covered ground she had already said — "the air is thick
            # with moisture, the ocean below a vast expanse". Of course it did: a
            # continuation is conditioned on a reply that was CUT OFF mid-sentence, which
            # is the strongest possible pull back into the words it just produced. This is
            # the one turn in the system most likely to repeat itself, and it was the one
            # turn with no guard. Fourth variant of the same hole.
            _arm_self_repeat_ban(_cfg, hist)
            return "".join(agent_chat_stream(hist, config=_cfg, tools=[]))

        ks.on_reply(session, reply, get_client().last_kairos, _continue)
    except Exception as exc:
        logger.warning("[gateway] kairos skipped: %s", exc)


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
    """The fact registry as JSON rows for the operator's memory pane.

    It used to return only {text, src, ts, npos} — no `name`, so the panel could SHOW a
    memory but never RETIRE one (forget() keys on name), and no `speaker`/`mem_class`/
    `lifecycle`, so a SELF memory looked exactly like one of Knack's and a tombstoned row
    looked live. A browser you cannot act from is a report, not a panel."""
    try:
        from harness.skills import lifecycle as lc
        from harness.skills.memory import _load, _text, verify_registry
        rows = []
        for e in _load():
            rows.append({
                "name": e.get("name", ""),
                "text": lc.strip_prefix(_text(e)),        # drop the legacy "The user said: "
                "speaker": e.get("speaker", ""),
                "mem_class": e.get("mem_class", ""),
                "lifecycle": e.get("lifecycle", 0),
                "src": e.get("src", ""),
                "ts": e.get("ts", ""),
            })
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

    # ── TUNING (2026-07-12) ───────────────────────────────────────────────────
    # One generic surface over the declarative knob registry. The operator UI renders
    # whatever it finds here, so a knob added to harness/tuning/registry.py appears in
    # the panel with its bounds, help and PROVENANCE (measured vs chosen) — no UI edit,
    # no endpoint edit. That is the point: a settings page that has to be hand-updated
    # rots, and this system's recurring failure is capability that exists but is not
    # reachable.
    @app.get("/v1/tuning")
    def tuning_get():
        from harness.tuning import registry as tune
        return jsonify(tune.schema())

    @app.post("/v1/tuning")
    def tuning_set():
        from harness.tuning import registry as tune
        body = request.get_json(force=True) or {}
        try:
            tune.set_many(body.get("values", {}))
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        return jsonify({"ok": True, **tune.schema()})

    @app.post("/v1/tuning/reset")
    def tuning_reset():
        from harness.tuning import registry as tune
        key = (request.get_json(force=True) or {}).get("key", "")
        tune.reset(key)
        return jsonify({"ok": True, **tune.schema()})

    # ── KAIROS: what she has decided to say, unprompted ───────────────────────
    @app.get("/v1/kairos/outbox")
    def kairos_outbox():
        from harness.kairos import scheduler as ks
        s = request.args.get("session", "default")
        return jsonify({"messages": ks.drain(s), "state": ks.peek_state(s)})

    @app.get("/v1/kairos/state")
    def kairos_state():
        from harness.kairos import scheduler as ks
        return jsonify(ks.peek_state(request.args.get("session", "default")))

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

    # ROLEPLAY (console path). Same hook as the OpenAI path — a scenario OFFER short-circuits
    # the model entirely; otherwise the scene's system prompt + this turn's DIRECTOR NOTE
    # are injected into the message list before the agent runs.
    # THIS is the path that mutates msgs (mutate_messages=True keeps the canonical
    # transcript the daemon saw), so this is where "the last user message" turns into a
    # tool receipt by the end of the turn. Take his words NOW.
    _human = _arm_turn(msgs)
    try:
        _rp_offer = _roleplay_pre_turn(body, msgs)
        if _rp_offer:
            yield ("data: " + json.dumps({"delta": _rp_offer}) + "\n\n").encode()
            msgs.append({"role": "assistant", "content": _rp_offer})
            yield b"data: [DONE]\n\n"
            return
    except Exception as exc:
        logger.warning("[gateway] roleplay pre-turn skipped: %s", exc)

    _phase("pre-turn")

    # KAIROS: HE spoke. Her chain resets, and if she was sitting on a pending
    # continuation she yields it — he gets the floor. That is what keeps this a
    # conversation instead of two monologues interleaving.
    try:
        from harness.kairos import scheduler as _ks0
        _ks0.on_user_turn(_session_of(body))
    except Exception:
        pass

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
    # CAPTURE: the console path writes memories too. Wiring a hook into one of the two
    # entry points and calling it done is the single most repeated bug in this system —
    # kairos, the repeat-guard and roleplay each shipped half-wired first. Not this one.
    _capture_after_turn(_human)
    # ── KAIROS: the turn is over. Does she have more to say? ───────────────────────
    # Almost always: no. The policy (harness/kairos/impulse.py) is SILENT by default and
    # every bound is checked before the impulse is even consulted — she cannot chain, she
    # never speaks over a question she asked him, and a continuation that turns out to be
    # a greeting or a restatement is dropped before he ever sees it.
    #
    # The impulse itself is not a heuristic: it is the RAW stop-vs-continue logit margin
    # from the forward, which the engine computed anyway. Calibrated (tools/kairos/
    # calibrate.py): finished turns sit at +2.0, guillotined turns at -14.8.
    try:
        from harness.kairos import scheduler as _ks
        _final = "".join(reply_parts).strip()
        _session = _session_of(body)
        if _final:
            def _continue(nudge: str) -> str:
                """Run ONE more turn with the nudge appended. She is continuing herself,
                so the nudge is a SYSTEM aside — not a new user message. (If it were a
                user message the transcript would grow a turn the operator never typed,
                and the next prefill would diverge from the persist cache.)"""
                from harness.agent import agent_chat_stream, _arm_self_repeat_ban
                from harness.inference import InferenceConfig
                hist = list(body.get("messages", []))
                hist.append({"role": "assistant", "content": _final})
                hist.append({"role": "system", "content": nudge})
                # A CONTINUATION MUST NOT DO RECALL. This config left auto_recall at its
                # default, so the daemon injected memories into her continuation — and her
                # first live one on this path came out as
                #     "From the record: oh no, we just track their comings and goings..."
                # She was finishing a sentence about a thunderstorm. Recall answers a
                # QUESTION; there is no question here, only her own severed clause, so a
                # memory arriving now can only derail it. (The OpenAI path already set
                # this. Two paths, one setting, and the one a human uses was the one that
                # missed it — the same shape as every other bug this week.)
                ccfg = InferenceConfig(max_tokens=120, temperature=cfg.temperature,
                                       auto_recall=False)
                _arm_self_repeat_ban(ccfg, hist)
                return "".join(agent_chat_stream(hist, config=ccfg, tools=[]))

            _ks.on_reply(_session, _final, get_client().last_kairos, _continue)
    except Exception as exc:
        logger.warning("[gateway] kairos skipped: %s", exc)

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
            # ── OPERATOR PANEL (2026-07-12) ───────────────────────────────────────
            # Moods/traits, memory add/retire, and the maintenance passes. Every one does
            # REAL work and returns a RECEIPT of what changed — a maintenance button that
            # says "done!" and cannot tell you what it did is how a store rots quietly, and
            # this one already rotted once (487 rows, 375 of them ASR test corpus).
            # Nothing here deletes: cleanup QUARANTINES, compaction TOMBSTONES.
            elif self.path.startswith("/v1/maintenance/") or self.path.startswith("/v1/memory/") \
                    or self.path.startswith("/v1/persona/set"):
                body = self._body()
                code, res = 200, {}
                try:
                    from harness.maintenance import ops
                    p = self.path
                    if p == "/v1/maintenance/compact":
                        res = ops.compact()
                    elif p == "/v1/maintenance/cleanup":
                        res = ops.cleanup()
                    elif p == "/v1/maintenance/nightshift":
                        res = ops.nightshift()
                    elif p == "/v1/maintenance/stats":
                        res = ops.stats()
                    elif p == "/v1/memory/add":
                        res = ops.add(body.get("fact", ""), body.get("speaker", "user"))
                    elif p == "/v1/memory/forget":
                        res = ops.forget(body.get("name", ""))
                    elif p == "/v1/persona/set/mood":
                        from harness.personality.tools import adjust_mood
                        res = {"ok": True, "result": adjust_mood(body.get("mood", ""))}
                    elif p == "/v1/persona/set/trait":
                        from harness.personality.tools import set_trait
                        res = {"ok": True, "result": set_trait(body.get("trait", ""),
                                                               body.get("action", "add"))}
                    else:
                        code, res = 404, {"ok": False, "error": "unknown op"}
                except Exception as exc:
                    code, res = 500, {"ok": False, "error": str(exc)}
                payload = json.dumps(res).encode()
                self.send_response(code); _cors(self)
                self.send_header("Content-Type", "application/json"); self.end_headers()
                self.wfile.write(payload)
            # TUNING: set / reset a knob. Live from the next turn — config that needs a
            # restart is config nobody tunes.
            elif self.path in ("/v1/tuning", "/v1/tuning/reset"):
                from harness.tuning import registry as _tune
                body = self._body()
                code, res = 200, {}
                try:
                    if self.path == "/v1/tuning":
                        _tune.set_many(body.get("values", {}))
                    else:
                        _tune.reset(body.get("key", ""))
                    res = {"ok": True, **_tune.schema()}
                except ValueError as exc:
                    code, res = 400, {"ok": False, "error": str(exc)}
                payload = json.dumps(res).encode()
                self.send_response(code); _cors(self)
                self.send_header("Content-Type", "application/json"); self.end_headers()
                self.wfile.write(payload)
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
                # TUNING (2026-07-12): the declarative knob registry. console/tuning.html
                # renders whatever this returns, so a knob added to harness/tuning/
                # registry.py appears in the panel by itself — no UI edit, no route edit.
                "/v1/tuning": lambda: __import__(
                    "harness.tuning.registry", fromlist=["x"]).schema(),
                # STATS IS A READ. It was reachable only under do_POST (with its sibling
                # maintenance PASSES, which do mutate), so a plain GET 404'd — and because
                # the operator panel loaded stats FIRST, that 404 threw and took the whole
                # memory pane down with it. The symptom on screen was "(gateway down)"
                # while the gateway was up and answering every other route. A read that
                # can only be reached by POST is a trap; this is the fix.
                "/v1/maintenance/stats": lambda: __import__(
                    "harness.maintenance.ops", fromlist=["x"]).stats(),
            }
            # query-string routes (session-scoped)
            _base = self.path.split("?", 1)[0]
            if _base in ("/v1/kairos/outbox", "/v1/kairos/state"):
                from urllib.parse import parse_qs, urlparse
                from harness.kairos import scheduler as _ks
                s = (parse_qs(urlparse(self.path).query).get("session") or ["default"])[0]
                out = ({"messages": _ks.drain(s), "state": _ks.peek_state(s)}
                       if _base == "/v1/kairos/outbox" else _ks.peek_state(s))
                self.send_response(200); _cors(self)
                self.send_header("Content-Type", "application/json"); self.end_headers()
                self.wfile.write(json.dumps(out).encode())
                return
            fn = _json_routes.get(_base)
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
    # KAIROS NEEDS A CLOCK. Her CHECK_IN branch asks "has the room been quiet for a while?"
    # — and silence is not an event, so nothing was ever going to ask it on her behalf. The
    # ticker only consults the POLICY (which says SILENT almost always); it reaches the
    # model only when the policy says speak. Guarded by kairos.enabled, so an operator who
    # has not armed her pays nothing.
    try:
        from harness.kairos import scheduler as _ks
        _ks.start_ticker()
    except Exception as exc:
        logger.warning("[gateway] kairos ticker not started: %s", exc)
    ThreadingHTTPServer((host, port), Handler).serve_forever()


def run(host: str = "127.0.0.1", port: int = 8800) -> None:
    """Start the agent gateway (zero-dep stdlib server with native /v1/chat + OpenAI surface)."""
    _run_stdlib(host, port)


if __name__ == "__main__":
    run()
