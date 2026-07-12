"""
Ephemeral Tool Calling
=====================

Tool calling for backends without a native ``tool_calls`` finish reason (the
sp-daemon emits plain text). Tools are *ephemeral*: attached to a single
generation, advertised in the system prompt, parsed back out of the model's
output, executed, and the result fed in for the next round. No persistent
registration with the backend.

Protocol (the model is instructed to emit, on its own line)::

    <tool name="read_file">{"path": "main.py"}</tool>

The loop runs each tool, appends an observation, and re-prompts until the
model stops emitting tool calls or ``max_rounds`` is hit.
"""

from __future__ import annotations

import ast
import inspect
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from harness.inference.client import SPDaemonClient, get_client
from harness.inference.inference_config import InferenceConfig

logger = logging.getLogger(__name__)

# Gemma-native: the model wraps calls in a ```tool_code fenced block (Python-style
# calls), and results return in ```tool_output. This is what Gemma is trained to emit.
# We also accept the legacy <tool …>{json}</tool> form as a fallback.
# Fence tolerance (AUDIT + live console 2026-07-10): the reason-SFT model emits
# '``` tool_code', '```toolcode', '```tool code', and — when generation hits
# max_tokens mid-block — UNCLOSED fences. (?:```|\Z) accepts the truncated tail.
_TOOLCODE_RE = re.compile(r"```[ \t]*tool[-_ ]?code\s*(.*?)(?:```|\Z)", re.DOTALL | re.IGNORECASE)  # live census: also 'Tool-Code'
_TOOL_RE = re.compile(r'<tool\s+name="([^"]+)"\s*>(.*?)</tool>', re.DOTALL)
# ```python / ```py / ```tool fences are accepted ONLY when the parsed call names are
# known tools (see _parse_tool_calls(known=...)) so code-example answers pass through.
_ANYFENCE_RE = re.compile(r"```[ \t]*(?:python|py|tool)[ \t]*\n?(.*?)(?:```|\Z)", re.DOTALL | re.IGNORECASE)
# live mutation 'get _time()' — heal a space split around an underscore in a call name.
_NAME_SPLIT_RE = re.compile(r"\b(\w+)\s+_\s*(\w+)\s*\(")


def resolve_tool(tool_index: Dict[str, "ToolSpec"], name: str) -> Optional["ToolSpec"]:
    """Exact, then normalized (case/underscore/hyphen-insensitive) tool lookup —
    the 12B emits 'gettime()' for get_time; don't fail the round on a typo."""
    spec = tool_index.get(name)
    if spec is not None:
        return spec
    def norm(s: str) -> str:
        return s.lower().replace("_", "").replace("-", "")
    n = norm(name)
    for k, v in tool_index.items():
        if norm(k) == n:
            return v
    return None


# ──── ToolSpec ────────────────────────────────────────────────────────────
@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: Dict[str, Any]
    fn: Callable

    def call(self, *args: Any, **kwargs: Any) -> str:
        try:
            return str(self.fn(*args, **kwargs))
        except Exception as exc:
            return f"[tool error: {exc}]"

    def advertise(self) -> str:
        params = ", ".join(self.parameters.get("properties", {}).keys())
        return f'- {self.name}({params}): {self.description}'

    def signature(self) -> str:
        """Gemma-style Python signature line for the tool preamble."""
        ps = []
        props = self.parameters.get("properties", {})
        req = set(self.parameters.get("required", []))
        ann_of = {"string": "str", "integer": "int", "number": "float", "boolean": "bool"}
        for p, meta in props.items():
            ann = ann_of.get(meta.get("type"), "str")
            ps.append(f"{p}: {ann}" + ("" if p in req else " = None"))
        return f"def {self.name}({', '.join(ps)}):  # {self.description}"

    @classmethod
    def from_callable(cls, fn: Callable, name: str = "", description: str = "") -> "ToolSpec":
        sig = inspect.signature(fn)
        props: Dict[str, Any] = {}
        required: List[str] = []
        type_map = {str: "string", int: "integer", float: "number", bool: "boolean"}
        for pname, p in sig.parameters.items():
            base = p.annotation
            base = getattr(base, "__args__", [base])[0] if getattr(base, "__origin__", None) else base
            props[pname] = {"type": type_map.get(base, "string")}
            if p.default is inspect.Parameter.empty:
                required.append(pname)
        return cls(
            name=name or fn.__name__,
            description=description or (fn.__doc__ or "").strip().split("\n")[0],
            parameters={"type": "object", "properties": props, "required": required},
            fn=fn,
        )


# ──── Registry (scoped tool selection) ────────────────────────────────────
class ToolRegistry:
    """Builds ephemeral tool sets, including from the skill registry."""

    def __init__(self) -> None:
        self._specs: Dict[str, ToolSpec] = {}

    def register(self, fn: Callable, name: str = "", description: str = "") -> ToolSpec:
        spec = ToolSpec.from_callable(fn, name, description)
        self._specs[spec.name] = spec
        return spec

    def load_from_skills(self, pack: str = "", names: Optional[List[str]] = None) -> int:
        from harness.skills.registry import SKILL_REGISTRY
        metas = (
            [SKILL_REGISTRY.get_skill(n) for n in names] if names
            else SKILL_REGISTRY.get_pack_metas(pack) if pack
            else list(SKILL_REGISTRY._by_name.values())  # noqa: SLF001
        )
        count = 0
        for m in metas:
            if m is None:
                continue
            self._specs[m.name] = ToolSpec.from_callable(m.func, m.name, m.description)
            count += 1
        return count

    def specs(self, names: Optional[List[str]] = None) -> List[ToolSpec]:
        if names:
            return [self._specs[n] for n in names if n in self._specs]
        return list(self._specs.values())


_REGISTRY: Optional[ToolRegistry] = None


def get_tool_registry() -> ToolRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = ToolRegistry()
    return _REGISTRY


# ──── The loop ────────────────────────────────────────────────────────────
def _tool_preamble(tools: List[ToolSpec]) -> str:
    """Gemma-native tool preamble: advertise Python signatures, ask for a ```tool_code block."""
    sigs = "\n".join(t.signature() for t in tools)
    # Concrete example built from the FIRST tool's real signature, so the model copies a
    # real call (not the placeholder param name "arg").
    example = "func()"
    if tools:
        t0 = tools[0]
        props = list(t0.parameters.get("properties", {}).keys())
        example = f'{t0.name}({props[0]}="value")' if props else f"{t0.name}()"
    return (
        "You have access to these Python functions (and ONLY these):\n\n"
        + sigs +
        "\n\nWhen you decide to call a function, output it in a fenced block EXACTLY like this:\n"
        "```tool_code\n" + example + "\n```\n"
        "Use the REAL parameter names from the signatures above (not placeholder names). "
        "Then STOP. The result returns to you as:\n```tool_output\n...result...\n```\n"
        "Rules: call a function INSTEAD of writing the code or answer yourself, then wait for the "
        "tool_output. Pass arguments as Python literals (strings in quotes). When the tool_output "
        "comes back, answer using ONLY its exact values — never invent or substitute. Do not call "
        "functions that are not listed above."
    )


# ──── OKFS-tiered tool loading (LUT -> gist -> full) ──────────────────────
# The same three-tier shape as MEM-OKF: a tiny always-loaded INDEX (name + one-line gist) of the
# tools an agent COULD use, a few CORE tools advertised in full up front, and `load_tools` to pull
# the FULL signature of any other tool on demand. This keeps the system prompt small (the 1189-token
# "inline every signature" preamble is what stalled the gateway) and lets the model load only the
# minimum, expanding as needs come up. The executor (tool_index) still holds EVERY tool, so once the
# model has seen a signature it can call it. This is the project-wide pattern: load the gist, expand
# to full only when required.
def _make_load_tools(all_specs: Dict[str, "ToolSpec"]) -> "ToolSpec":
    """The meta-tool: reveal the FULL signature(s) of named tools on demand (the OKFS 'full' tier)."""
    def load_tools(names: str) -> str:
        wanted = [x.strip() for x in str(names).replace(";", ",").replace(" ", ",").split(",") if x.strip()]
        out = []
        for n in wanted:
            spec = all_specs.get(n)
            out.append(spec.signature() if spec else f"# no tool named '{n}'")
        return "\n".join(out) if out else "# usage: load_tools(\"name1,name2\")"
    return ToolSpec.from_callable(
        load_tools, "load_tools",
        "Reveal how to call other tools by name (comma-separated), then call them")


def build_tool_system(
    core: List["ToolSpec"],
    extra: Optional[List["ToolSpec"]] = None,
    system_prefix: str = "",
    system_suffix: str = "",
) -> tuple:
    """OKFS-tiered tool context. Returns (system_content, tool_index).

    CORE tools are advertised with full signatures (always loadable). EXTRA tools appear only as a
    one-line gist INDEX (LUT); the model calls ``load_tools("name")`` to get an extra's full
    signature, then calls it. ``tool_index`` can execute ANY of them (core + extra + load_tools)."""
    extra = extra or []
    all_specs: Dict[str, ToolSpec] = {t.name: t for t in (list(core) + list(extra))}
    load_tools_spec = _make_load_tools(all_specs)
    tool_index: Dict[str, ToolSpec] = dict(all_specs)
    tool_index[load_tools_spec.name] = load_tools_spec

    core_sigs = "\n".join(t.signature() for t in core)
    core_sigs += "\n" + load_tools_spec.signature()
    example = "load_tools(names=\"...\")"
    if core:
        props = list(core[0].parameters.get("properties", {}).keys())
        example = f'{core[0].name}({props[0]}="value")' if props else f"{core[0].name}()"
    def _gist(d: str) -> str:  # LUT tier: one short line, not the full docstring
        d = (d or "").replace("\n", " ").split(". ")[0].strip()
        return (d[:54] + "…") if len(d) > 55 else d
    lut = "\n".join(f"- {t.name}: {_gist(t.description)}" for t in extra)

    parts = [
        "You have tools. A FEW are ready to call right now (full signatures below). MANY MORE are "
        "listed by name only — call load_tools(\"name\") to see how one works, then call it.",
        "\n# Ready now:\n" + core_sigs,
    ]
    if lut:
        parts.append("\n# Also available (load_tools(\"name\") to use):\n" + lut)
    # "answer using ONLY its exact values" is a rule about answering FROM A TOOL_OUTPUT —
    # do not paraphrase the number, do not invent a row. Stated flatly, as the LAST thing in
    # the system prompt, it reads as a rule about ANSWERING, and she carried it into ordinary
    # conversation: asked how she was feeling, she said "Good." A literalness instruction
    # with no scope on it becomes a personality. It is scoped now.
    parts.append(
        "\nTo call a tool, output a fenced block EXACTLY like this, then STOP and wait:\n"
        "```tool_code\n" + example + "\n```\n"
        "Pass arguments as Python literals (strings in quotes), and use the REAL parameter names. "
        "The result returns as ```tool_output ... ```. WHEN YOU ANSWER FROM A TOOL_OUTPUT, use "
        "its exact values — never invent or substitute them. (That is a rule about quoting a "
        "tool, not a rule about how you talk.) "
        "Most turns need NO tool — just talk; reach for one only when you truly need it."
    )
    preamble = "\n".join(parts)
    sys_content = (system_prefix.strip() + "\n\n" + preamble) if system_prefix.strip() else preamble
    if system_suffix.strip():
        sys_content = sys_content + "\n\n" + system_suffix.strip()
    return sys_content, tool_index


def _calls_from_code(code: str) -> List[tuple]:
    """AST-parse a code block into [(name, args, kwargs)] call tuples."""
    calls: List[tuple] = []
    code = _NAME_SPLIT_RE.sub(r"\1_\2(", code)  # heal 'get _time()' -> 'get_time()'
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError:
        return calls
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", None)
        if not name:
            continue
        args = []
        for a in node.args:
            try:
                args.append(ast.literal_eval(a))
            except Exception:
                args.append(None)
        kwargs = {}
        for kw in node.keywords:
            try:
                kwargs[kw.arg] = ast.literal_eval(kw.value)
            except Exception:
                kwargs[kw.arg] = None
        calls.append((name, args, kwargs))
    return calls


def _parse_tool_calls(text: str, known: Optional[set] = None) -> List[tuple]:
    """Extract [(name, args_list, kwargs_dict)] from the model's text. Prefers Gemma's
    ```tool_code fenced Python calls (space-tolerant); falls back to the legacy
    <tool …>{json} form; finally (AUDIT 2026-07-10) accepts ```python/```py/```tool
    fences whose calls name KNOWN tools — the reason-SFT model drifts to those fences."""
    calls: List[tuple] = []
    for block in _TOOLCODE_RE.findall(text):
        calls.extend(_calls_from_code(block.strip().strip("`").strip()))
    if not calls:  # legacy <tool …>{json} fallback
        for name, raw in _TOOL_RE.findall(text):
            try:
                kw = json.loads(raw.strip() or "{}")
            except json.JSONDecodeError:
                kw = {}
            calls.append((name, [], kw if isinstance(kw, dict) else {}))
    if not calls and known:  # fence-drift fallback: only KNOWN tool names count
        def _norm(s: str) -> str:
            return s.lower().replace("_", "").replace("-", "")
        known_norm = {_norm(k) for k in known}
        py_blocks: List[str] = []
        for m in re.finditer(r"```[ \t]*(python|py|tool)\b[ \t]*\n?(.*?)(?:```|\Z)",
                             text, re.DOTALL | re.IGNORECASE):
            tag, block = m.group(1), m.group(2).strip()
            # model mashups seen live: '```python\ntool_code websearch(...)' — strip the
            # stray tool_code token so the call underneath parses.
            block = re.sub(r"^\s*tool_?code\b[:\s]*", "", block)
            cs = [c for c in _calls_from_code(block) if _norm(c[0]) in known_norm]
            calls.extend(cs)
            if not cs and tag in ("python", "py") and block:
                py_blocks.append(block)
        # AUTO-ROUTE (live console 2026-07-10): when the model writes a GENUINE python
        # block instead of calling a tool ('```python\nimport datetime...'), run it
        # through the sandboxed run_python tool — identical power to the explicit call
        # it was supposed to make, and the feedback loop shows it the real output.
        if not calls and "run_python" in known:
            for block in py_blocks:
                try:
                    if ast.parse(block, mode="exec").body:
                        calls.append(("run_python", [block], {}))
                        break
                except SyntaxError:
                    continue
    return calls


def run_with_tools(
    messages: List[Dict[str, str]],
    tools: List[ToolSpec],
    *,
    extra_tools: Optional[List[ToolSpec]] = None,
    client: Optional[SPDaemonClient] = None,
    config: Optional[InferenceConfig] = None,
    max_rounds: int = 6,
    on_tool: Optional[Callable[[str, dict, str], None]] = None,
    system_prefix: str = "",
) -> str:
    """Run an ephemeral tool-calling loop and return the final assistant text.

    CALLED BY: the CLI coder, agent reply paths.
    EMITS: ``on_tool(name, args, result)`` per call.
    `system_prefix` (e.g. an identity/behaviour prompt) is merged into the single system turn.
    """
    client = client or get_client()
    cfg = config or InferenceConfig()
    # OKFS-tiered tool context (core full + extra gist-index + load_tools); tool_index executes any.
    # THE VOICE CODA GOES HERE TOO. Both paths (this blocking loop and agent_chat_stream)
    # must build the IDENTICAL system prompt — not only so she is the same person on each,
    # but because a system prompt that differs between paths diverges the persist-KV cache
    # at token 0 and re-prefills the whole conversation. That bug cost 111 seconds a turn
    # last time; it is not going to be reintroduced by a personality fix.
    try:
        from harness.agent import voice_coda as _coda
        _suffix = _coda()
    except Exception:
        _suffix = ""
    sys_content, tool_index = build_tool_system(tools, extra_tools or [],
                                                system_prefix=system_prefix,
                                                system_suffix=_suffix)
    system = {"role": "system", "content": sys_content}

    convo = list(messages)

    final = ""
    # PK2 §T2-E3 robustness: malformed-fence recovery + no-progress (repeat-call) detection.
    prev_round_sig = None          # signature of last round's (calls, outputs)
    repeat_streak = 0
    for _round in range(max_rounds):
        resp = client.chat(messages=[system] + convo, config=cfg)
        text = resp.text
        calls = _parse_tool_calls(text, known=set(tool_index))
        if not calls:
            # MALFORMED RECOVERY: the model opened a tool fence but nothing parsed —
            # returning that raw fence as the "answer" is a silent failure. Feed the
            # parse error back once per occurrence (bounded by max_rounds) instead.
            # (space-tolerant: the reason model emits '``` tool_code' variants)
            if re.search(r"```[ \t]*tool", text) or "<tool " in text:
                logger.info("[tools] malformed tool call — re-prompting (round=%d)", _round)
                convo.append({"role": "assistant", "content": text})
                convo.append({"role": "user", "content":
                    "```tool_output\n[parse error] That tool call could not be parsed. Emit ONE "
                    "fenced block exactly like:\n```tool_code\nname(param=\"value\")\n```\n"
                    "with real parameter names, or answer in plain text with no fence.\n```"})
                continue
            final = text
            break
        convo.append({"role": "assistant", "content": text})
        # ONE CALL PER ROUND, AND THE ROUND IS THE ENFORCEMENT (2026-07-12).
        #
        # The prompt has said "Call at most ONE tool" since the beginning. Nothing enforced
        # it, and on the first live notes turn she emitted THREE in one fence — add_note,
        # then edit_note, then remove_note — and narrated it herself: "I'll remove the
        # temporary note after editing it". She added the note, tidied it, and then deleted
        # it, all before seeing a single tool_output. The board came back empty and she told
        # him it was done.
        #
        # A tool call is an ACTION ON THE WORLD, and an action taken without seeing the
        # result of the previous one is a guess. Truncating to one forces the loop to do
        # what a loop is for: act, observe, then decide. She can still call a second tool —
        # on the next round, knowing what the first one did.
        if len(calls) > 1:
            logger.info("[tools] %d calls in one fence — taking the FIRST (%s) and letting "
                        "her see its result before the next", len(calls), calls[0][0])
            calls = calls[:1]
        outputs = []
        for name, args, kwargs in calls:
            spec = resolve_tool(tool_index, name)
            result = spec.call(*args, **kwargs) if spec else \
                f"[unknown tool: {name} — available: {', '.join(sorted(tool_index))}]"
            if on_tool:
                on_tool(name, {"args": args, "kwargs": kwargs}, result)
            outputs.append(f"{name} -> {result}")
        # NO-PROGRESS DETECTOR: identical calls producing identical outputs two rounds
        # running is a rut (the greedy-repetition failure class). Nudge once, then stop
        # honestly instead of burning the remaining rounds.
        round_sig = repr((calls, outputs))
        repeat_streak = repeat_streak + 1 if round_sig == prev_round_sig else 0
        prev_round_sig = round_sig
        if repeat_streak >= 2:
            logger.warning("[tools] no-progress loop broken (operation=run_with_tools, round=%d)", _round)
            final = "(stopped: repeating the same tool call with the same result — " \
                    "latest output: " + "; ".join(outputs)[:400] + ")"
            break
        tail = ("\n[note] You already made this exact call and saw this result. Use it to answer, "
                "or try something different.") if repeat_streak == 1 else ""
        convo.append({"role": "user", "content": "```tool_output\n" + "\n".join(outputs) + tail + "\n```\n"
                      "Answer using the tool_output. Copy numbers, dates, and codes EXACTLY "
                      "as printed — do not rephrase or reformat them."})
        # HINDSIGHT 2026-07-10 numeric-fidelity: post-tool rounds answer at low temperature
        # (0.6/1.3 garbles numbers when paraphrasing tool output).
        from dataclasses import replace as _dc_replace
        cfg = _dc_replace(cfg, temperature=0.15, repetition_penalty=1.05)
    else:
        logger.warning("[tools] max rounds reached (operation=run_with_tools, rounds=%d)", max_rounds)
        final = final or "(tool loop exhausted)"
    return final
