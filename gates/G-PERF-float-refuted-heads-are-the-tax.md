---
type: gate-receipt
title: "G-PERF — float lever REFUTED (1.07x). `other` named. The 4.1s 'head tax' was a DAEMON-DIRECT artifact (production pays 80ms). The real tax is the 1618-token PREAMBLE: -40% decode, every token, forever."
date: 2026-07-12
status: MEASURED — and self-corrected once. Read the correction.
---

# 1. The float lever is worth 7%, not 100% (stands)

The float path was "REFUTED at attended-detail" (P5a) because the model garbled
`RTX 2060`. That canary was measured with `no_repeat_ngram=3` on — the ban that
garbled EVERY repeated detail regardless of precision (G-VERBATIM). So it refuted
nothing, and the ~2x lever had to be re-measured.

Same prompt, temp 0, daemon-direct, heads OFF, only decode precision differs:

| serving regime | decode |
|---|---|
| `byteexact=true` (exact-integer islands) | **22.1 tok/s** |
| `byteexact=false` (float) | **23.7 tok/s** |

**1.07x.** Decode is memory-bound on the weight read, not ALU-bound on the
nonlinearities, so making the nonlinearities cheaper buys ~nothing. Float also
changes the text (489ch vs 322ch, same prompt), so 7% would additionally cost the
reproducibility the gates doctrine rests on.

**Decision: `byteexact = true` STAYS.** We were paying ~0% for byte-exactness while
believing it cost us half our speed. `profiles/float.toml` is a measurement profile,
never a serving one.

# 2. `other` is now named (stands)

TURN-PHASE lumped 4132 ms into one anonymous `other` bucket. It now reads:

    TURN-PHASE: total N = prefill P + recall R (F fwd) + decode D (T tok, X tok/s) + post O + other E

`recall` = everything between prefill and the first generated token (L5 search, judge,
replay). `post` = capture / spectest / qkey mint. `F` = forward passes burned by the
recall stage (via `kv::step_count()`), which is how we learned the recall stage runs
**exactly ONE forward** — so its cost was never inference.

`post` measures **0 ms**. Capture/spectest/qkey are free. That suspect is dead.

# 3. THE CORRECTION — the "4.1 s head tax" was an artifact of MY PROBE

I reported `other`/recall = 4132 ms/turn and called it "the turn tax". That number is
real but it is **daemon-direct only**:

- daemon-direct (`POST :3000/v1/chat`) → `auto_recall` **defaults TRUE** → fires the
  **legacy in-kernel recall lane** → **4376 ms/turn**.
- through the gateway (`:8800`, what the console and every user actually use) → the
  gateway is the L5 recall authority and sends `auto_recall:false` → the daemon's
  recall stage costs **71–98 ms**.

**Production never paid the 4.1 s.** I measured a path users do not take — the same
class of error as the `no_repeat_ngram` false elimination, caught within the hour this
time because the new instrumentation showed `RECALL-PHASE` never firing.

## But it IS a live footgun (needs a gate)

The legacy in-kernel lane is still compiled (`legacy_policy`) and still fires on ANY
daemon-direct request that does not explicitly pass `auto_recall:false`. That is a
**second recall authority**, exactly what `serve.py`'s `recall_authority must be L5`
lint exists to prevent — the lint guards the profile but not the wire. Anything that
talks to :3000 directly (probes, harnesses, a fallback console) silently pays 4.4 s
AND gets a different recall answer than production. **Filed: G-ONE-RECALL-AUTHORITY.**

# 4. THE REAL TAX — the preamble costs 40% of decode, every token

| context | decode |
|---|---|
| daemon-direct, bare prompt (~20 tok context) | **20–22 tok/s** |
| gateway, with the persona + tool-schema preamble (**1618 tokens**) | **12–13 tok/s** |

Attention over the cached preamble is re-paid on **every generated token of every
turn, forever**. A 300-token reply at 12 tok/s is 25 s; at 22 tok/s it is 14 s.

This is now the largest lever in the system, and unlike the last three suspects it is
not a bug — it is a design cost we chose without measuring. Next:

1. **Shrink the preamble.** 1618 tokens of persona + tool schemas. Measure decode
   tok/s vs preamble length to get the exact slope, then cut/compress the schemas
   (they are the bulk) and lazy-load tool definitions only when a tool lane is live.
2. **Drafter spec-decode** (19.8% acceptance ~ 1.2x, byte-identical output) — strictly
   additive on top of whatever baseline we reach.
3. **Cold start**: `prefill 96342 ms` for the 1618-token preamble (~58 ms/tok) — the
   same preamble, paid once at boot. Shrinking it fixes this too. Note turn 2 shows
   `prefill 0` → **persist-KV prefix reuse is working correctly.**

# Receipts

All numbers are `TURN-PHASE` / `RECALL-PHASE` lines emitted by the daemon itself
(`var/daemon.log`, 2026-07-12), kairos engine, `gemma4-12b-b1-reason.sp-model`,
`no_repeat_ngram=0`, `byteexact=true`.

# 5. Also caught (needs its own gate)

On a heads-ON daemon-direct float turn the model answered a thunderstorm question with
a **recalled memory** — `"From the record: The user said: His neighbor talked about the
quiet library..."` — instead of answering. That is the legacy lane's recall MISFIRE.
**Filed: G-RECALL-PRECISION** — an irrelevant memory must never displace the answer.
