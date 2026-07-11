---
type: gate-receipt
title: "G-PERF — the float lever is a DUD (1.07x, not 2x). The turn tax is the HEADS: 4132 ms of 'other' per turn vs 54 ms with them off."
date: 2026-07-12
status: MEASURED — byteexact stays ON in production; the speed work moves to `other`
---

# Why this was re-measured

The float path was "REFUTED at attended-detail" (P5a) because the model garbled
`RTX 2060` on the float turn. That canary was measured **with `no_repeat_ngram=3`
on** — the ban that made the model garble EVERY repeated detail regardless of
precision (see G-VERBATIM). So the refutation refuted nothing, and the ~2x float
lever had to be reopened and measured honestly.

# Result 1 — float is worth 7%, not 100%

Same prompt (150-word description, max_tokens 200), temp 0, daemon-direct,
heads OFF (no recall / spectest / growth), so ONLY the decode precision differs:

| serving regime | decode | `other` |
|---|---|---|
| `byteexact=true` (exact-integer islands) | **22.1 tok/s** | 54 ms |
| `byteexact=false` (float) | **23.7 tok/s** | 43 ms |

**1.07x.** Not 2x. The exact-integer islands (RMSNorm / GELU / RoPE / softcap) are
nearly free — the decode is memory-bound on the weight read, not ALU-bound on the
nonlinearities, so making the nonlinearities cheaper buys almost nothing.

**Decision: `byteexact = true` STAYS in production.** We were paying ~0% for
byte-exactness and had convinced ourselves it cost 2x. Float also produces different
text (489ch vs 322ch on the same prompt), so the 7% would additionally cost us the
reproducibility the whole receipts/gates doctrine rests on. Bad trade, refused.

`profiles/float.toml` is kept as a measurement profile, not a serving one.

# Result 2 — THE TURN TAX IS THE HEADS (this is where the speed actually is)

Same turn, same 80 tokens, heads ON (production agent profile) vs OFF:

    heads ON   total 9212 ms = prefill 1345 + decode 3735 + other 4132 ms
    heads OFF  total 6036 ms = prefill 1194 + decode 4788 + other   54 ms
                                                            ^^^^^^^^^^^^^

**`other` is 4132 ms — larger than the decode it wraps.** That is the recall /
spectest-veto / B4-capture stack running per turn. It is ~76x the null-floor cost.

This reframes every speed conversation we have had:
- it is NOT the sampler (that was the correctness bug),
- it is NOT the precision regime (1.07x, above),
- it is NOT the decode kernel (22 tok/s is the memory-bandwidth ceiling),
- it IS the machinery we bolted around the turn.

## Next (the honest speed backlog, in order of size)

1. **`other` = 4.1 s/turn.** Instrument it into named sub-phases (recall search,
   L5 judge decodes, spectest veto head, B4 capture/admission) the same way
   TURN-PHASE named prefill/decode. We cannot cut what we have not named.
   The B3 judge appears to run extra *decodes* that are not counted in the token
   count — which is why short turns showed an absurd "0.8 tok/s".
2. **Cold new-chat 96.6s** (G-CONVERSATION T1, the one remaining FAIL) — correct
   prefix reuse behind the gate; the shear stays disarmed until it has a gate that
   shears THEN grows past ring_W.
3. **Drafter spec-decode**, 19.8% acceptance ~ 1.2x with byte-identical output.
   Now strictly additive on top of a 22 tok/s exact baseline.

# Also caught here (needs its own gate)

On the heads-ON float run the model answered a thunderstorm question with a
**recalled memory** — `"From the record: The user said: His neighbor talked about
the quiet library..."` — instead of answering. That is a recall MISFIRE (the L5/judge
picked an irrelevant episode and let it speak). Filed as the next correctness gate
after G-VERBATIM: **G-RECALL-PRECISION** — an irrelevant memory must never displace
the answer.

# Receipts

All numbers above are from `TURN-PHASE` lines emitted by the daemon itself
(`var/daemon.log`, 2026-07-12), on the kairos engine at commit b227c74, model
`gemma4-12b-b1-reason.sp-model`, `no_repeat_ngram=0`.
