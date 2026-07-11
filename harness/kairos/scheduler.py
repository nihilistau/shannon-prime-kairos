"""KAIROS SCHEDULER — the thing that actually lets her speak, and mostly stops her.

Sits on the gateway's turn boundary. After every reply:

    1. read the turn's continuation impulse (eot_margin, straight from the forward)
    2. ask the policy (harness/kairos/impulse.py) — which says SILENT almost always
    3. if it says otherwise, WAIT the realistic delay, then generate the continuation
    4. run the last gate: worth_saying(). A continuation that is a greeting, a
       re-introduction, or a restatement is DROPPED and never reaches the operator.
    5. only what survives all four goes in the session's OUTBOX, which the console polls

Steps 4 and 5 matter as much as 1-3. An unprompted message that adds nothing is worse
than silence: it teaches the operator to ignore her. She is allowed to think, and then
decide she had nothing after all.

All knobs are read LIVE from the tuning registry on every turn, so the operator can move
kairos.max_chain or kairos.continue_margin in the UI and the next turn obeys it — no
restart. Config that requires a restart is config nobody tunes.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict, deque
from typing import Any, Callable, Optional

from harness.kairos.impulse import (
    CHECK_IN, CONTINUE, CHECK_IN_NUDGE, continue_nudge,
    Impulse, KairosConfig, TurnState, decide, note_spoke, note_user, worth_saying,
)
from harness.tuning import registry as tune

logger = logging.getLogger(__name__)

_LOCK = threading.RLock()
_STATE: dict[str, TurnState] = defaultdict(TurnState)
_OUTBOX: dict[str, deque] = defaultdict(deque)
_TIMERS: dict[str, threading.Timer] = {}


def live_config() -> KairosConfig:
    """Read the knobs fresh, every turn. The UI is the source of truth."""
    return KairosConfig(
        enabled=bool(tune.get("kairos.enabled")),
        continue_margin=float(tune.get("kairos.continue_margin")),
        max_chain=int(tune.get("kairos.max_chain")),
        cooldown_s=float(tune.get("kairos.cooldown_s")),
        max_per_hour=int(tune.get("kairos.max_per_hour")),
        checkin_idle_s=float(tune.get("kairos.checkin_idle_s")),
        checkin_chance=float(tune.get("kairos.checkin_chance")),
    )


def on_user_turn(session: str) -> None:
    """He spoke. Her chain resets — that is what makes this a conversation."""
    with _LOCK:
        note_user(_STATE[session], time.monotonic())
        t = _TIMERS.pop(session, None)
    if t:
        t.cancel()          # he spoke while she was waiting to continue — she yields to him


def on_reply(
    session: str,
    reply_text: str,
    kairos_payload: Optional[dict],
    generate: Callable[[str], str],
) -> Optional[Impulse]:
    """Called after each assistant reply. `generate(nudge)` runs one more turn with the
    nudge appended and returns her text. Returns the Impulse (for the receipt/telemetry)."""
    cfg = live_config()
    if not cfg.enabled:
        return None

    margin = None
    if kairos_payload:
        margin = kairos_payload.get("eot_margin")

    now = time.monotonic()
    with _LOCK:
        st = _STATE[session]
        imp = decide(cfg=cfg, state=st, now=now, reply_text=reply_text, eot_margin=margin)

    logger.info("[kairos] session=%s margin=%s -> %s (%s)",
                session, f"{margin:.2f}" if isinstance(margin, float) else margin,
                imp.action, imp.reason)
    if not imp.speaks:
        return imp

    def _fire():
        # the CONTINUE nudge is built from the reply so she can see WHERE she was cut —
        # without the tail she just restates the whole thing and worth_saying() drops it.
        nudge = continue_nudge(reply_text) if imp.action == CONTINUE else CHECK_IN_NUDGE
        try:
            text = (generate(nudge) or "").strip()
        except Exception as exc:                      # never let a continuation break the app
            logger.warning("[kairos] continuation failed: %s", exc)
            return
        ok, why = worth_saying(text, reply_text)
        if not ok:
            logger.info("[kairos] DROPPED: %s :: %r", why, text[:60])
            return
        with _LOCK:
            note_spoke(_STATE[session], time.monotonic())
            _OUTBOX[session].append({
                "text": text,
                "kind": imp.action,
                "reason": imp.reason,
                "margin": margin,
                "at": time.time(),
            })
        logger.info("[kairos] SPOKE (%s): %r", imp.action, text[:70])

    with _LOCK:
        t = threading.Timer(imp.delay_s, _fire)
        t.daemon = True
        _TIMERS[session] = t
        t.start()
    return imp


def drain(session: str) -> list[dict]:
    """The console polls this. Returns and clears anything she has decided to say."""
    with _LOCK:
        out = list(_OUTBOX[session])
        _OUTBOX[session].clear()
    return out


def peek_state(session: str) -> dict:
    """For the operator panel: why is she quiet right now?"""
    cfg = live_config()
    now = time.monotonic()
    with _LOCK:
        st = _STATE[session]
        recent = len([t for t in st.spoken_times if now - t < 3600.0])
        cooling = max(0.0, cfg.cooldown_s - (now - st.last_spoke_at)) if st.last_spoke_at else 0.0
        return {
            "enabled": cfg.enabled,
            "chain": st.chain,
            "max_chain": cfg.max_chain,
            "cooldown_left_s": round(cooling, 1),
            "spoken_last_hour": recent,
            "max_per_hour": cfg.max_per_hour,
            "pending": len(_OUTBOX[session]),
        }

