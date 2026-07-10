"""PF-B3 — self-modify personality via tags. The model already emits [MOOD:x]/[VOICE:x] (and now
[TRAIT:+x]/[TRAIT:-x]); StreamProcessor strips them from output but never PERSISTED them. This adds
a post-call interceptor that reads those tags off the reply and writes them into the persona state
(PF-B2 write_state), so a voice/mood/trait the model chooses this turn survives to the next — the
model self-modifies its own personality mid-conversation.

ADR-002: the tag IS the clean symbolic DECISION; the EXECUTOR (write_state -> persona.md) applies it.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, Tuple

from harness.personality.persona_file import parse_persona, write_state

_MOOD = re.compile(r"\[MOOD:([^\]]+)\]")
_VOICE = re.compile(r"\[VOICE:([^\]]+)\]")
_TRAIT = re.compile(r"\[TRAIT:([+-]?)([^\]]+)\]")
_STRIP = re.compile(r"\[(?:MOOD|VOICE|TRAIT):[^\]]+\]")


def _persona_path() -> str:
    return os.environ.get("SP_PERSONA_FILE") or os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "persona.md")


def apply_personality_tags(reply: str, persona_path: str = "") -> Tuple[str, Dict[str, str]]:
    """Persist [MOOD]/[VOICE]/[TRAIT] tags from a reply into the persona state; return the tag-
    STRIPPED reply + the resulting state. `[TRAIT:+x]` adds, `[TRAIT:-x]` removes, `[TRAIT:x]` adds.
    Best-effort: any error leaves the reply stripped and the state untouched."""
    path = persona_path or _persona_path()
    changed = False
    try:
        text = Path(path).read_text(encoding="utf-8") if Path(path).exists() else ""
        _, state = parse_persona(text)
        moods = _MOOD.findall(reply)
        if moods:
            state["mood"] = moods[-1].strip(); changed = True
        voices = _VOICE.findall(reply)
        if voices:
            state["voice"] = voices[-1].strip(); changed = True
        traits = [t.strip() for t in state.get("traits", "").split(",") if t.strip()]
        for sign, raw in _TRAIT.findall(reply):
            name = raw.strip()
            if not name:
                continue
            if sign == "-":
                traits = [t for t in traits if t.lower() != name.lower()]
            elif name.lower() not in (t.lower() for t in traits):
                traits.append(name)
            changed = True
        if traits:
            state["traits"] = ", ".join(traits)
        if changed:
            write_state(path, state)
        result_state = {k: state.get(k, "") for k in ("voice", "mood", "traits")}
    except Exception:
        result_state = {}
    clean = _STRIP.sub("", reply).strip()
    return clean, result_state


# ── the interceptor (thin wrapper; import the base lazily so this module stays light) ──
def make_interceptor():
    """Return a PersonalityStateInterceptor instance wired to the governance pipeline."""
    from harness.mcp.comms_framework import InterceptorBase

    class PersonalityStateInterceptor(InterceptorBase):
        name = "personality_state"
        priority = 72  # post-call, before ResponseShaper (80)

        def post_call(self, ctx) -> None:  # ResponseContext (dict subclass; reply is an attr)
            reply = getattr(ctx, "reply", "") or ""
            if not reply:
                return
            clean, _ = apply_personality_tags(reply)
            try:
                ctx.reply = clean
            except Exception:
                pass

    return PersonalityStateInterceptor()
