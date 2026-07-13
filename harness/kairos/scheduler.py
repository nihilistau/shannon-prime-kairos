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
    CHECK_IN, CONTINUE, REMIND, MUSE, CHECK_IN_NUDGE, continue_nudge, remind_nudge,
    muse_nudge,
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


# ── REFLECTION ON THE CLOCK (2026-07-13) ─────────────────────────────────────
#
# THINKING IS NOT SPEAKING, and keeping them apart is the whole design.
#
# She reflects SILENTLY whenever the room has been still long enough: she reads what she
# knows about him and writes down what she has come to believe. That happens whether or not
# he ever hears about it — it is how the model of him gets built, and most of what she
# concludes should simply become part of what she knows, unremarked. A person who told you
# every single thing they had ever noticed about you would be unbearable.
#
# Only a genuinely SURPRISING conclusion earns an interruption (reflect.speak_bits). The bar
# is not "did she think of something" — she thinks on a clock, she will always have thought
# of something. The bar is whether the model itself did not see it coming, which is the one
# property of a conclusion that cannot be faked.
#
# NO NEW EVIDENCE, NO NEW THINKING. If nothing has been added to the store since the last
# reflection, she does not run: re-reading the same facts just re-derives the same
# conclusion and presents it as a discovery. (Reinforcement makes that harmless in the
# STORE — a re-derived belief strengthens rather than duplicating — but it would be deadly
# in the CHANNEL, where the same thought arriving twice is how a companion becomes a bore.)
_LAST_REFLECT_AT: float = 0.0
_LAST_EVIDENCE: int = -1
_PENDING_INSIGHT: dict = {}


def _evidence_count() -> int:
    """How much she has been TOLD — not how much she has CONCLUDED.

    ── A REFLECTION IS A CONCLUSION, NOT AN OBSERVATION (2026-07-14) ────────────────────
    This used to be `len(_load())`: every row in the store, including her own reflections.

    And `insight()` WRITES ROWS. So the sequence was:

        ev = evidence_count()          # 46
        if ev == last_evidence: return # "nothing new to think about"
        last_evidence = ev             # 46
        insight()                      # <-- writes 2 rows. The store is now 48.

    ...and on the next tick the count is 48, which is "new evidence", so she reflects again —
    ON HER OWN REFLECTIONS. The gate that was supposed to mean "has he told me anything?"
    actually meant "has the store changed?", and she is part of the store.

    It never spun (the 30-minute cooldown bounded it). IT JUST DRIFTED. Each pass took her
    conclusions as fresh input and concluded something about them, and from the outside that
    reads as "the model has got a bit weird lately" — which is unfalsifiable, gets blamed on
    the weights, and is nearly impossible to see from a transcript.

    DERIVING A BELIEF FROM EVIDENCE MUST NOT CREATE EVIDENCE.

    Evidence is what HE said and what the WORLD did. Never what SHE concluded. A system whose
    inferences re-enter its own input is not learning, it is compounding — and the only thing
    that compounds is its own certainty.

    (The same shape as `_capture_after_turn` storing tool RESULTS as facts about him — she ate
    her own exhaust. It is the third time this exact loop has appeared in this codebase, which
    is why it gets a named rule rather than a fix.)
    """
    try:
        from harness.skills.memory import _load
        return sum(1 for r in _load() if _is_evidence(r))
    except Exception:
        return -1


def _is_evidence(row: dict) -> bool:
    """Is this row something the WORLD told her, or something SHE decided?

    ── src IS AN AUDIT TRAIL, NOT A CLAIM STATUS, AND I NEARLY SHIPPED A GATE THAT TRUSTED IT ──
    My first cut tested `src not in ("reflection", "insight")`. It passed — because exactly ONE
    row in the live store happens to have src EXACTLY "reflection". Here is what src actually
    holds:

        'user turn'                                     30
        'rescued from ep_live_m1783826444872'            1
        'user turn | repair: un-retired (2026-07-12)'    1
        ' | cleanup: stamped speaker=user'               9
        'reflection'                                     1

    It is FREE-TEXT PROVENANCE PROSE that gets appended to over time. The moment a reflection row
    is touched by a cleanup pass it becomes "reflection | cleanup: ...", the exact-match fails,
    and the row silently becomes EVIDENCE again — reopening the self-feeding loop this function
    exists to close. The gate would not error. It would just quietly stop working, months later,
    because of a maintenance script.

    So: check the STRUCTURED field (speaker) first, and treat src as a fuzzy hint, not a key.
    A field that is a paragraph is not a field you can branch on.

    (This is why the store needs a real claim status — candidate/observed/inferred/confirmed —
    as a first-class enum, instead of inferring epistemics from prose. Filed as its own task;
    this is the hardening that makes today's fix survive until then.)
    """
    if (row.get("speaker") or "user") == "self":
        return False                       # her own voice is not news from the world
    src = (row.get("src") or "").lower()
    if "reflection" in src or "insight" in src:
        return False                       # a conclusion is not an observation
    return True


def reflect_tick(now: Optional[float] = None) -> Optional[dict]:
    """Think about him, quietly. Returns an insight worth SAYING, or None (usually None)."""
    global _LAST_REFLECT_AT, _LAST_EVIDENCE
    from harness.tuning import registry as tune
    if not bool(tune.get("reflect.enabled")):
        return None

    now = now if now is not None else time.monotonic()
    idle_s = float(tune.get("reflect.idle_s"))
    cool_s = float(tune.get("reflect.cooldown_s"))

    with _LOCK:
        # the room must be still — reflection is a whole model turn and must never race him
        # for the GPU while he is mid-sentence
        last_user = max((st.last_user_at for st in _STATE.values()), default=0.0)
        if not last_user or (now - last_user) < idle_s:
            return None
        if _LAST_REFLECT_AT and (now - _LAST_REFLECT_AT) < cool_s:
            return None
        ev = _evidence_count()
        if ev == _LAST_EVIDENCE:
            return None                       # nothing new to think ABOUT
        _LAST_REFLECT_AT, _LAST_EVIDENCE = now, ev

    try:
        from harness.maintenance import ops
        from harness.model.person import PersonModel
        res = ops.insight()
    except Exception as exc:
        logger.warning("[kairos] reflection failed: %s", exc)
        return None

    # 1. HAS SOMETHING GONE QUIET? The neighbour who did not wave carries more information
    #    than the one who did, and noticing it is not retrieval — nobody asked a question.
    try:
        pm = PersonModel.from_registry()
        sil = pm.silences()
        if sil and sil[0]["bits"] >= float(tune.get("reflect.speak_bits")):
            logger.info("[kairos] reflection: a silence worth asking about (%.1f bits)",
                        sil[0]["bits"])
            return {"text": sil[0]["claim"], "bits": sil[0]["bits"], "silence": sil[0]}
    except Exception:
        pass

    # 2. Otherwise: did she CONCLUDE anything, and was it surprising enough to interrupt for?
    wrote = res.get("wrote") or []
    if not wrote:
        logger.info("[kairos] reflected — nothing new concluded")
        return None
    # a REINFORCED belief is one she already held; it is stronger now, but it is not NEWS
    fresh = [w for w in wrote if "-> stored" in w]
    if not fresh:
        logger.info("[kairos] reflected — only re-derived what she already believed")
        return None

    text = fresh[0].split(" -> ")[0].strip()
    try:
        bits = PersonModel.from_registry().surprisal(text)
    except Exception:
        bits = 0.0
    floor = float(tune.get("reflect.speak_bits"))
    if bits < floor:
        logger.info("[kairos] reflected and kept it to herself (%.1f < %.1f bits): %r",
                    bits, floor, text[:50])
        return None
    logger.info("[kairos] reflection worth saying (%.1f bits): %r", bits, text[:60])
    return {"text": text, "bits": bits}


def _watch_tick() -> None:
    """SHE ACTUALLY LOOKS. On the same clock she thinks on.

    "I will look out for a 3090 GPU to be available."  — and then nothing looked.

    This is what makes that sentence true. A watch that fires becomes an ordinary due
    reminder, so it arrives through the path that is already gated and already bounded: she
    tells him once, with the evidence, and does not nag. The promise and the keeping of it
    now run on the same rails as every other promise she makes."""
    try:
        from harness.skills import watch as W
        due = W.due_checks()
        if not due:
            return
        note = due[0]                       # one per tick: this costs a search and a turn
        res = W.check(note)
        if res.get("fired"):
            # A FIRED WATCH IS A DUE REMINDER. Give it a due date of NOW and the existing
            # REMIND path — bounded, once, with a reason — carries it the rest of the way.
            from harness.skills import notes as N
            N.update(note["id"], due_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                     raised=False)
            logger.info("[watch] %r fired — it is now a due reminder", note.get("title"))
    except Exception as exc:
        logger.warning("[watch] tick failed: %s", exc)


def _due_notes() -> list:
    """Reminders that have come due and have not been raised yet. Kept out of impulse.py so
    the policy stays pure and gateable without a store."""
    try:
        from harness.skills import notes as N
        return N.due()
    except Exception:
        return []


def _arm(session, imp, reply_text, generate, margin, notes=None, insight=None) -> None:
    """Wait the delay, generate, and let worth_saying() have the last word."""
    def _fire():
        # the CONTINUE nudge is built from the reply so she can see WHERE she was cut —
        # without the tail she just restates the whole thing and worth_saying() drops it.
        if imp.action == CONTINUE:
            nudge = continue_nudge(reply_text)
        elif imp.action == REMIND:
            nudge = remind_nudge(notes or [])
        elif imp.action == MUSE:
            nudge = muse_nudge(insight or {})
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

    # SHE LOOKS AT THE WORLD FOR HIM. due_checks() is cheap and network-free; it only
    # reaches the web when a watch is actually stale (every 6h by default), so this costs
    # nothing on the overwhelming majority of ticks.
    _watch_tick()

    due = _due_notes()          # THE CLOCK IS WHAT MAKES A REMINDER POSSIBLE AT ALL.

    # SHE THINKS ON THE SAME CLOCK SHE SPEAKS ON, but they are not the same act. reflect_tick
    # writes what she concludes into the store REGARDLESS; it returns something here only on
    # the rare occasion the conclusion was surprising enough to be worth interrupting him
    # for. Most reflections end in her simply knowing something new and saying nothing.
    insight = None
    try:
        insight = reflect_tick(now)
    except Exception as exc:
        logger.warning("[kairos] reflect_tick: %s", exc)

    with _LOCK:
        sessions = list(_LAST.items())
    for session, (reply_text, generate) in sessions:
        with _LOCK:
            st = _STATE[session]
            if _TIMERS.get(session) and _TIMERS[session].is_alive():
                continue                       # she is already about to say something
            imp = decide(cfg=cfg, state=st, now=now,
                         reply_text=reply_text, eot_margin=None, due_notes=due,
                         insight=insight)
        if not imp.speaks:
            continue
        logger.info("[kairos] session=%s idle tick -> %s (%s)", session, imp.action, imp.reason)
        _arm(session, imp, reply_text, generate, None,
             notes=due if imp.action == REMIND else None,
             insight=insight if imp.action == MUSE else None)
        if imp.action in (REMIND, MUSE):
            break              # one session hears it, not every open tab


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

