# ADR-012 — fp16 K/V cache (not int8), and why

**Status:** planned, not started. Written 2026-07-13 at the end of a long session, deliberately
*instead of* starting the surgery, because half-finished dtype surgery in the KV cache does not
fail loudly — it fails like G-VERBATIM did: she keeps talking, fluently, and the numbers come
out wrong.

---

## 1. Why this is now the critical path (and it was NOT, three hours ago)

I filed KV quantization as *"lowest value, highest risk, does not fix the re-prefill."* The
first two still stand. **The third is false**, and the operator's Q4 smoke test is what proved it.

Measured, weights swapped, **zero code changed**:

| | b1-reason (8.79 GB) | q4b (6.65 GB) |
|---|---|---|
| dedicated VRAM | 11,911–11,984 MiB | **9,740 MiB** |
| sp-daemon host spill | 122–860 MiB | **76 MiB** — the pinned floor. Zero. |
| one-shot batched prefill | **DECLINED** (no VRAM) | **TRUE** |
| the judge (520 tok) | **113,475 ms** | **6,422 ms** — 17.7× |
| judge verdict | "NO: not in stock…" | *identical* |
| conversation after aux call | survived | survived |

**The only thing that changed was that the weights left room for the design to run.** Every
piece of machinery — the scratch session, the ring-off open, the per-session `one_shot` flag,
the batched prefill — is correct, and was being starved. So the KV dtype is not an
optimisation any more. It is the thing standing between the operator and a working system on
the weights he actually wants.

**The cheap experiment that could have killed the expensive one cost four minutes.** That is the
lesson of the whole session and it belongs at the top of this file.

## 2. fp16, NOT int8. The arithmetic says fp16 is enough, and it is a fraction of the risk.

Per SWA layer: `kvd = 2048` (8 KV heads × 256), 46 SWA layers, 2 globals, ring_W 2048, pmax 13000.

| | ring (46×2048) | globals | one-shot scratch | **freed** |
|---|---|---|---|---|
| fp32 (today) | 1.54 GB | 0.43 GB | 470 MB | — |
| **fp16** | **0.77 GB** | **0.21 GB** | **235 MB** | **~985 MB** |
| int8 | 0.39 GB | 0.11 GB | 120 MB | ~1.48 GB |

The requirement is ~535 MB (scratch 235 + batched activation scratch ~300). **fp16 frees 985 MB.
It clears the bar with room, and q4b proved that is all the headroom the design wants.**

**Do not take the 4× we do not need in exchange for the one risk this codebase has already been
burned by.**

* fp16: 10-bit mantissa, **no scale factors at all**. `__float2half` on store, `__half2float`
  on read. There is nothing to get wrong.
* int8: an 8-bit *integer* grid plus per-head scale arrays — precisely the regime where
  confusable digit embeddings collapse. That is the G-VERBATIM failure mode
  (`4471` → `4417`), and while the *cause* there turned out to be `no_repeat_ngram`
  (b227c74) and quantization was explicitly **eliminated** (5812939), that is a reason not to
  fear fp16 — it is not a licence to go and build the failure mode on purpose.

If fp16 ever proves insufficient, int8 is a strictly later decision with a working fp16
reference to compare against. Doing it in the other order means debugging two things at once.

## 3. THE CONTAINMENT RULE (the whole reason this doc exists)

`dKc[L]` / `dVc[L]` are `float*` and are touched in **112 places**:

```
52x  gemma4_decode_cuda        <- every attention launch
 8x  g4_kv_step
 7x  gemma4_kv_prefill_batched
 4x  gemma4_kv_replay · gemma4_kv_ctx_dump · g4_kv_launch_full
 3x  xbar_capture · xbar_splice
 2x  gemma4_kv_snapshot · _rewind · _reset_cold · _ablate_rows
```

To **save** memory the fp32 buffer must not exist for the SWA layers. So under fp16:

> **`s->dKc[L] == NULL` for every SWA layer, and every consumer either handles `__half` or
> REFUSES — LOUDLY. Nothing guesses. Nothing silently reads a NULL. Nothing quietly falls back
> to a stale float buffer.**

A dtype refactor that "mostly works" is the worst possible outcome here, because the failure is
not a crash — it is a plausible sentence with the wrong number in it.

## 4. Execution order (each step independently verifiable; do not skip the gate)

1. **Centralise access first.** Introduce `kv_k(s,L)` / `kv_v(s,L)` accessors and a
   `KV_DTYPE(s,L)` predicate, and route all 112 sites through them **while still fp32**.
   *This step must be a no-op.* Prove it: G-VERBATIM + G-CONVERSATION byte-identical before and
   after. This is what turns fp16 from a 112-site change into a 6-site change.
2. **Allocate.** `dKh/dVh` (`__half*`) for SWA layers when `SP_CUDA_KV_FP16=1`; `dKc/dVc` NULL
   there. `gemma4_kv_prefix_bytes` becomes dtype-aware (the prefix snapshot copies raw bytes and
   WILL be wrong otherwise — it is my code and it is the first thing that breaks).
3. **Write path.** `k_kv_store` half variant + the direct `cudaMemcpyAsync` stores at
   ~3200 / ~3513 and the `cudaMemsetAsync` zero-fills.
4. **Read path.** `k_attn_decode_ring` and `k_attn_decode_ring_bx` half variants. `_bx` is the
   byte-exact (exact-integer islands) kernel — quantisation is still *deterministic*, so
   run-to-run byte-exactness survives; what changes is the value vs the fp32 config. Say that
   out loud in the gate rather than pretending.
5. **Refuse everywhere else.** `ctx_dump`, `replay`, `xbar_capture`, `xbar_splice`,
   `ablate_rows`: error out with a named message when fp16 is on and they meet a NULL. They are
   default-off diagnostic paths; a clear error beats a silent wrong answer.

## 5. The gate: G-KVFP16. It is a QUALITY gate, and it must not pretend to be an exactness gate.

fp16 K/V is **not** byte-identical to fp32 K/V. Any gate asserting that is a gate that will
either fail forever or be quietly loosened until it means nothing. So assert what is actually
true:

1. **VRAM**: daemon dedicated drops ~985 MB; sp-daemon host spill returns to the **76 MiB pinned
   floor** (see G-VRAM: the floor is legitimate pinned staging, not a spill — the operator caught
   me asserting otherwise).
2. **The unlock**: the one-shot judge reports `batched=True` and lands **< 15 s** (it is 113 s
   today on these weights, 6.4 s on q4b).
3. **VERBATIM SURVIVES**: `4471` copies back as `4471`. `RTX 2060` as `RTX 2060`. This is the
   one that matters — it is the exact failure this dtype could plausibly cause, and it is
   cheap to check.
4. **Determinism**: the same prompt twice at temp 0 gives byte-identical output (fp16 is
   deterministic; if this fails, something is racing, not rounding).
5. **Coherence**: G-CONVERSATION parity against the fp32 run — not identical text, but not
   degraded either. Judge it on the gates we already own, not on vibes.

## 6. Fallback that costs nothing

`SP_CUDA_KV_FP16` defaults **off**. fp32 remains the null floor. If any of §5 fails, the flag
stays off and we have lost nothing but time — which is the entire point of building it this way
rather than swapping the dtype in place and hoping.
