---
type: regression-postmortem
title: "LIVE-PLAY REGRESSION: the prefix shear corrupted conversations past the ring. Operator found it. My gates could not have."
date: 2026-07-11 23:30
status: FIXED (shear disarmed) — with a doctrine failure to record
---

# What the operator saw

Every reply truncated after a few characters ("Hello there! I'm Shannon-",
"I'm ", "Fine, thanks for ") and turns crawling. The system I had declared
sealed an hour earlier was unusable.

# What actually happened

`gemma4_kv_shear` (P1c-2) sets `commit_pos = P` and `jcur = 0` alongside
`dpos = P`. `commit_pos` is the SWA undo-journal BASELINE: the journal index
is `pos - commit_pos`, bounded by `Jmax = 64`. As soon as a sheared
conversation grows past `ring_W = 2048` and journaling engages, that index is
far outside its bound. The KV state degrades; the model emits end-of-turn
immediately; every subsequent turn in that residency is 1-26 characters.

Evidence: `[agent] round=0 is_tool=None buf=26ch / 5ch / 1ch` — the harness
streamed everything it received; the DAEMON produced almost nothing.

# The doctrine failure (the part that matters)

My shear gates tested: fresh short chats after a shear. Every one passed —
20.4 µs restore, "Tokyo.", "42.", "Jupiter.". **Not one gate ever kept talking
after a shear.** The failure needs a conversation to grow past 2048 tokens in
a residency where a shear fired. No probe I wrote could produce it. The
operator produced it in four messages.

HINDSIGHT lesson 6 says composition needs its own gates; lesson 7 says
live-play IS a gate class. I wrote both into the receipts today and then sealed
P1 on a battery of short, fresh, single-turn probes. The bar was met and the
system was broken. That is exactly the failure the charter exists to prevent.

# Fix

`profiles/agent.toml: prefix_snapshot = false` — the shear is a default-off
lever again, as levers should be. The verb stays in the tree. It does NOT run
again until there is a gate that: shears, then grows the conversation past
ring_W, then checks reply completeness. Verified after disarming: 702-char and
490-char replies, five-turn conversation coherent, recall intact.

# Speed accounting (measured, same night)

- **Cold prefill on a cache miss: ~5 minutes.** Byte-exact prefill is
  ~233 ms/token; the 1.65k-token preamble alone is minutes. The new
  `PERSIST-KV: guard miss (pos=X != committed Y)` line names it when it
  happens (it fired: pos=1921 vs committed=2125).
- **MCP tool bridge rebuilt EVERY turn: 5.5 s** — a cost the console never
  paid before I rehomed it to the gateway. Fixed: the tool system is built
  once per serve (`_SYS_CACHE`).
- B4 capture after an admitted turn: tens of seconds, serialized with the
  session (the 120-word cap helps; async capture is the real fix).
- Decode: 24.4 tok/s floor (the drafter is P5's answer).

# Standing offer

Every change today is a revertible commit and the staging binary is untouched:
`profiles/agent.toml: engine_exe -> shannon-prime-system-engine/.../sp-daemon.exe`
restores the pre-kairos stack in one line.
