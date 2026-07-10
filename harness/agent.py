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
    return [ToolSpec.from_callable(fn) for fn in (MEMORY_TOOLS + [run_python, web_search])]


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
    if os.environ.get("SP_PERSONALITY", "0") == "1":
        from harness.personality.tools import PERSONALITY_TOOLS
        tools = tools + PERSONALITY_TOOLS
    specs = [ToolSpec.from_callable(fn) for fn in tools]
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
                                    eot_bias=4.0, max_tokens=192, auto_recall=False)
    # OKFS-tiered tools: core up front + the rest as a load-on-demand index (small system prompt).
    return run_with_tools(
        list(messages), core, extra_tools=extra, client=client, config=cfg, on_tool=on_tool,
        max_rounds=5, system_prefix=load_agent_system())


def agent_chat_stream(
    messages: List[dict],
    *,
    tools: Optional[List[ToolSpec]] = None,
    client: Optional[SPDaemonClient] = None,
    config: Optional[InferenceConfig] = None,
    on_tool: Optional[Callable[[str, dict, str], None]] = None,
    max_rounds: int = 3,
):
    """Streaming agent: yields the FINAL answer token-by-token. Tool rounds run silently
    (the model's ```tool_code is buffered, executed, and fed back without reaching the user);
    only the model's plain-language answer is streamed. A generation is treated as a tool call
    iff it begins with a ```tool fence."""
    client = client or get_client()
    # temp>0 + repetition_penalty 1.3: greedy (temp 0) collapses into in-context repetition ruts
    # ("I don't know" to everything). 0.6/1.3 keeps the voice alive AND breaks the rut; the
    # ```tool_code``` format is robust enough to survive the moderate temperature.
    # NOTE: byteexact MUST stay on (default) -- the float/byteexact-off kvdecode path produces
    # garbage logits for the served chat (verified 2026-06-26). It's also what makes the prefill
    # slow (~233ms/tok exact-integer attention); fixing the float path is the real speed unlock.
    cfg = config or InferenceConfig(temperature=0.6, repetition_penalty=1.3,
                                    eot_bias=4.0, max_tokens=192, auto_recall=False)
    # OKFS-tiered tools: a few core up front, the rest as a load-on-demand index -- keeps the system
    # prompt small (the 1189-token inline preamble is what stalled the gateway).
    if tools is not None:
        system_content, tool_index = build_tool_system(tools, [], system_prefix=load_agent_system())
    else:
        system_content, tool_index = build_tool_system(core_tools(), extra_tools(),
                                                       system_prefix=load_agent_system())
    system = {"role": "system", "content": system_content}
    convo = list(messages)

    for _round in range(max_rounds):
        buf = ""
        is_tool = None  # None = undecided, True = tool call (silent), False = answer (streamed)
        for delta in client.chat_stream(messages=[system] + convo, config=cfg):
            buf += delta
            if is_tool is None:
                s = buf.lstrip()
                # AUDIT 2026-07-10: ANY fence-leading generation is a tool CANDIDATE —
                # the reason model drifts to '``` tool_code' / '```python' variants.
                # The parser resolves it at generation end (unparsed fences flush as-is);
                # cost = fence-leading answers are flushed whole, not token-streamed.
                if s.startswith("```") or "```tool" in s:
                    is_tool = True
                elif s and s[0] != "`" and len(s) >= 4:
                    is_tool = False
                    yield buf  # flush the buffered answer prefix
            elif is_tool is False:
                yield delta  # stream the answer live
            # is_tool True -> keep buffering silently
        # generation finished
        if not is_tool:
            if is_tool is None:  # ambiguous/short -> it was an answer; flush
                yield buf
            return
        calls = _parse_tool_calls(buf, known=set(tool_index))
        if not calls:  # looked like a tool fence but parsed nothing -> show it
            yield buf
            return
        convo.append({"role": "assistant", "content": buf})
        outputs = []
        for name, args, kwargs in calls:
            spec = tool_index.get(name)
            result = spec.call(*args, **kwargs) if spec else f"[unknown tool: {name}]"
            if on_tool:
                on_tool(name, {"args": args, "kwargs": kwargs}, result)
            outputs.append(f"{name} -> {result}")
        # HINDSIGHT 2026-07-10 numeric-fidelity fix: after a tool round, answer at low
        # temperature (the 0.6/1.3 chat config garbles numbers when paraphrasing tool
        # output — live: tool printed 3304, model said "3334") + an explicit verbatim rule.
        from dataclasses import replace as _dc_replace
        cfg = _dc_replace(cfg, temperature=0.15, repetition_penalty=1.05)
        convo.append({"role": "user", "content": "```tool_output\n" + "\n".join(outputs) +
                      "\n```\nAnswer using the tool_output. Copy numbers, dates, and codes "
                      "EXACTLY as printed — do not rephrase or reformat them."})
    yield "(tool loop exhausted)"
