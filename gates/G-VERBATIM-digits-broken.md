---
type: gate-receipt
title: "G-VERBATIM — THE BIG ONE: the served stack cannot copy DIGITS out of its own context. Not the sampler. Not byte-exactness. The engine."
date: 2026-07-12
status: RED (gate written; fix is a real engine investigation)
---

# The finding

Temp 0. Tools off. Recall off. no_repeat_ngram off. eot_bias off.
Both byte-exact AND float. Both the reason model AND the base model.
**Every combination gives the identical wrong answer.**

| prompt | truth | model says |
|---|---|---|
| "Repeat exactly, nothing else: 4471" | 4471 | **4481** |
| "door code 4471, GPU RTX 2060" → repeat both | 4471 / 2060 | **4417 / RTX 3061** |
| "What is 4471 plus zero? number only" | 4471 | **"4417 plus zero is 14448"** |
| "Count: 1,2,3,4,5,6,7 — repeat exactly" | 1..7 | **1,2,3,4,5,6,7,1,1** |
| "Repeat exactly: quartzblanket" (CONTROL) | quartzblanket | **quartzblanket** ✓ |
| "What is 2+2?" (CONTROL) | 4 | **4** ✓ |

**Rare words copy perfectly. Arithmetic works. DIGITS IN CONTEXT DO NOT
SURVIVE A COPY.**

# What this explains (every one of these was blamed on something else)

- The tool time reported as "2014-365".
- The persona GPU read back as "RTX 210." / "RTX 3067".
- "Shannon-15" instead of Shannon-Prime.
- HINDSIGHT's "numeric garbling of tool results" — attributed to 0.6/1.3
  sampling and "fixed" with temp 0.15 + a verbatim rule. **It reproduces at
  temperature 0.** That fix could not have worked; it only reduced the odds.
- Any memory containing a number (a code, a date, a flight, a locker) is
  unreliable ON READ-BACK, no matter how faithfully it was stored.

This is not cosmetic. Memory, tools and persona are all built on the assumption
that the model can quote its context. For numbers, it cannot.

# What it is NOT (all falsified tonight, with receipts)

- NOT the sampler: ngram 3 vs 0 → identical output. temp 0.7 vs 0 → same class.
- NOT byte-exactness: byteexact=true vs false → byte-identical wrong strings.
- NOT the reason-SFT adapter: the BASE model fails too.
- NOT the harness: reproduced daemon-direct, no gateway, no tools, no recall.

# Suspects (in order), each needing its own experiment

1. **`SP_CUDA_DECODE_INT8`** — not just int8 GEMM: it also selects the PACKED
   INT8 EMBEDDING TABLE which doubles as the tied LM head. The daemon REFUSES to
   open without it on this model ("gemma4_kv_open: tied head needs
   SP_CUDA_DECODE_INT8=1"), so it cannot be A/B'd on b1 alone. Digit tokens are
   near-neighbours in embedding space; int8 collapse hits them first and leaves
   distinctive words intact — precisely the observed signature.
   **Experiment**: serve `gemma4-12b-st.sp-model` (11.1 GB — carries a separate
   higher-precision head) with INT8 off, re-run this gate. If digits survive,
   the int8 path is the bug and the fix is a real head/embedding decision.
2. Weight quantization of the served model (b1 ≈ 6-bit, 8.79 GB).
3. Positional read-out of single-char digit tokens (attention/RoPE).

# The gate

`harness_tests/g_verbatim.py` — word copy (control), arithmetic (control),
digit copy, digit echo, and a tool-shaped composite (21.7C / 48% / K9).
**Any** change to engine, sampler, model or profile re-runs it. Numbers must
survive a round trip through the model's own context, or nothing above it can
be trusted.
