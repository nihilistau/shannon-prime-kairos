"""G-ONEWRITER — exactly one thing may write var/memory/registry.jsonl.

── THE FIX FOR THE BUG CLASS WAS ITSELF APPLIED TO ONE OF TWO PATHS (2026-07-14) ────────
2026-07-12 retired the daemon as a memory writer, and said why, at length, in a profile comment:

    "Two authorities decided what a memory was: the daemon's word-count-and-a-pronoun, and the
     harness's lifecycle rules -- which had the dedupe, the supersede, the two stores and the
     durability test. The daemon won every time, BECAUSE IT WROTE FIRST."

The remedy was `growth = false`. THE DAEMON HAS TWO WRITE FLAGS.

    growth      (SP_B4_NIGHTSHIFT)  auto-capture the whole turn        -> RETIRED
    store_verb  (SP_MEM_STORE)      intercept "remember that X" /      -> STILL TRUE, IN 12 OF 13
                                    "note that X", write the registry     PROFILES, INCLUDING THE
                                    directly, and answer with ZERO        LIVE ONE
                                    DECODE so the model never sees it

So on the live profile, "note that I'll be late" went to the daemon, which wrote the registry with
speaker hardcoded "user", no `status`, and none of is_memorable(), the identity firewall,
dedupe/reinforce, find_superseded(), or the private-secret classifier that G-SECRET just landed.

The remedy for "an invariant enforced in one of two paths is enforced in neither" was enforced in
one of two paths.

── AND THE REASON store_verb EXISTED IS GONE ────────────────────────────────────────────
It was added because the model would answer "I don't know how to store memories" while an episode
grew silently behind it — the system had the ability and denied it. Capture no longer depends on
the model choosing a tool: app._capture_after_turn() runs on EVERY turn, splits the human's text,
and puts each durable sentence through remember(). The deterministic guarantee store_verb provided
is now provided by the correct door.

── WHY THIS IS A LINT AND NOT A COMMENT ─────────────────────────────────────────────────
A rule written in a comment gets applied to the file the comment is in. That is exactly what
happened: the doctrine lived in agent.toml and eight other profiles kept growth=true, including
kairos.toml — the one an operator is most likely to reach for by name.

It lives in serve.py now, the only door, where a profile that arms two memory writers CANNOT BOOT.
And this gate walks EVERY profile on disk, so a new one cannot ship armed.

    python harness_tests/g_onewriter.py       (offline: no GPU, no daemon)
"""
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

try:
    import tomllib
except ModuleNotFoundError:                      # py<3.11
    import tomli as tomllib

import serve                                     # noqa: E402

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok   %s" % name)
    else:
        FAIL += 1
        print("  FAIL %s   %s" % (name, detail))


def load(p):
    with open(p, "rb") as f:
        return tomllib.load(f)


def boots(cfg):
    """Does serve.py accept this profile? Returns (ok, message)."""
    try:
        serve.build_env(cfg)
        return True, ""
    except SystemExit as e:
        return False, str(e)
    except Exception as e:                        # a missing key is not what we are testing
        return True, "(unrelated: %s)" % e


# ── 1. EVERY PROFILE ON DISK IS SINGLE-AUTHORITY ─────────────────────────────────────
# Not "the live one is fine". Every one. kairos.toml shipped armed for two days.
print("\n1. every shipped profile arms exactly one memory writer")
profiles = sorted(glob.glob("profiles/*.toml"))
check("found profiles to check", len(profiles) >= 10, len(profiles))

for p in profiles:
    c = load(p)
    mem, agent = c.get("memory", {}), c.get("agent", {})
    armed = [n for n, on in (("growth", mem.get("growth")),
                             ("store_verb", mem.get("store_verb"))) if on]
    spine = agent.get("authority") == "spine"
    check("%-22s harness-authority=%-5s daemon-writers=%s"
          % (os.path.basename(p), spine, armed or "none"),
          not (spine and armed),
          "TWO WRITERS: the daemon writes with none of the harness guards")

# ...and no profile is REFUSED BY THIS LINT. Deliberately narrower than "every profile boots",
# which is not true and should not be: drafter-datagen / headprobe / l1ref carry
# no_repeat_ngram=3 and are refused by the OLDER G-VERBATIM lint, which they are meant to override
# on purpose (SP_ALLOW_NGRAM_BAN=1). My first cut asserted "boots" and failed those three — a gate
# asserting a thing I wanted rather than a thing that was true, which is the whole failure mode of a
# gate. This checks what it means to check: THE MEMORY-AUTHORITY LINT NEVER FIRES ON A SHIPPED PROFILE.
print("\n   ...and no shipped profile is refused for TWO MEMORY AUTHORITIES")
for p in profiles:
    ok, why = boots(load(p))
    check("%-22s not refused for two writers" % os.path.basename(p),
          ok or "TWO MEMORY AUTHORITIES" not in why,
          why.splitlines()[0] if why else "")


# ── 2. THE LINT REFUSES THE BAD COMPOSITION ──────────────────────────────────────────
# Assert the guard fires, on the REAL build_env, not a reimplementation of its rule.
print("\n2. serve.py REFUSES a profile that arms two writers (the door, not a comment)")
base = load("profiles/agent.toml")

for flag in ("growth", "store_verb"):
    c = load("profiles/agent.toml")
    c["memory"][flag] = True                      # re-arm the daemon behind the harness's back
    ok, why = boots(c)
    check("memory.%-11s = true + authority='spine' -> REFUSED TO BOOT" % flag,
          not ok, "IT BOOTED. The daemon would write the registry unguarded.")
    check("   ...and the refusal says WHICH flag and WHY",
          (not ok) and flag in why and "TWO MEMORY AUTHORITIES" in why,
          why.splitlines()[0] if why else "")

# The composition is only illegal when the HARNESS is the authority. A daemon-owned profile is
# coherent (one writer, just a different one), and the lint must not forbid it out of superstition.
c = load("profiles/agent.toml")
c["memory"]["store_verb"] = True
c["agent"]["authority"] = "l5"                    # daemon owns the turn -> daemon may own memory
ok, _ = boots(c)
check("but a DAEMON-authority profile may still use the daemon writer (one writer, not zero)",
      ok, "the lint is refusing a legal single-authority composition")


# ── 3. THE LIVE PROFILE, EXPLICITLY ──────────────────────────────────────────────────
print("\n3. the live profile: the harness owns memory, and nothing else writes")
check("agent.toml authority = 'spine'", base["agent"].get("authority") == "spine")
check("agent.toml growth     = false", not base["memory"].get("growth"))
check("agent.toml store_verb = false", not base["memory"].get("store_verb"),
      "the daemon still intercepts 'remember that ...' with zero decode")

print("\nG-ONEWRITER  %d/%d" % (PASS, PASS + FAIL))
sys.exit(1 if FAIL else 0)
