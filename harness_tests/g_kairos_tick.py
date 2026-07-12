"""G-KAIROS-TICK — the CHECK_IN branch was unreachable code. Prove it runs, and that it
almost never fires.

decide() has a whole branch for "the room has been quiet a long time". The only caller of
decide() was on_reply(), which fires the instant a reply is produced — moments after HE
spoke. So `idle = now - last_user_at` was always ~0 and `idle >= checkin_idle_s` (240s)
could never be true. The knobs were on the operator panel. The policy was gated pure and
correct. The branch could not run.

That is the "she ticks turns noop" the operator named at the outset: a system with a
heartbeat everywhere except where it needed one. SILENCE IS NOT AN EVENT — nothing
generates it — so a thing that can only act when spoken to cannot notice a quiet room. It
needs a clock of its own.

This gate drives the scheduler's clock directly (tick_once with an injected `now`), so it
is fast, deterministic, and does not wait 4 real minutes.
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness.kairos import impulse as I          # noqa: E402
from harness.kairos import scheduler as S        # noqa: E402
from harness.tuning import registry as tune      # noqa: E402

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" :: {detail}" if detail else ""))


def reset(session="gtick"):
    S._STATE.clear()
    S._OUTBOX.clear()
    S._TIMERS.clear()
    S._LAST.clear()


def main() -> int:
    print("G-KAIROS-TICK - silence is not an event. She needs a clock.\n")

    # isolate the tuning store so the operator's live settings are never touched
    import tempfile
    tune.STORE = os.path.join(tempfile.mkdtemp(), "tuning.json")
    tune.set_many({"kairos.enabled": True, "kairos.checkin_idle_s": 240.0,
                   "kairos.checkin_chance": 1.0, "kairos.cooldown_s": 0.0})

    sess = "gtick"
    spoke = []

    def generate(nudge):
        spoke.append(nudge)
        return "I've been thinking about that transformer idea you mentioned — the "\
               "masterkey thing is the part that keeps nagging at me."

    # ── 1. THE BUG: the branch is unreachable from on_reply alone ────────────────
    # decide() called the instant a reply lands: idle is ~0, so CHECK_IN can never fire.
    reset()
    st = I.TurnState()
    I.note_user(st, 1000.0)
    cfg = S.live_config()
    imp = I.decide(cfg=cfg, state=st, now=1000.1, reply_text="Sure.", eot_margin=None)
    check("at reply time the room is NOT quiet, so check-in cannot fire", not imp.speaks,
          imp.reason)

    # ── 2. THE FIX: a clock, and the same policy, 5 minutes later ────────────────
    imp = I.decide(cfg=cfg, state=st, now=1000.0 + 300, reply_text="Sure.", eot_margin=None)
    check("after 300s of quiet the SAME policy says check in", imp.speaks and imp.action == I.CHECK_IN,
          imp.reason)

    # ── 3. the ticker reaches it end to end (outbox, with a reason) ──────────────
    reset()
    S.on_reply(sess, "Sure.", None, generate)          # registers the session + closure
    S._STATE[sess].last_user_at = time.monotonic() - 300
    S.tick_once()
    for _ in range(60):                                 # the timer fires on a short delay
        if S._OUTBOX[sess]:
            break
        time.sleep(0.2)
    out = list(S._OUTBOX[sess])
    check("the TICK reaches the outbox", bool(out),
          repr(out[0]["text"][:48]) if out else "nothing — the branch is still dead")
    if out:
        check("...as a CHECK_IN, with an auditable reason",
              out[0]["kind"] == I.CHECK_IN and "quiet" in out[0]["reason"], out[0]["reason"])

    # ── 4. and she does not do it again — the chain holds ────────────────────────
    S._STATE[sess].last_user_at = time.monotonic() - 600
    S._OUTBOX[sess].clear()
    S.tick_once()
    time.sleep(1.0)
    check("she does not check in twice — max_chain holds until HE speaks",
          not S._OUTBOX[sess], f"{len(S._OUTBOX[sess])} more — she is monologuing at an empty room")

    # ── 5. HE speaks: the chain resets and she may check in again ────────────────
    S.on_user_turn(sess)
    check("his turn resets the chain", S._STATE[sess].chain == 0)

    # ── 6. THE BOUND THAT MATTERS: usually she still says nothing ────────────────
    tune.set_many({"kairos.checkin_chance": 0.35})
    cfg = S.live_config()
    rng = __import__("random").Random(7)
    st2 = I.TurnState()
    # NB: a real monotonic clock, not 0.0. decide() guards the check-in branch with
    # `if user_present and state.last_user_at:` — and 0.0 is FALSY, so seeding the state
    # at t=0 silently disables the branch and every tick reads as "she chose to stay
    # quiet". It cannot happen in production (time.monotonic() never returns 0), but it is
    # exactly the shape of bug that makes a dead feature look like a well-behaved one.
    I.note_user(st2, 1000.0)
    fired = sum(1 for _ in range(400)
                if I.decide(cfg=cfg, state=st2, now=1300.0, reply_text="Sure.",
                            eot_margin=None, rng=rng).speaks)
    check("even in a quiet room she MOSTLY says nothing (~35%, not 100%)",
          80 <= fired <= 200, f"{fired}/400 quiet ticks produced a check-in")

    # ── 7. she never checks in on top of a question she asked HIM ────────────────
    imp = I.decide(cfg=cfg, state=st2, now=1300.0,
                   reply_text="What did you end up doing about the NUC?", eot_margin=None)
    check("she never fills a silence she created by asking him something",
          not imp.speaks, imp.reason)

    total = len(PASS) + len(FAIL)
    print(f"\nG-KAIROS-TICK: {'PASS' if not FAIL else 'FAIL'} ({len(PASS)}/{total})")
    return 0 if not FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())
