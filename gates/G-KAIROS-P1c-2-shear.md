---
type: gate-receipt
title: "P1c-2 — gemma4_kv_shear: O(1) prefix restore; cold new-chat 123s → 5s"
gate: "G-KAIROS-PERF 'cold new-chat ≤ 20s' MET on the shear path"
date: 2026-07-11
status: GREEN
---

# G-KAIROS-P1c-2 — the prefix shear

## The insight

The charter asked for a save/restore snapshot verb. The refutation of the
capture_batched composition (G-KAIROS-P1c-1) forced a closer read of the ring
discipline, which yielded something better than a snapshot: **when the SWA
ring has never wrapped in this residency (dpos ≤ ring_W=2048), no slot in
[0..P) was ever clobbered** — slot(p)==p, and the journal-bounded REWIND_BOUND
discipline exists solely for the wrapped case. A new chat over the shared
constant preamble therefore needs NO copies at all: shear the position state
back to P. Rows [0..P) are the very rows prefill minted — byte-exact by
construction, all owners. Rows ≥ P are beyond dpos, unreachable by any
attention mask, and overwritten by the suffix prefill as it advances.

## What landed

- `gemma4_kv_shear(s, P)` in staging `src/backends/cuda/cuda_forward.cu`
  (research lands in staging first — HINDSIGHT continuity doctrine): guards
  bad P and the wrapped-ring case, syncs the stream, sets dpos (host+device),
  commit_pos=P, jcur=0.
- Glue shim `sp_daemon_cuda_kvdecode_shear` (both staging + kairos copies),
  Rust `kv::shear` in cuda_kvdecode_dispatch.rs.
- routes.rs `prefix_snapshot_restore` rewritten from the refuted capture
  composition to the shear (failure ⇒ 0 ⇒ full-prefill null floor unchanged).
- Profile `kv.prefix_snapshot = true` (env SP_PREFIX_SNAPSHOT=1).

## Receipts (2026-07-11)

- Backend lib rebuild GREEN; daemon link GREEN (24.7s).
- Gate battery (gateway spine authority, fresh sessions):
  - A warm-first: 67 s (queued behind the boot prewarm — unchanged cost)
  - C new-chat: **`PREFIX-SHEAR: restored the 1644-token shared prefix in
    20.4µs (O(1)); prefill suffix 74 (full would be 1718)` → "Tokyo." in 5 s
    end-to-end.** Baseline for the same shape this morning: 123 s.
- Coherence through the sheared prefix: persona + template intact.

## Follow-ups banked

- Probe B (first new-chat after A) full-prefilled instead of shearing (39 s) —
  entry hit the `pos == committed.len()` guard mismatch after A's post-turn
  machinery. Diagnose the pos/cl divergence; likely one more shear per session
  boundary to be had.
- Shear is in-VRAM only: a daemon restart still pays the one-time prewarm
  (~5 min byteexact grind — pre-existing). Disk persistence of the prefix
  would need the save/restore pair; only worth it if boot frequency demands.
- Conversations wrapping the ring (> 2048 tokens) decline the shear correctly
  (fall back to full prefill) — by design.
