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
    CHECK_IN, CONTINUE, REMIND, CHECK_IN_NUDGE, continue_nudge, remind_nudge,
    Impulse, KairosConfig, TurnState, decide, note_spoke, note_user, worth_saying,
)
from harness.tuning import registry as tune

logger = logging.getLogger(__name__)

_LOCK = threading.RLock()
_STATE: dict[str, TurnState] = defaultdict(TurnState)
_OUTBOX: dict[str, deque] = defaultdict(deque)
_TIMERS: dict[str, threading.Timer] = {}

# THE LAST TURN, PER SESSION — her reply, and the closure that can run one more turn on
# that conversation. The idle ticker needs both: to check in, she has to be able to SPEAK,
# and speaking means generating against the history she was last in.
_LAST: dict[str, tuple] = {}
_TICKER: Optional[threading.Thread] = None


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

    # REMEMBER THE TURN EVEN WHEN SHE IS SILENT — and even when kairos is off. The idle
    # ticker speaks against the last conversation, so it needs the closure regardless of
    # what this turn decided. Storing it only on the speaking path would mean she could
    # only ever check in after a turn she had already interrupted.
    with _LOCK:
        _LAST[session] = (reply_text, generate)

    if not cfg.enabled:
        return None

    margin = None
    if kairos_payload:
        margin = kairos_payload.get("eot_margin")

    now = time.monotonic()
    due = _due_notes()
    with _LOCK:
        st = _STATE[session]
        imp = decide(cfg=cfg, state=st, now=now, reply_text=reply_text,
                     eot_margin=margin, due_notes=due)

    logger.info("[kairos] session=%s margin=%s -> %s (%s)",
                session, f"{margin:.2f}" if isinstance(margin, float) else margin,
                imp.action, imp.reason)
    if not imp.speaks:
        return imp

    _arm(session, imp, reply_text, generate, margin, notes=due if imp.action == REMIND else None)
    return imp


def _due_notes() -> list:
    """Reminders that have come due and have not been raised yet. Kept out of impulse.py so
    the policy stays pure and gateable without a store."""
    try:
        from harness.skills import notes as N
        return N.due()
    except Exception:
        return []


def _arm(session, imp, reply_text, generate, margin, notes=None) -> None:
    """Wait the delay, generate, and let worth_saying() have the last word."""
    def _fire():
        # the CONTINUE nudge is built from the reply so she can see WHERE she was cut —
        # without the tail she just restates the whole thing and worth_saying() drops it.
        if imp.action == CONTINUE:
            nudge = continue_nudge(reply_text)
        elif imp.action == REMIND:
            nudge = remind_nudge(notes or [])
        else:
            nudge = CHECK_IN_NUDGE
        try:
            text = (generate(nudge) or "").strip()
        except Exception as exc:                      # never let a continuation break the app
            logger.warning("[kairos] continuation failed: %s", exc)
            return

        # A REMINDER IS NOT SUBJECT TO worth_saying(). That gate exists to let her decide,
        # after thinking, that she had nothing worth saying — and that freedom is right for
        # a continuation or a check-in. It is WRONG here: he asked to be reminded, and a
        # reminder she talked herself out of is a broken promise that looks exactly like a
        # bug. She still chooses the words; she does not get to choose silence.
        if imp.action != REMIND:
            ok, why = worth_saying(text, reply_text)
            if not ok:
                logger.info("[kairos] DROPPED: %s :: %r", why, text[:60])
                return
        elif not text:
            # she produced nothing at all — say it plainly rather than drop the promise
            titles = ", ".join((n.get("title") or "") for n in (notes or [])[:3])
            text = f"Reminder: {titles}."

        with _LOCK:
            note_spoke(_STATE[session], time.monotonic())
            _OUTBOX[session].append({
                "text": text,
                "kind": imp.action,
                "reason": imp.reason,
                "margin": margin,
                "notes": [n.get("id") for n in (notes or [])],
                "at": time.time(),
            })

        # SHE REMINDS; SHE DOES NOT NAG. Marked only AFTER it actually reached the outbox,
        # so a reminder that failed to generate is still owed and will fire on a later tick.
        if imp.action == REMIND:
            try:
                from harness.skills import notes as N
                for n in (notes or []):
                    N.mark_raised(n.get("id"))
            except Exception as exc:
                logger.warning("[kairos] could not mark reminder raised: %s", exc)

        logger.info("[kairos] SPOKE (%s): %r", imp.action, text[:70])

    with _LOCK:
        t = threading.Timer(imp.delay_s, _fire)
        t.daemon = True
        _TIMERS[session] = t
        t.start()


# ── THE IDLE TICK (2026-07-12) ────────────────────────────────────────────────
# CHECK_IN was unreachable code. decide() has a whole branch for it — "the room has been
# quiet a long time" — and the only caller of decide() was on_reply(), which fires the
# instant a reply is produced, i.e. moments after HE spoke. So `idle = now - last_user_at`
# was always ~0, and `idle >= checkin_idle_s` (240s) could never be true. The knobs were on
# the operator panel; the policy was gated pure and correct; the branch could not run.
#
# That is the "she ticks turns noop" the operator named at the outset: the system had a
# heartbeat everywhere except where it needed one. Silence is not an event, so nothing
# generated it — and a thing that can only act when spoken to cannot notice a quiet room.
# It needs a clock of its own.
#
# The tick is cheap: it asks the POLICY, not the model. It reaches the model only if the
# policy says speak — and the policy says SILENT almost always (240s of quiet, then a 35%
# roll, then the cooldown, the hourly cap and the chain limit all still apply).
def tick_once(now: Optional[float] = None) -> None:
    cfg = live_config()
    if not cfg.enabled:
        return
    now = now if now is not None else time.monotonic()
    due = _due_notes()          # THE CLOCK IS WHAT MAKES A REMINDER POSSIBLE AT ALL.
    with _LOCK:
        sessions = list(_LAST.items())
    for session, (reply_text, generate) in sessions:
        with _LOCK:
            st = _STATE[session]
            if _TIMERS.get(session) and _TIMERS[session].is_alive():
                continue                       # she is already about to say something
            imp = decide(cfg=cfg, state=st, now=now,
                         reply_text=reply_text, eot_margin=None, due_notes=due)
        if not imp.speaks:
            continue
        logger.info("[kairos] session=%s idle tick -> %s (%s)", session, imp.action, imp.reason)
        _arm(session, imp, reply_text, generate, None,
             notes=due if imp.action == REMIND else None)
        if imp.action == REMIND:
            break              # one session gets the reminder, not every open tab


def start_ticker(period_s: float = 15.0) -> None:
    """One clock for the whole gateway. Idempotent."""
    global _TICKER
    with _LOCK:
        if _TICKER and _TICKER.is_alive():
            return

        def _loop():
            while True:
                time.sleep(period_s)
                try:
                    tick_once()
                except Exception as exc:
                    logger.warning("[kairos] tick failed: %s", exc)

        _TICKER = threading.Thread(target=_loop, name="kairos-tick", daemon=True)
        _TICKER.start()
        logger.info("[kairos] idle ticker started (every %.0fs)", period_s)


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

