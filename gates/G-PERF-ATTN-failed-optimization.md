---
type: gate-receipt
title: "G-PERF-ATTN — I parallelised the byte-exact softmax and made decode 32% SLOWER. Reverted. And my benchmark was confounded, so the baseline I'd been quoting was wrong too."
date: 2026-07-12
status: REVERTED — negative result, kept because it is expensive knowledge
---

# What I did

Long-context decode is much slower than short-context decode. Reading the served
byte-exact attention kernels (`k_attn_decode_win_bx`, `k_attn_decode_ring_bx`) I found
the softmax folded **entirely on `threadIdx.x == 0`** — a serial loop calling
`bx_exp_fixed` (an expensive FB30 fixed-point exp) once per cached position, while the
other 255–1023 threads of the block idled. O(ctx), serial, per head, per layer, per
token. It looked exactly like the culprit.

I replaced it with a warp-shuffle tree reduction. The reasoning for legality was sound
and still is: **the exact substrate is integer**, integer addition is associative and
max is order-independent, so a tree-order reduction is **bit-identical** to the serial
fold. That part worked — the output was byte-for-byte the same (489-char deterministic
completion, unchanged).

# What happened

It was **32% slower**, like-for-like (same prompt, same PINNED 100 generated tokens):

| binary | decode (100 tok @ ~1700 ctx) | rate |
|---|---|---|
| HEAD (serial softmax) | 23 160 ms | **4.3 tok/s** |
| parallel softmax | 30 580 ms | **3.3 tok/s** |

**Reverted.**

## The obvious mechanism is ruled out

I assumed register spilling (`__launch_bounds__(1024)` caps Turing at 64 regs, and
`bx_exp_fixed` is register-hungry). So I added `-Xptxas=-v` to the CUDA backend build —
**nobody had ever looked at this kernel's register budget.** It says:

    k_attn_decode_win_bx :  60 registers, 0 bytes spill stores, 0 bytes spill loads
    k_attn_decode_ring_bx:  50 registers, 0 bytes spill stores, 0 bytes spill loads

**Zero spills.** So the slowdown is not spilling, and — more importantly — **the serial
softmax was never the bottleneck.** Spreading it across 1024 threads added barrier and
shared-memory traffic that cost more than the serial exps it removed. The real
long-context cost is elsewhere.

## Where the cost actually is (the next lead, NOT yet tested)

The kernel's own comment names it, and I read past it:

> *"This loop runs ctx times per HD element — it was the dominant modulo storm at long context."*

The **p·V fold** is `O(ctx)` per output element with two `int64 %` operations every 64
products, and `int64 %` is ~20 SASS ops on Turing. The Q·K fold has the same shape.
Those are the O(ctx) terms that actually scale. Any future attempt starts there — and
starts by *profiling*, not by reading code and guessing.

# THE REAL LESSON — my benchmark was confounded

I had been quoting "decode is 11.5 tok/s at 1600 ctx". That run **generated only 20
tokens**. The like-for-like 100-token figure is **4.3 tok/s**. I compared a 20-token run
against a 100-token run and read the difference as a regression.

`tok/s` is meaningless unless BOTH the generated token count AND the context length are
pinned — the model is free to stop early, and the rate is a function of context. Every
ad-hoc perf probe I ran this session had one or both unpinned.

This is the same failure that produced the `no_repeat_ngram` false elimination: **an
uncontrolled A/B, believed.**

## The fix: `harness_tests/g_perf_decode.py` (G-PERF-DECODE)

A repeatable decode-rate gate. Pins the context bucket, pins the generated token count,
repeats, reports the median, enforces a regression floor. **Any perf claim about this
engine must now cite it.** No more ad-hoc probes — including by me.

# What was kept from this

- `-Xptxas=-v` on the CUDA backend build (register/spill visibility, permanently).
- `harness_tests/g_perf_decode.py` — the gate that should have existed first.
- The knowledge that the softmax is NOT the bottleneck, and the modulo storm is the
  live suspect. That cost a build cycle to learn; it is written down so it is not
  re-learned.

# Standing

Production is on HEAD (serial softmax), byte-exact, `no_repeat_ngram=0`.
G-VERBATIM 6/6 and the 489-char determinism check both still hold.
