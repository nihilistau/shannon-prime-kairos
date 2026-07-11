---
type: gate-receipt
title: "Load-time prefill + G-CONVERSATION: turns 40-80s -> 5-17s; the gate that catches the way the system actually fails"
date: 2026-07-12 (small hours)
status: GREEN on speed + completeness; two honest corrections recorded
---

# 1. "Why is prefill run on the first message and not on load?" (operator)

It WAS on load — but on a BACKGROUND thread, while the gateway already served
traffic. So the first user turn RACED the prefill on the one resident session:
the persist guard missed (`pos != committed`), the cache was thrown away, and
BOTH the prewarm and the turn paid a full cold prefill. That is the ~5-minute
ambush.

Fixed:
- `_WARM` event: chat turns WAIT for the load-time prefill (heartbeats keep the
  UI alive); nothing can race it.
- `/health` reports `warm`; `serve.py` holds "READY" until the prefix is hot
  ("prefix HOT in 424s — first turn is fast").
- Console shows a `◐ warming` chip instead of looking dead.
- `_prewarm` is ALWAYS byte-exact (the preamble's detail is the thing that
  matters, whatever regime serving uses).

# 2. The MCP tool bridge was rebuilt EVERY turn (5.5 s measured)

A cost the console never paid until the P1b-2a rehoming put every turn through
the gateway. Now built once per serve (`_SYS_CACHE`): `tool-system build 0.0s
(cached=True)`.

# 3. Turn-phase timing in the kernel (the line that ends the guessing)

`TURN-PHASE: total 2024 ms = prefill 619 ms + decode 1319 ms (17 tok, 12.9 tok/s)
+ other 86 ms (byteexact=true)`

Result: gateway overhead ~0, "other" (capture/spectest/mint) ~85 ms. **All
remaining cost is decode: ~12-13 tok/s byte-exact** (byte-exact declines the
CUDA-graph decode path). A 700-char reply is ~180 tokens ⇒ ~15 s. That is the
system's true speed limit and the drafter's target.

# 4. Measured (same 10-turn conversation, past ring_W)

| | before tonight's fixes | after |
|---|---|---|
| turn latency | 40-80 s | **4.6-17.3 s** |
| first turn | ambushed by prefill race | prefill done at load |
| replies | complete | complete |
| recall mid-conversation | works | works |

# 5. TWO HONEST CORRECTIONS

**(a) My completeness checker was lying.** It only accepted ASCII `.!?`, so it
FAILED stylish endings ("a silent guardian forevermore—", "… time and again …")
and reported bugs that did not exist. A gate that cries wolf gets ignored —
which is exactly how a REAL mid-word death hides. Now: unicode terminal marks
accepted, unit-tested against both the real failures ("and yet there'",
"ingly calm blue surfaces") and the real stylistic endings.

**(b) My float refutation was under-evidenced.** I claimed float serving
corrupts attended detail, citing "Shannon-15 / RTX 3067". Tonight the SAME
canary failed under BYTE-EXACT serving ("RTX 210."). So that evidence does not
separate float from ordinary model sloppiness at temp 0.7. The float question
is REOPENED and needs a controlled experiment (temp 0, N samples, same session,
both regimes). Float remains OFF by default — but for lack of evidence either
way, not because it is refuted. Byte-exact serving costs ~2x decode speed
(graph path declined), so this experiment is worth real money.

# 6. eot_bias exonerated

Swept 4.0 / 2.0 / 0.0 on long-form: eot=4 produced a clean 939-char paragraph;
the "failures" were the checker bug above. Banked instead: at eot=4 one run hit
"(tool loop exhausted)" — the tool system prompt pushes the model to call tools
on a creative-writing prompt. Harness-layer; tracked.
