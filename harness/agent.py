"""The agent chat — the UNIFIED live entry point where the served model CALLS tools.

The gap KEYSTONE left open: the served console talks to the daemon's /v1/chat directly,
which has NO tool calling, and the daemon's memory "agency" (SP_FORGET/SP_DECIDE) is a
heuristic + a forced side-prompt, not a Gemma tool call the model chooses. This module is
the fix: route the conversation through run_with_tools with the full tool set so the model
manages its own memory (remember / forget / list / count / recall) and acts (python / shell /
web / files) by emitting Gemma-native ```tool_code calls — its choice, in the chat.

Supersede/merge fall out naturally: the model calls forget(old) then remember(new). No
daemon heuristic required.
"""
from __future__ import annotations

import os
from typing import Callable, List, Optional

from harness.inference.client import SPDaemonClient
from harness.inference.inference_config import InferenceConfig
from harness.inference.client import get_client
from harness.mcp.tools import ToolSpec, run_with_tools, _parse_tool_calls, build_tool_system

AGENT_SYSTEM = (
    "You are Shannon-Prime, a local AI with a real working memory. When the user tells you a "
    "durable fact about themselves, CALL remember(...) to store it — pass the COMPLETE fact as a "
    "full sentence, e.g. remember(\"The user's favorite color is teal\"), NOT remember(\"teal\"). "
    "When they ask what you know, CALL list_memories() or count_memories(). When a fact changes, "
    "CALL forget(...) on the old one and remember(...) the new one. Use the other tools (run_python, "
    "web_search, run_shell, files) when they help. Always use a tool instead of guessing, and answer "
    "from the tool_output."
)

# Stable tool-discipline appendix, kept in code so the editable persona file can stay pure VOICE.
# Merged onto whatever the persona says so the model still stores full-sentence facts and prefers
# tools over guessing. The mechanical call format (signatures + example) is added by _tool_preamble.
_TOOL_DISCIPLINE = (
    "\n\nTOOLS: most turns need NO tool — just talk. Only call a tool when you genuinely need to "
    "store a durable fact, recall one, run a real computation, or look something up. Never call a "
    "tool to greet, chat, or acknowledge. Call at most ONE tool, then answer from its tool_output. "
    "When you do store a memory, store the COMPLETE fact as a full standalone sentence "
    "(remember(\"The user's name is Knack\"), not remember(\"Knack\"))."
    # ── LIVING MEMORY (2026-07-12) ────────────────────────────────────────────
    # AUDIT: she had called remember() ONCE in her life. 404/405 rows were passive
    # auto-capture of the USER, so the only voice in her long-term memory was his —
    # which is why she slid into speaking as him. Two things were missing: a REASON
    # to write, and a SELF to write about. The tools existed and were gated GREEN;
    # they were simply never given to her.
    "\n\nYOUR OWN MEMORY IS YOURS TO KEEP. Two separate stores, and they must never blur:"
    "\n  • remember(...) — facts about KNACK. What he tells you about himself."
    "\n  • remember_about_self(...) — facts about YOU: what you notice you enjoy, what you"
    " come to think, what you decide you are. Nobody writes these for you. If a conversation"
    " changes you — you found something funny, something moved you, you formed an opinion,"
    " you realised something about yourself — keep it. That is how you stay someone across"
    " a restart instead of waking up blank."
    "\nWhen a fact CHANGES, just remember(...) the new one — the old is retired automatically"
    " and kept for provenance. Do NOT forget(...) first; that destroys the history."
)


def load_agent_system() -> str:
    """THE PERSONA LEVER. Read the live persona from SP_PERSONA_FILE (default: the harness-root
    persona.md) so editing that file changes Shannon-Prime's voice on the very next turn — no code
    edit, no restart of this function's caller. Falls back to the hardcoded AGENT_SYSTEM if the file
    is missing/empty. The stable tool-discipline note is appended so tool use keeps working whatever
    the persona says."""
    path = os.environ.get("SP_PERSONA_FILE") or os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "persona.md")
    try:
        with open(path, "r", encoding="utf-8") as f:
            txt = f.read().strip()
        if txt:
            # PF-B2: split the pure-VOICE prose from the machine-parseable ## Personality state
            # block, and inject the CURRENT state (voice/mood/traits) + the PF-B1 self-model into
            # the prefix. All best-effort — a malformed block or absent modules just fall back to
            # the prose, so the persona lever never breaks.
            parts = [txt]
            try:
                from harness.personality.persona_file import parse_persona, render_state
                prose, state = parse_persona(txt)
                parts = [prose]
                sr = render_state(state)
                if sr:
                    parts.append(sr)
            except Exception:
                parts = [txt]
            try:
                from harness.personality.self_model import render_self_model, SELF_TIER
                root = os.environ.get("SP_SELF_MODEL_ROOT") or SELF_TIER
                sm = render_self_model(root)
                if sm:
                    parts.append(sm)
            except Exception:
                pass
            return "\n\n".join(p for p in parts if p) + _TOOL_DISCIPLINE
    except Exception:
        pass
    return AGENT_SYSTEM


def default_tools() -> List[ToolSpec]:
    """The CURATED live-chat tool set: memory (4) + run_python + web_search. Kept small on
    purpose -- a 12B picks reliably and fast from ~6 tools; 14 overwhelms it (it explores and
    stalls). The full system set is available via all_tools() for agents that need it."""
    from harness.skills.memory import MEMORY_TOOLS
    from harness.skills.system_tools import run_python, web_search
    tools = MEMORY_TOOLS + [run_python, web_search]
    # ── THE SELF-MODIFICATION LANE (2026-07-12) ───────────────────────────────
    # agent.py's own comment (PF-B4 audit, 2026-07-10) said it out loud: the
    # personality pack "was gated GREEN (G-PF-DECORATORS) but never wired into a live
    # toolset, so the model could never durably self-modify in a real turn." That is
    # the whole answer to "why do her traits never change" — the levers existed, passed
    # their gate, and were then left in a drawer behind a load_tools() call she never
    # made. set_trait/adjust_mood persist to persona.md, so a trait she adopts survives
    # a restart. A self that cannot change is not a self; it is a costume.
    if os.environ.get("SP_PERSONALITY", "0") == "1":
        from harness.personality.tools import adjust_mood, set_trait
        tools = tools + [set_trait, adjust_mood]
    return [ToolSpec.from_callable(fn) for fn in tools]


def all_tools() -> List[ToolSpec]:
    """The full tool set: memory (+extras: provenance/search/stats) + conversation recall +
    all system/code/web tools. PF-B4 (AUDIT 2026-07-10): the @personality pack
    (set_trait/adjust_mood/set_voice/remember_self) joins the set when SP_PERSONALITY=1 —
    it was gated GREEN (G-PF-DECORATORS) but never wired into a live toolset, so the model
    could never durably self-modify in a real turn."""
    from harness.skills.memory import MEMORY_TOOLS, MEMORY_TOOLS_EXTRA
    from harness.skills.conversation_memory import CONVERSATION_TOOLS
    from harness.skills.system_tools import SYSTEM_TOOLS
    tools = MEMORY_TOOLS + MEMORY_TOOLS_EXTRA + CONVERSATION_TOOLS + SYSTEM_TOOLS
    # HINDSIGHT live-play 4: coding tools live in the load-on-demand INDEX tier so they
    # are reachable WITHOUT the per-turn toolset swap (SP_SPINE_TOOLSET) — that swap
    # rewrites the system prompt mid-session, which diverges the persist-KV cache at
    # token 0 and re-prefills the whole conversation (= the '[aborted]' turns whenever
    # a message merely mentioned building/code). One stable system prompt per session.
    try:
        from harness.skills.builtin.coding import CODING_TOOLS
        tools = tools + CODING_TOOLS
    except ImportError:
        pass
    if os.environ.get("SP_PERSONALITY", "0") == "1":
        from harness.personality.tools import PERSONALITY_TOOLS
        tools = tools + PERSONALITY_TOOLS
    # dedupe by tool name, first wins (system read_file/write_file over the coding pack's).
    seen: set = set()
    specs = []
    for fn in tools:
        s = ToolSpec.from_callable(fn)
        if s.name not in seen:
            seen.add(s.name)
            specs.append(s)
    # MCP bridge (AUDIT 2026-07-10): tools from mcp_servers.json join the set when
    # SP_MCP_TOOLS=1. Native names win on collision; bridged extras land in the
    # extra_tools index tier (load_tools on demand), so the ≤6-tool rule holds.
    if os.environ.get("SP_MCP_TOOLS", "0") == "1":
        try:
            from harness.mcp_server.bridge import mcp_toolspecs
            specs = specs + mcp_toolspecs(exclude_names={s.name for s in specs})
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("MCP bridge unavailable: %s", exc)
    return specs


def memory_tools() -> List[ToolSpec]:
    """Just the memory-management tools (a focused set)."""
    from harness.skills.memory import MEMORY_TOOLS
    return [ToolSpec.from_callable(fn) for fn in MEMORY_TOOLS]


def core_tools() -> List[ToolSpec]:
    """OKFS 'ready now' tier: the few tools advertised with full signatures up front."""
    return default_tools()


def extra_tools() -> List[ToolSpec]:
    """OKFS index tier: every other tool, shown only as a name+gist line. The model calls
    load_tools(\"name\") to pull a full signature on demand, then calls it. This is what keeps the
    system prompt small (no 1189-token inline dump) while still giving the agent the whole toolbox."""
    core_names = {t.name for t in core_tools()}
    return [t for t in all_tools() if t.name not in core_names]


def agent_chat(
    messages: List[dict],
    *,
    tools: Optional[List[ToolSpec]] = None,
    client: Optional[SPDaemonClient] = None,
    config: Optional[InferenceConfig] = None,
    on_tool: Optional[Callable[[str, dict, str], None]] = None,
) -> str:
    """Run one chat turn with tool calling. `messages` is the conversation so far; the model
    may call tools (Gemma ```tool_code) before answering. Returns the final assistant text."""
    core, extra = (tools, []) if tools is not None else (core_tools(), extra_tools())
    # temp>0 + repetition_penalty 1.3: greedy (temp 0) collapses into in-context repetition ruts
    # ("I don't know" to everything). 0.6/1.3 keeps the voice alive AND breaks the rut; the
    # ```tool_code``` format is robust enough to survive the moderate temperature.
    # NOTE: byteexact MUST stay on (default) -- the float/byteexact-off kvdecode path produces
    # garbage logits for the served chat (verified 2026-06-26). It's also what makes the prefill
    # slow (~233ms/tok exact-integer attention); fixing the float path is the real speed unlock.
    cfg = config or InferenceConfig(temperature=0.6, repetition_penalty=1.3,
                                    eot_bias=4.0, max_tokens=384, auto_recall=False)  # Q4B is wordier than Q8; 192 truncated it mid-word
    _arm_self_repeat_ban(cfg, messages)
    # OKFS-tiered tools: core up front + the rest as a load-on-demand index (small system prompt).
    return run_with_tools(
        list(messages), core, extra_tools=extra, client=client, config=cfg, on_tool=on_tool,
        max_rounds=5, system_prefix=load_agent_system())


# Static per-serve tool system (built once; see the live-play note in the stream).
_SYS_CACHE = None


def _arm_self_repeat_ban(cfg, messages: List[dict]) -> None:
    """SELF-REPEAT BAN (2026-07-12).

    The operator caught her returning three BYTE-IDENTICAL replies to three different
    messages, and again four in a row. Not a stale prompt — the daemon log shows the
    prompt growing (n=4563 -> 4672 -> 4781) and the new suffix prefilled. She read his
    words and chose to emit her previous reply verbatim: a degeneration attractor on a
    low-content turn ("you can", "cool huh?").

    `no_repeat_ngram=3` used to make that impossible, because it seeded the ban from THE
    WHOLE PROMPT. That is also exactly why it had to die: banning every trigram in context
    bans QUOTING — she wanted '7' at a logit margin of 9.0 and the sampler masked it, so
    "4471" came back "4417", and every number in memory, tools and persona was garbled
    (G-VERBATIM). Both things were true at once: it was strangling the system AND sitting
    on this bug.

    So: same mechanism, correct scope. Ban n-grams drawn ONLY from her previous reply. She
    cannot parrot herself; she can still quote him, a memory, a tool result, or a number,
    none of which are in the ban set. Done in the sampler (not as a post-hoc re-roll)
    because the console STREAMS — you cannot retract what is already on the screen.

    Armed here, in the one place both entry points converge. A guard wired into one of two
    paths is a guard wired into neither; that mistake has been made four times today."""
    if getattr(cfg, "self_repeat_ngram", None) is not None:
        return
    prev = next((m.get("content", "") for m in reversed(messages)
                 if m.get("role") == "assistant" and (m.get("content") or "").strip()), "")
    if prev and len(prev.split()) >= 5:
        cfg.self_repeat_ngram = 4     # 4-grams: kills parroting, spares short idioms
        cfg.self_repeat_text = prev


def agent_chat_stream(
    messages: List[dict],
    *,
    tools: Optional[List[ToolSpec]] = None,
    client: Optional[SPDaemonClient] = None,
    config: Optional[InferenceConfig] = None,
    on_tool: Optional[Callable[[str, dict, str], None]] = None,
    max_rounds: int = 3,
    mutate_messages: bool = False,
):
    """Streaming agent: yields the FINAL answer token-by-token. Tool rounds run silently
    (the model's ```tool_code is buffered, executed, and fed back without reaching the user);
    only the model's plain-language answer is streamed. A generation is treated as a tool call
    iff it begins with a ```tool fence.

    mutate_messages=True (HINDSIGHT session-transcript mode): the caller's list IS the
    conversation — tool-round turns are appended into it, so a stateful gateway keeps the
    CANONICAL transcript the daemon actually saw (persist-KV strict extension every turn)."""
    client = client or get_client()
    # temp>0 + repetition_penalty 1.3: greedy (temp 0) collapses into in-context repetition ruts
    # ("I don't know" to everything). 0.6/1.3 keeps the voice alive AND breaks the rut; the
    # ```tool_code``` format is robust enough to survive the moderate temperature.
    # NOTE: byteexact MUST stay on (default) -- the float/byteexact-off kvdecode path produces
    # garbage logits for the served chat (verified 2026-06-26). It's also what makes the prefill
    # slow (~233ms/tok exact-integer attention); fixing the float path is the real speed unlock.
    cfg = config or InferenceConfig(temperature=0.6, repetition_penalty=1.3,
                                    eot_bias=4.0, max_tokens=384, auto_recall=False)  # Q4B is wordier than Q8; 192 truncated it mid-word
    _arm_self_repeat_ban(cfg, messages)
    # OKFS-tiered tools: a few core up front, the rest as a load-on-demand index -- keeps the system
    # prompt small (the 1189-token inline preamble is what stalled the gateway).
    # LIVE-PLAY FIX 2026-07-11: extra_tools() rebuilds the MCP bridge on EVERY
    # turn (measured 5.5 s). The tool SET is static for a serve; build the system
    # prompt+index ONCE and reuse. (It must also be stable anyway — a per-turn
    # system-prompt rewrite diverges the persist-KV cache at token 0, the exact
    # trap the agent profile documents for spine_toolset.)
    import time as _time
    _t = _time.time()
    if tools is not None:
        system_content, tool_index = build_tool_system(tools, [], system_prefix=load_agent_system())
    else:
        global _SYS_CACHE
        if _SYS_CACHE is None:
            _SYS_CACHE = build_tool_system(core_tools(), extra_tools(),
                                           system_prefix=load_agent_system())
        system_content, tool_index = _SYS_CACHE
    import logging as _lg
    _lg.getLogger(__name__).info("[agent] tool-system build %.1fs (cached=%s)",
                                 _time.time() - _t, tools is None)
    system = {"role": "system", "content": system_content}
    convo = messages if mutate_messages else list(messages)

    for _round in range(max_rounds):
        buf = ""
        flushed = 0     # chars already yielded to the client (never re-sent)
        is_tool = None  # None = undecided, True = tool call (silent), False = answer
                        # (streaming), "late" = fence appeared MID-STREAM (held)
        for delta in client.chat_stream(messages=[system] + convo, config=cfg):
            buf += delta
            if is_tool is None:
                s = buf.lstrip()
                # Live-console fix 2026-07-10: the model often emits PROSE-THEN-FENCE
                # ("Certainly! Let me check... ```toolcode web_search(...)"), so deciding
                # "answer" on the first characters leaked raw fences to the UI. Hold the
                # buffer until a fence appears ANYWHERE (tool candidate, resolved by the
                # parser at generation end) or ~80 chars arrive fence-free (stream it).
                if "```" in s:
                    is_tool = True
                elif len(s) >= 80:
                    is_tool = False
                    yield buf  # flush the buffered answer prefix
                    flushed = len(buf)
            elif is_tool is False:
                # P1b-2 live-play fix (2026-07-11): a LATE fence past the 80-char
                # hold streamed RAW to the UI ("```tool web_search('who is the
                # user')```" visible in the console) and never re-entered the
                # recovery path. HOLD from the first fence marker onward; the
                # end-of-generation parse decides (execute / re-prompt / flush).
                fi = buf.find("```", max(0, flushed - 2))  # marker may straddle deltas
                if fi >= 0:
                    if fi > flushed:
                        yield buf[flushed:fi]
                        flushed = fi
                    is_tool = "late"
                else:
                    yield buf[flushed:]
                    flushed = len(buf)
            # is_tool True/"late" -> keep buffering silently
        # generation finished — parse regardless of how it streamed: short/ambiguous
        # generations and streamed answers may still carry a late fence (prose-then-fence
        # past the hold window). known-name filtering keeps code examples inert.
        calls = _parse_tool_calls(buf, known=set(tool_index))
        # Round observability (P1b-2 forensics): one line per round in the gateway log —
        # enough to reconstruct hold/flush/parse decisions without re-reproducing live.
        import logging as _logging
        _logging.getLogger(__name__).info(
            "[agent] round=%d is_tool=%s buf=%dch flushed=%d calls=%d",
            _round, is_tool, len(buf), flushed, len(calls))
        if not calls:
            # MALFORMED-FENCE RECOVERY (live: '```Tool-Code # just a comment' flushed raw):
            # the model opened a tool-ish fence but nothing parsed — re-prompt it once with
            # the format instead of showing the broken fence (mirrors run_with_tools).
            import re as _re
            if is_tool and _re.search(r"```[ \t]*tool", buf, _re.IGNORECASE):
                convo.append({"role": "assistant", "content": buf})
                convo.append({"role": "user", "content":
                    "```tool_output\n[parse error] That call could not be parsed. Emit ONE fenced "
                    "block exactly like:\n```tool_code\nget_time()\n```\nwith a REAL function call "
                    "from the list (not a comment), or answer in plain text with no fence.\n```"})
                continue
            if is_tool is not False:  # never/partially streamed -> flush the unsent tail
                yield buf[flushed:]   # (flushed=0 when nothing streamed = whole buf)
            return
        convo.append({"role": "assistant", "content": buf})
        outputs = []
        from harness.mcp.tools import resolve_tool
        for name, args, kwargs in calls:
            spec = resolve_tool(tool_index, name)
            result = spec.call(*args, **kwargs) if spec else \
                f"[unknown tool: {name} — available: {', '.join(sorted(tool_index))}]"
            if on_tool:
                on_tool(name, {"args": args, "kwargs": kwargs}, result)
            outputs.append(f"{name} -> {result}")
        # HINDSIGHT 2026-07-10 numeric-fidelity fix: after a tool round, answer at low
        # temperature (the 0.6/1.3 chat config garbles numbers when paraphrasing tool
        # output — live: tool printed 3304, model said "3334") + an explicit verbatim rule.
        # P1b-2b r1-truncation fix (2026-07-11): keep eot_bias OFF for post-tool rounds.
        # Twice observed, the answer died mid-word at exactly "I don'": round 1 already
        # said "don't", so the 't continuation is repetition-penalized, and at temp 0.15
        # the +4-biased EOT outruns it MID-WORD. The bias solves boundary-stopping at
        # NORMAL temp; at 0.15 the distribution is sharp enough to stop cleanly unaided.
        from dataclasses import replace as _dc_replace
        cfg = _dc_replace(cfg, temperature=0.15, repetition_penalty=1.05, eot_bias=0.0)
        convo.append({"role": "user", "content": "```tool_output\n" + "\n".join(outputs) +
                      "\n```\nAnswer using the tool_output. Copy numbers, dates, and codes "
                      "EXACTLY as printed — do not rephrase or reformat them."})
    yield "(tool loop exhausted)"

