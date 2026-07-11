---
type: gate-receipt
title: "G-VERBATIM — SOLVED. The model was innocent. `no_repeat_ngram=3` banned the model from re-emitting any trigram it could see, and verbatim copying IS that."
date: 2026-07-12
status: GREEN — 6/6. Root cause found, fixed, gated, and lint-guarded.
supersedes: "the RED receipt of 2026-07-12 (six 'eliminations', one of which was false and cost the whole hunt)"
---

# ROOT CAUSE

`profiles/agent.toml` → `[decode] no_repeat_ngram = 3` → `SP_NO_REPEAT_NGRAM=3`.

**`no_repeat_ngram=N` forbids emitting any N-token sequence that already appears in
the context. Quoting a number, a memory, a tool result or a persona fact IS emitting
a sequence that already appears in the context.** The feature and the requirement are
the same operation with opposite signs.

## The mechanism, caught in the act

Prompt: `The code is 4471. Repeat it.` The model emits `4`, `4` — and now the trigram
`4 → 4 → 7` **exists in the prompt**, so `'7'` is masked. The sampler takes the
next-best token, which is the other digit in the code: `'1'`. On the following step
`4 → 1 → 7` is a *novel* trigram, so `'7'` is allowed and gets emitted late.

    truth   4 4 7 1
    served  4 4 1 7      <- not a transposition. A BAN and a late re-entry.

Measured on the engine's OWN post-output_norm hidden states (`SP_HIDDEN_DUMP` +
`SP_HIDDEN_DUMP_DECODE`, this session), honest f32 head, softcap 30:

| decode step | model WANTS | margin | engine PRINTED | |
|---|---|---|---|---|
| 20 | `'4'` | 2.25 | `4` | ok |
| 21 | `'4'` | 6.91 | `4` | ok |
| 22 | **`'7'`** | **9.04** | **`1`** | **BANNED** |
| 23 | `'7'` | 3.58 | `7` | (the late re-entry) |

**The model wanted `'7'` with a margin of 9.0.** It was never confused, never
quantization-noisy, never coin-flipping. It was *overruled*.

# Why the symptom table looked like a model/kernel bug

The ban only bites on the **third token of a repeated run**. Everything shorter is
untouched — which produced a symptom table that pointed convincingly at the forward:

| case | tokens | verdict |
|---|---|---|
| `"7"`, `"47"` | 1-2 | never completes a banned trigram → **always passed** |
| `"quartzblanket"`, `"QXZP"` | few, distinct | → **always passed** |
| `"4471"`, `"A7B2"`, `"2+2"`, `"four four seven one"` | 3+ | → **always failed** |

"Distinct letters survive, digits die" is not a statement about embeddings. It is a
statement about **token count**.

# MY FALSE ELIMINATION (the reason this took days)

The previous receipt's suspect #1 read:

> *"Sampler — no_repeat_ngram 3 vs 0: byte-identical output."*

That test was wrong. The profile was edited but the daemon was **not restarted
cleanly**, so both arms ran with `SP_NO_REPEAT_NGRAM=3`. Byte-identical output was
the *tell* that neither arm had changed anything — and I recorded it as proof of
innocence. Every subsequent "elimination" (ring off, persist off, heads off, Q8 vs
Q4, byteexact on/off) was run **with the ban still on**, which is exactly why they
all produced byte-identical wrong output. They were all measuring the same masked
sampler.

The operator named this hypothesis first and asked for it to be tested. It was
dismissed on a broken A/B. **Check the daemon's own env banner, not the file you
edited.**

# What was ACTUALLY eliminated (still valid, re-verified)

- **The forward is correct.** Prefill hiddens predict `4,4,7,1` with margins 3-8.
- **The tied int8 head is correct.** f32 head vs the served dp4a int8 head over the
  same hiddens: **0/26 argmax flips**; logit noise 0.023 vs mean top-1 margin 3.16
  (two orders of magnitude). The `norm 127` "lead" was an artifact of the parity
  *script* omitting the `/127` that `k_embed_packed_one` applies.
- **The latent seam is faithful.** `single_entry=true` (`gemma4_kv_inject_tokens`)
  vs `false` (`kv::prefill`): identical output. The `routes.rs:1544` claim
  "bit-identical to prefill by construction" is now **measured**, not asserted.
- **The decode table is correct.** A static table cannot render `'7'` right in one
  context and wrong in another.
- **`TokenDecodeBuffer` cannot transpose** (extend → emit prefix → drain).

# THE FIX

    profiles/agent.toml:  no_repeat_ngram = 0     # was 3

Anti-degeneration is `eot_bias` + the B4 admission cap, **not** an n-gram ban.

## Lint guard (serve.py) — so this cannot silently return

`build_env()` now REFUSES to launch any profile with `no_repeat_ngram >= 2` unless
`SP_ALLOW_NGRAM_BAN=1` is set deliberately:

    profile invalid: no_repeat_ngram=3 breaks verbatim copy (G-VERBATIM).

# RECEIPTS (2026-07-12, full production stack: persona + tools + recall + growth)

    G-VERBATIM: PASS (6/6)
      [PASS] WORD copy: quartzblanket   :: 'The passphrase is quartzblanket.'
      [PASS] arithmetic: 2+2=4          :: '2+2=4. Digits only.'
      [PASS] DIGIT copy: 4471           :: '4471.'
      [PASS] DIGIT copy: RTX 2060       :: 'RTX 2060.'
      [PASS] DIGIT echo: 8302           :: '8302 is a number, so I will repeat it: 8302'
      [PASS] TOOL-shaped copy           :: 'The temperature is 21.7C, the humidity is 48% ...'

Daemon-direct A/B on a clean restart (`SP_NO_REPEAT_NGRAM=0` confirmed in the banner):

    4471                 -> 4471                      (was 4417)
    A7B2                 -> A7B2                      (was A7B7)
    2+2                  -> 2+2=4                     (was 2+4=6)
    four four seven one  -> Four four seven one       (was four four seven four four four)
    21.7C / 48% / K9     -> all three, exact          (was 22.1C / 49% / ...)

# What this unblocks

Every number the system reports about itself, its tools, or its memories was
untrustworthy while this was live. HINDSIGHT's "numeric garbling" — blamed on
0.6/1.3 sampling and "fixed" with temp 0.15 — was **this**, which is why it
reproduced at temperature 0 and why that fix never worked.

# New forensics kept from the hunt

- `SP_HIDDEN_DUMP_DECODE=1` — keeps the KAI-5 hidden tap open through the **decode**
  steps (it used to close at prefill end, so we had only ever measured a path that
  makes none of the tokens the user sees). Default-off ⇒ byte-identical.
- `tools/reference/head_precision.py` — replays the engine's own hiddens through an
  honest f32 head and through a faithful int8-dp4a simulation; reports argmax flips,
  top-1 margins and logit noise. This is what caught the model wanting `'7'` at 9.0
  while the engine printed `'1'`.
- `POST /v1/debug/kdiff` — per-position global-K cosine (RoPE reaches the cache).

# THE STANDING LESSON

`gold 25/25` validates the **math core**. The served forward is the CUDA
`gemma4_kv_*` path, which the gold gates do not touch — and the *sampler* sits above
both. A gate suite that is green while the product is broken is measuring the wrong
layer. **G-VERBATIM is now the gate that stands between the model and the user, and
it runs after ANY engine / model / profile / sampler change.**
