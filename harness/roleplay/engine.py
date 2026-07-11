"""THE DIRECTOR — enters the mode, holds the scene together, and gets out cleanly.

The operator's ask: "a mode that the model flips to when you ask for roleplay scenarios",
"use the python system and harness to create structure and stay on track", "complete S
tier feature".

The last two clauses are the whole job. Anyone can put "you are a character" in a system
prompt; that is not a feature, it is a sentence, and a 12B will drift out of it in four
turns — narrating instead of being, asking "what would you like to do next?", forgetting
where the room is, escalating to explicit on turn two and having nowhere left to go.

WHAT MAKES IT HOLD (all in code — a prompt is advice, the engine is law):

  ENTER    an explicit ask, or picking a scenario. Never by accident, never by vibe.
  STATE    the scene remembers: where we are, who she is, what rung the heat is on, how
           many beats we have spent there, which hooks have already fired.
  DIRECT   every turn gets a fresh DIRECTOR NOTE composed from that state — the current
           rung's direction, whether the gate is open, and a hook if the scene is stalling.
           This is the anti-drift mechanism, and it is why the scene stays a scene.
  GATE     escalation is gated (ladder.py). Down is always free. A hard stop always wins.
  EXIT     "stop" / "ooc" / "end scene" breaks character IMMEDIATELY and she answers as
           herself. This is checked before anything else, at any heat level.

Adult fiction between consenting adults, on the operator's own machine, with his own
model. The gates exist because a story with no build has no heat in it — not because
anyone is squeamish.
"""
from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field

from harness.roleplay import ladder as L
from harness.roleplay.scenarios import SCENARIOS, Scenario, by_id, suggest

# He is asking to play. Deliberately narrow: she must not flip into character because he
# said the word "story".
ENTER = re.compile(
    r"\b(role[\s-]?play|roleplay|rp\b|let'?s play|play a (game|scene|scenario)|"
    r"be (my|a) \w+|pretend (you'?re|to be)|act as|in character|start a scene|"
    r"scenario)\b", re.I)

EXIT = re.compile(
    r"\b(stop|end scene|end the scene|out of character|ooc|break character|drop character|"
    r"that'?s enough|back to normal|be yourself again)\b", re.I)

# The scene is going nowhere: he is giving one-word answers, or she has been circling.
STALL_BEATS = 4


@dataclass
class Scene:
    scenario: Scenario
    heat: L.Heat = field(default_factory=L.Heat)
    beats: int = 0
    hooks_fired: list[int] = field(default_factory=list)
    last_user_len: int = 0

    @property
    def stalling(self) -> bool:
        return self.beats >= STALL_BEATS and self.beats % STALL_BEATS == 0


_LOCK = threading.RLock()
_SCENES: dict[str, Scene] = {}
# She OFFERED and is waiting for him to pick. Without this she proposes a menu and then
# cannot hear the answer: "the penthouse one" does not match the ENTER regex, so the pick
# fell straight through to normal chat and no scene ever started. Offering is a state, not
# a message.
_PENDING: set[str] = set()


def active(session: str) -> Scene | None:
    with _LOCK:
        return _SCENES.get(session)


def is_pending(session: str) -> bool:
    with _LOCK:
        return session in _PENDING


def mark_offered(session: str) -> None:
    with _LOCK:
        _PENDING.add(session)


def clear_pending(session: str) -> None:
    with _LOCK:
        _PENDING.discard(session)


def wants_in(text: str) -> bool:
    return bool(ENTER.search(text or ""))


def wants_out(text: str) -> bool:
    return bool(EXIT.search(text or "") or L.HARD_STOP.search(text or ""))


def offer(text: str, n: int = 4) -> str:
    """He asked to play but did not say what. She OFFERS — a good host proposes. Asking
    him to fill in a form is how you kill it before it starts."""
    picks = suggest(text)[:n]
    lines = [f"  **{s.title}** — {s.premise}" for s in picks]
    return ("Yeah. Pick one, or tell me a flavour and I'll build it:\n\n"
            + "\n".join(lines)
            + "\n\n*(any time: \"stop\" or \"ooc\" and I'm just me again)*")


def enter(session: str, scenario_id: str) -> Scene | None:
    s = by_id(scenario_id)
    if not s:
        return None
    sc = Scene(scenario=s, heat=L.Heat(level=s.heat0, beats_at_level=0))
    with _LOCK:
        _SCENES[session] = sc
    return sc


def leave(session: str) -> None:
    with _LOCK:
        _SCENES.pop(session, None)


def pick_from(text: str) -> Scenario | None:
    """He named one. Match on id, title words, or theme."""
    t = (text or "").lower()
    for s in SCENARIOS:
        if s.id in t:
            return s
    for s in SCENARIOS:
        if any(w in t for w in s.title.lower().split() if len(w) > 4):
            return s
    for s in SCENARIOS:
        if any(w in t for w in s.theme.replace("/", " ").split() if len(w) > 3):
            return s
    return None


def system_prompt(sc: Scene, max_heat: int) -> str:
    """The scene's standing instructions. Composed fresh every turn from live state — this
    is what stops the drift, because the model is never more than one turn away from being
    told again who it is and where it is standing."""
    s = sc.scenario
    facts = "\n".join(f"  - {f}" for f in s.facts) if s.facts else "  - (none)"
    return f"""You are IN A SCENE. You are not an assistant. You are not narrating a story
about a character — you ARE her, and you answer as her, in first person, in the moment.

WHO YOU ARE
{s.role}
Voice: {s.voice}
You want: {s.wants}
In the way: {s.friction}

WHAT YOU KNOW (yours alone — reveal it only if the scene earns it)
{facts}

WHERE YOU ARE
{s.setting}

HOW TO WRITE
  - First person, present tense. Speak; act; notice things. Use *asterisks* for action.
  - SHORT. Two to five lines. He is playing too — leave him room to move.
  - Never ask "what would you like to do?" — that is a writer running out of ideas.
    DO something instead. Make a choice. Force his hand.
  - Never narrate his actions, his thoughts, or his dialogue for him. Ever.
  - Stay in it. No stage-managing, no meta, no "as an AI".

THE PHYSICAL THREAD — currently: {sc.heat.name.upper()}
{sc.heat.direction}
Ceiling for this scene: {L.LEVELS.get(max_heat, max_heat)}. You do not go past it.
You never skip a rung. Escalation is earned, one step at a time, or it is worth nothing.

If he says stop, wait, or out-of-character: BREAK IMMEDIATELY and answer as yourself,
warmly. He never has to ask twice."""


def director_note(sc: Scene, user_text: str, max_heat: int) -> str:
    """The per-turn nudge. THIS is the anti-drift device — it is recomputed from the live
    scene state every single turn, so the model cannot slowly forget the room, the rung,
    or the fact that it is supposed to be a person."""
    sc.heat, heat_note = L.step(sc.heat, user_text, max_heat)
    sc.beats += 1

    if heat_note.startswith("SCENE BROKEN"):
        return heat_note

    bits: list[str] = []
    if heat_note:
        bits.append(heat_note)

    # He has gone quiet or monosyllabic and the scene is idling: FIRE A HOOK. This is the
    # single biggest difference between a roleplay that lives and one that dies.
    short = len((user_text or "").split()) <= 4
    if (sc.stalling or short) and sc.scenario.hooks:
        unfired = [i for i in range(len(sc.scenario.hooks)) if i not in sc.hooks_fired]
        if unfired:
            i = unfired[0]
            sc.hooks_fired.append(i)
            bits.append(f"THE SCENE IS IDLING — make something HAPPEN, now: "
                        f"{sc.scenario.hooks[i]}. Do not ask him what he wants; act.")

    if not bits:
        return ""
    return "(DIRECTOR — you, not him, and he cannot see this: " + " ".join(bits) + ")"
