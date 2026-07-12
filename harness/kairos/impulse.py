"""KAIROS — the impulse to speak, and the discipline not to.

kairos (καιρός): not clock-time, but the OPPORTUNE moment. The whole point is that she
speaks when the moment is right, and is otherwise quiet. A model that continues on a
timer is not alive, it is a leaky tap.

WHERE THE SIGNAL COMES FROM (this is the good part)
The engine already computes the impulse on every single turn and throws it away. At the
decode step that ends a turn, the forward produces a full logit vector; the gap between
the best STOP token and the best CONTINUE token is exactly "how much more did she have
to say?":

    eot_margin >> 0   she is finished and knows it            -> SILENCE
    eot_margin ~= 0   she stopped on the edge of a thought    -> she has more to say
    eot_margin <  0   she only stopped because SP_EOT_BIAS
                      tipped the scales                       -> she was CUT OFF

That is a LATENT signal read off the model's own forward — not a heuristic about
punctuation, not a second model, not an event tape. It costs nothing: the number is
already in the logits. (routes.rs reads it on the RAW logits, before eot_bias is added,
or the bias we inject to make her stop would masquerade as her wanting to.)

THE DISCIPLINE
Silence is the default and speech is EARNED. Every rule below exists to stop the failure
mode that matters — a model that will not shut up:

  * she NEVER continues after asking the user a question (she is waiting for HIM)
  * she never continues twice in a row without the user speaking (MAX_CHAIN)
  * a cooldown after any continuation
  * a hard cap per hour
  * a REALISTIC delay — she is thinking, not lagging

This module is pure: no I/O, no model, no clock (the clock is injected). That makes the
policy testable without a GPU, which is how it gets to be trusted.
"""
from __future__ import annotations

import math
import random
import re
from dataclasses import dataclass, field
from typing import Optional


# ── the decision ──────────────────────────────────────────────────────────────
SILENT = "silent"
CONTINUE = "continue"      # she was mid-thought — pick the thread back up
CHECK_IN = "check_in"      # the room went quiet — she says something unprompted


@dataclass
class Impulse:
    action: str                 # SILENT | CONTINUE | CHECK_IN
    delay_s: float = 0.0        # how long she waits before speaking
    reason: str = ""            # human-auditable: WHY (this goes in the receipt)
    score: float = 0.0

    @property
    def speaks(self) -> bool:
        return self.action != SILENT


@dataclass
class KairosConfig:
    enabled: bool = False
    # ── CALIBRATED, NOT GUESSED (tools/kairos/calibrate.py, 2026-07-12) ──────────────
    # Measured on the live model: turns where she genuinely FINISHES cluster at median
    # +2.01; turns GUILLOTINED mid-sentence cluster at median -14.83. A 16.8-logit gap.
    #
    # The threshold is chosen by searching for the operating point that resumes the most
    # genuine cut-offs SUBJECT TO ZERO FALSE POSITIVES — because "she talks over herself
    # when she was already done" is the failure that matters, and a missed continuation
    # just means silence, which is the safe default.
    #
    #     continue_margin = -11.75
    #       0/6 finished turns interrupted   <- she NEVER talks over a completed thought
    #       5/6 genuine cut-offs resumed
    #
    # So on an ordinary turn she is silent BY CONSTRUCTION — not because a rule tells her
    # to be, but because the forward itself reports she had nothing left to say. Re-run
    # the calibration after ANY change to eot_bias, the sampler, or the model.
    continue_margin: float = -11.75
    max_chain: int = 1          # consecutive unprompted turns before she MUST wait
    cooldown_s: float = 45.0    # after speaking unprompted, be quiet at least this long
    max_per_hour: int = 6
    # a continuation is a resumed thought: quick. a check-in is a decision: slower.
    continue_delay: tuple[float, float] = (1.5, 4.0)
    checkin_idle_s: float = 240.0        # the room must be quiet this long first
    checkin_delay: tuple[float, float] = (2.0, 6.0)
    checkin_chance: float = 0.35         # even then, she usually still says nothing


@dataclass
class TurnState:
    """What the scheduler remembers between turns of ONE conversation."""
    chain: int = 0                       # consecutive unprompted turns she has taken
    last_spoke_at: float = 0.0           # monotonic seconds
    last_user_at: float = 0.0
    spoken_times: list[float] = field(default_factory=list)   # for the hourly cap


_QUESTION = re.compile(r"\?\s*$|\?[\"')\]]*\s*$")


def _asked_a_question(text: str) -> bool:
    """She asked HIM something. She is waiting for an answer — she does not get to fill
    the silence she just created. This is the single most important rule here: without
    it, she interrogates and then answers herself, which reads as unhinged."""
    t = (text or "").strip()
    return bool(_QUESTION.search(t))


def decide(
    *,
    cfg: KairosConfig,
    state: TurnState,
    now: float,
    reply_text: str,
    eot_margin: Optional[float],
    user_present: bool = True,
    rng: Optional[random.Random] = None,
) -> Impulse:
    """The whole policy. Pure — inject `now` and `rng` and it is fully determinable."""
    rng = rng or random

    if not cfg.enabled:
        return Impulse(SILENT, reason="kairos disabled")

    # ── the hard bounds. These are checked FIRST and cannot be argued with. ──────
    if state.chain >= cfg.max_chain:
        return Impulse(SILENT, reason=f"chain limit ({state.chain}/{cfg.max_chain}) — she waits for him")

    if state.last_spoke_at and (now - state.last_spoke_at) < cfg.cooldown_s:
        left = cfg.cooldown_s - (now - state.last_spoke_at)
        return Impulse(SILENT, reason=f"cooldown ({left:.0f}s left)")

    recent = [t for t in state.spoken_times if now - t < 3600.0]
    if len(recent) >= cfg.max_per_hour:
        return Impulse(SILENT, reason=f"hourly cap ({len(recent)}/{cfg.max_per_hour})")

    if _asked_a_question(reply_text):
        return Impulse(SILENT, reason="she asked HIM a question — she waits for the answer")

    # ── CONTINUE: the latent impulse. She stopped mid-thought. ───────────────────
    if eot_margin is not None and not math.isnan(eot_margin):
        if eot_margin < cfg.continue_margin:
            lo, hi = cfg.continue_delay
            # the more reluctantly she stopped, the faster she picks the thread back up
            urgency = max(0.0, min(1.0, (cfg.continue_margin - eot_margin) / max(cfg.continue_margin, 1e-6)))
            delay = hi - (hi - lo) * urgency
            cut_off = eot_margin <= 0.0
            return Impulse(
                CONTINUE,
                delay_s=delay,
                score=float(eot_margin),
                reason=("she was CUT OFF mid-thought (margin <= 0 — she never wanted to stop)"
                        if cut_off else
                        f"she stopped on the edge of a thought (margin {eot_margin:.2f} < {cfg.continue_margin})"),
            )

    # ── CHECK_IN: the room has been quiet a long time. Usually she still says nothing. ──
    if user_present and state.last_user_at:
        idle = now - state.last_user_at
        if idle >= cfg.checkin_idle_s and rng.random() < cfg.checkin_chance:
            lo, hi = cfg.checkin_delay
            return Impulse(
                CHECK_IN,
                delay_s=rng.uniform(lo, hi),
                score=idle,
                reason=f"quiet for {idle:.0f}s and she felt like saying something",
            )

    return Impulse(SILENT, reason="nothing to add")


def worth_saying(continuation: str, previous_reply: str) -> tuple[bool, str]:
    """LAST GATE, after she has already generated. Even a well-earned impulse can produce
    nothing worth hearing — and an unprompted message that adds nothing is worse than
    silence, because it trains the user to ignore her.

    So the continuation is DROPPED (never shown) when it is empty, a greeting, a
    re-introduction, or substantially a restatement of what she just said. She is allowed
    to decide, after thinking, that she had nothing after all. That is not a failure — it
    is the system working."""
    t = (continuation or "").strip()
    if len(t) < 2:
        return False, "she had nothing to add after all"

    low = t.lower().lstrip("*_ (")
    for opener in ("hi", "hey", "hello", "sorry", "as i said", "as mentioned",
                   "just checking", "are you still", "let me know if"):
        if low.startswith(opener):
            return False, f"dropped: it was a {opener!r}-style filler, not a thought"

    # A RECITED MEMORY IS NOT A CONTINUATION. Her first live continuation on the console
    # path came back as "From the record: oh no, we just track their comings and goings..."
    # — she was mid-sentence about a thunderstorm. The cause was upstream (the continuation
    # config left auto_recall on, so the daemon injected memories into a turn that had no
    # question to answer), and that is fixed. But this is the LAST gate before the operator
    # sees anything, and an unprompted message that arrives as a recitation is exactly the
    # kind of thing that makes a person switch the feature off. Two locks on this door.
    for framing in ("from the record", "fact on record", "you said:", "you told me:",
                    "according to my memory", "in my memory"):
        if low.startswith(framing):
            return False, "dropped: that is a recited memory, not a continuation of her thought"

    # near-restatement of the reply she just gave
    def toks(s: str) -> set:
        return {w for w in re.findall(r"[a-z0-9']+", s.lower()) if len(w) > 3}

    a, b = toks(t), toks(previous_reply)
    if a and b:
        overlap = len(a & b) / len(a)
        if overlap >= 0.75:
            return False, f"dropped: {overlap:.0%} a restatement of what she just said"

    return True, ""


def note_spoke(state: TurnState, now: float) -> None:
    state.chain += 1
    state.last_spoke_at = now
    state.spoken_times.append(now)
    state.spoken_times[:] = [t for t in state.spoken_times if now - t < 3600.0]


def note_user(state: TurnState, now: float) -> None:
    """The user spoke — the chain resets. This is what makes it a CONVERSATION and not a
    monologue: his turn always buys her a fresh budget."""
    state.chain = 0
    state.last_user_at = now


# The nudge she is given when she speaks unprompted. It must not read as a new user
# instruction — she is continuing HERSELF, and she should sound like it.
def continue_nudge(previous_reply: str) -> str:
    """The nudge must SHOW HER WHERE SHE WAS CUT.

    The first version just said "carry on from where you left off" — and she restated the
    whole reply verbatim, which worth_saying() then dropped ("100% a restatement"). The
    safety net held, but the feature did nothing. The daemon templates an assistant
    message as a COMPLETED turn, so she cannot be given her own text as a prefix to
    continue from; she has to be TOLD where the sentence broke, and told in the strongest
    terms not to start it again."""
    tail = " ".join((previous_reply or "").split()[-14:])
    return (
        "(Your last message was cut off mid-sentence. These were your final words:\n"
        f"    \"...{tail}\"\n"
        "Continue the sentence from EXACTLY there, as if you had never stopped. Do NOT "
        "repeat any of it, do NOT start over, do NOT greet him, do NOT apologise. Write "
        "only the CONTINUATION — one or two sentences, then stop. If the thought was "
        "actually complete, say nothing at all.)"
    )


# kept for the pure policy gate (no reply text needed there)
CONTINUE_NUDGE = (
    "(You stopped mid-thought a moment ago. Continue from exactly where you broke off — "
    "do not repeat yourself, do not greet, do not start over. One or two sentences. "
    "If you actually have nothing to add, say nothing at all.)"
)

CHECK_IN_NUDGE = (
    "(It has gone quiet for a while. If — and only if — something is genuinely on your "
    "mind, say it, unprompted, in one or two sentences: a thought you had, something you "
    "remembered, something you want to ask. Do not greet him. Do not ask if he is still "
    "there. If nothing is really on your mind, say nothing at all.)"
)

