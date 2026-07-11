---
type: gate-receipt
title: "P5 LAUNCHED — perf battery measured (P1 stays open, honestly); float path COHERENT on this build; drafter pipeline landed"
date: 2026-07-11
status: MEASURED / LAUNCHED (P1 seal withheld; P5 in progress)
---

# The perf ladder, opened with receipts

## 1. G-KAIROS-PERF battery (single client, quiesced clean boot)

| leg | bar | measured | verdict |
|---|---|---|---|
| T1 warm chat | first-token ≤ 5 s | 7 s e2e | marginal |
| T2 warm tool turn | ≤ 15 s e2e | **69 s** | MISS |
| T3 cold new-chat | ≤ 20 s e2e | **31 s** (shear 13.8 µs ✓) | MISS |
| T4 cold new-chat | steady-state | **119 s** (shear 11.4 µs ✓) | MISS |

**P1 is NOT sealed on these numbers.** The persist/shear lanes are perfect —
the time goes elsewhere, and the battery itself caught the main thief:

**B4 NIGHTSHIFT capture contention.** Admission has a lower word bound but NO
UPPER bound; a long turn's capture_batched grinds the GPU synchronously (the
2,100-char float probe triggered a `recall WRITE: store 195.2 MiB` — minutes)
while the next turn queues on the session. Fix candidates (banked, kernel):
an admission length cap (words ≤ ~120), and/or deferring capture to an idle
tick instead of the turn boundary. Secondary suspect: byteexact decode rate on
the kairos binary (measure decode tok/s in isolation before/after).

## 2. P5a — the float path is COHERENT on this build

- Suffix+decode float probe: "Paris." at temp 0.
- **Cold FULL float prefill** (~2,100 fresh tokens, no shared prefix,
  byteexact:false, temp 0): a detailed, ACCURATE one-sentence summary of the
  passage. Zero garbage.

The doctrine note ("float path produces garbage", "coherent↔garbage across
rebuilds") described a BUILD-DEPENDENT failure — latent UB, not a wrong
algorithm. Today's clean kairos backend (clang-cl/nvcc from G-CLEAN-BUILD)
does not exhibit it. One probe cannot certify a rebuild-dependent mode, so the
P5a repair task is now precisely scoped:
- **Certification path**: a boot-time float-vs-exact parity self-check (short
  reference prefill in both modes at temp 0; mismatch ⇒ float serving refused,
  byteexact floor kept). Cheap, honest, turns "trust" into a per-boot gate.
- **If certified**: float serving kills the byteexact prefill tax (~30 ms/tok),
  the ~5-min boot prewarm grind, and re-opens ADR-009 batch prefill — the
  single biggest unlock, exactly as HINDSIGHT predicted.

## 3. P5b — the drafter project is LAUNCHED

- `tools/drafter/datagen.py`: (hidden[t] → hidden[t+1]) pairs via the proven
  KAI-5 SP_HIDDEN_DUMP rail; corpus = the repo's own prose; 60k-pair target.
- `tools/drafter/fit_drafter.py`: EAGLE-lite head (PCA-whiten 768 → MLP →
  ĥ[t+1]) — the exact KAI-5 v2 recipe that hit val_cos 0.637 on Mimi.
- `profiles/drafter-datagen.toml`: isolated registry, growth OFF (the Hodor
  lesson at profile level), hidden-dump armed via the new serve.py [debug] knob.
- On-metal H2H already exists: SP_EAGLE_ACCEPT (eagle_accept.rs) + the
  gemma4_draft_step FFI — the drafter head slots into a built harness.
- **Gate to seal P5-drafter**: offline top-1 acceptance proxy through the
  frozen LM head ≥ 25%, then SP_EAGLE_ACCEPT on-metal accept ≥ 2/8 mean,
  then spec_step wiring → decode ≥ 40 tok/s.

Run order (operator, ~overnight):
  python serve.py drafter-datagen
  python tools/drafter/datagen.py        (~1-2 h, 60k pairs)
  python serve.py agent --stop
  python tools/drafter/fit_drafter.py    (GPU free; ~1 h)

## 4. Session hygiene

Probe turns pruned from the production registry again (444 → 441, backup
kept). The capture-cap fix above would end this class of pollution at the
admission gate.
