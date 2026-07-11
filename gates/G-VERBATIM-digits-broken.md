---
type: gate-receipt
title: "G-VERBATIM — the model cannot copy REPEATED/CONFUSABLE tokens out of its own context. Digits die; distinct letters survive. Six suspects eliminated with evidence."
date: 2026-07-12
status: RED — root cause narrowed to the attention read-out; ONE experiment left
---

# The symptom, precisely characterised

temp 0 · tools off · recall off · ngram off · eot off · daemon-direct

| context | ask | model says | |
|---|---|---|---|
| "The code is 7." | repeat | **7** | ✓ |
| "The code is 47." | repeat | **47** | ✓ |
| "The code is 4471." | repeat | **4417** | ✗ transposed |
| "The code is QXZP." | repeat | **QXZP** | ✓ **four DISTINCT letters — perfect** |
| "The code is A7B2." | repeat | **A7B7** | ✗ copied an EARLIER token |
| "The code is 4 4 7 1." | repeat | **4 1 7 4** | ✗ scrambled |
| "four four seven one" | repeat | **four four seven four four four** | ✗ number-WORDS fail too |
| "quartzblanket" | repeat | **quartzblanket** | ✓ |
| "2+2" | compute | **4** | ✓ |

**The failure is not about digits per se. It is about REPEATED or CONFUSABLE
tokens.** Four distinct letters copy perfectly; any sequence with a repeat
(4,4 / four,four) or near-neighbours collapses, and the model substitutes a
token that appeared EARLIER in the sequence (A7B2 → A7B**7**). That is the
signature of an attention read-out that cannot disambiguate two positions
holding the same content — an induction/copy failure, not a precision failure.

# What this breaks (everything above it)

Tool numbers ("2014-365"), persona details ("RTX 210."), any stored memory with
a code/date/number, HINDSIGHT's "numeric garbling" (blamed on 0.6/1.3 sampling
and "fixed" with temp 0.15 — **it reproduces at temperature 0**, so that fix
never worked).

# ELIMINATED, each with evidence (do not re-litigate)

1. **Sampler** — no_repeat_ngram 3 vs 0: byte-identical output. temp 0.7 vs 0:
   same class of failure. eot_bias 4/2/0: irrelevant.
2. **Byte-exactness** — byteexact true vs false: byte-identical wrong strings.
3. **Harness** — reproduced daemon-direct, no gateway, no tools, no recall.
4. **The SFT adapter** — the BASE model fails identically.
5. **Weight quantization** — the PURE-Q8 model (`st`, 329/329 tensors OK_Q8,
   no 4-bit anywhere) fails identically ("21.7C/48%" → "22.1C/49%"). The mixed
   b1 (Q8 + 96×Q4B) and the all-Q4 `qat` (total gibberish — a broken transcode,
   already known) bracket it. Precision is NOT the discriminator.
6. **Tokenizer** — every digit ID matches the HF `tokenizer.json` EXACTLY
   (0=236771, 1=236770, ... 9=236819; gemma-4's digit IDs genuinely are
   non-monotonic).
7. **RoPE / partial rotary** — the model's `rope_freqs.weight[256]` is exactly
   right (1.0 for pairs 0-63, 1e30 for 64-255 = `partial_rotary_factor 0.25` on
   the 512-wide global head), and the kernel's `base^(-2i/head_dim)` matches HF's
   `_compute_proportional_rope_parameters` **exactly** (HF also divides by
   head_dim, not rotary_dim — verified in the installed transformers source).
   Both `k_rope_freqs_at` (resident) and `k_rope_at` (SWA) use the ABSOLUTE
   position.
8. **`attention_k_eq_v`** — gemma-4 has NO `attn_v` tensor (V = the K
   projection) on global layers. The engine implements this CORRECTLY in BOTH
   forward paths: `dv = dk` is copied BEFORE the k-norm and RoPE, then given the
   weightless V-norm — byte-for-byte HF's ordering.

# WHAT REMAINS (the live suspects)

The bug is in the **attention read-out over the cached span**, most likely in:
- `k_attn_decode_win` / `k_attn_decode` — the single-query GQA kernels, with
  **group = 16** on global layers (16 query heads : 1 KV head, 512-wide) and the
  SWA window. A grouping/stride error would blur positions holding equal content
  while leaving distinct content separable — exactly the symptom.
- the **softcap** (`final_logit_softcapping = 30`, `attn_logit_softcapping`)
  and `scaling = 1.0` interaction.
- AltUp / PLE residual mixing.

# THE DECISIVE EXPERIMENT (next session, do this first)

Run the SAME weights through HF transformers (installed, gemma4 supported) on
the SAME prompt ("The code is 4471. Repeat it.") and compare:
1. HF output vs ours (does HF copy 4471? — near-certainly yes),
2. then bisect the forward: the engine already HAS the machinery
   (`attn_only` bisect modes + `BX_REC` tensor dumps in cuda_forward.cu) to dump
   q/k/v/attn per layer. Compare against HF's tensors at the same layer.
The engine's own gold gates test the MATH CORE, not the gemma-4 forward against
a reference — that gap is exactly where this bug has been living.

# The gate

`harness_tests/g_verbatim.py` — word control, arithmetic control, digit copy,
digit echo, tool-shaped composite. Run it after ANY engine/model/profile change.
**Until it is GREEN, no number the system reports about itself, its tools, or
its memories can be trusted.**

# HUNT LOG — 2026-07-12 (continued)

## New forensics tool: POST /v1/debug/kdiff  (shipped, CUDA-only)

Prefills raw tokens into the resident cache and returns, per position, the token
id + the cosine of its GLOBAL-owner K row against every other position. Read-only.
This is how you ask the engine "can attention even TELL these two tokens apart?"

    curl -s localhost:3000/v1/debug/kdiff -d '{"text":"4 4 7 1"}'

## Result: the keys DO carry position (RoPE reaches the cache)

    pos 1  tok 236812 ('4')   cos vs pos 3 ('4') = 0.618
    pos 2  tok 236743 (' ')   cos vs pos 4 (' ') = 0.740, vs pos 6 = 0.592

Two IDENTICAL tokens at different positions are NOT identical in the stored keys.
So RoPE is applied and reaches the KV cache. (Note the cosine floor is high BY
DESIGN: partial_rotary_factor 0.25 leaves 384 of 512 global dims un-rotated, so
identical tokens share 75% of their key vector. Fine positional discrimination
lives in the SWA layers, which carry full RoPE.)

## Also eliminated this round

- **Attention scaling** — HF self.scaling = 1.0; the engine folds ascale=1.0
  (comment: "gemma4 scaling=1.0 (folded)"). Match. A too-flat softmax would have
  produced exactly our symptom; it is not that.

## The HF reference is still THE decisive experiment — and it is BLOCKED ON DISK

	ransformers 5.5.4 is now importable (the install was broken by a
huggingface_hub version mismatch — fixed). But:
- the checkpoint is gemma4_unified, which 5.5.4 does not wrap. Its TEXT stack
  (Gemma4ForCausalLM + Gemma4TextConfig) is exactly right, so
  	ools/reference/make_text_ckpt.py re-shards model.language_model.* into a
  loadable checkpoint (streams tensor-by-tensor; peak RAM ~3 GB).
- **It needs ~23 GB free on a drive. D: has 22 GB.** Free space (or point OUT at
  another drive) and run:

      python tools/reference/make_text_ckpt.py
      <Python311>\python.exe tools/reference/hf_reference.py

  Loading 12B bf16 needs offload (32 GB RAM / 12 GB VRAM) — slow, but this is a
  CORRECTNESS reference, not a benchmark. If HF copies "4471" and the engine says
  "4417", the engine's gemma-4 forward is wrong and the bisect starts (the engine
  already carries ttn_only bisect modes + BX_REC tensor dumps for this).
