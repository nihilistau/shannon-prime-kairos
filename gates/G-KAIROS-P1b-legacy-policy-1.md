---
type: gate-receipt
title: "P1b increment 1 — legacy_policy feature; research/dead lanes fold to compile-time-false"
gate: "P1 stays OPEN (this is the flag + first tranche; the proven-policy extraction to harness executors is P1b-2)"
date: 2026-07-11
status: GREEN
---

# P1b-1 — the legacy_policy feature

## What landed

Cargo feature `legacy_policy` (DEFAULT-ON). With the feature, behavior is
identical to yesterday. Without it (`--no-default-features --features
exact,wire_cuda_backend`), these routes.rs lanes fold to compile-time-false
(all RESEARCH or DEAD per MIGRATION-MAP):

SP_SPINE in-kernel recall (DEAD, persona leak, OKFS 1264a862) · telepathy-chat
routing · the B3 q·K scan trigger + QDUMP dataset rail · INT2 C2-Hamming cull ·
W_c head (superseded) · F2b jaccard stage · B3 generative-judge cascade
(refuted, cbea4d38) · disposer/knockout modes · FM steering · F3 capture rail ·
COCONUT thoughts.

UNTOUCHED (the proven one-config stack): L5 cosine recall + attr-gate +
MEM-OKF policy dispatch, B4 NIGHTSHIFT growth + persist, persist-KV LCP,
spectest veto (KEEP armed), capture/mint verbs.

Transform style: `cfg!(feature = "legacy_policy") && …` at each lane's flag
initializer/condition head — minimal reviewable diff; ON-build codegen carries
the same runtime env checks as before (byte-identical behavior); OFF-build
folds each lane to constant-false. Full #[cfg] source exclusion is P1b-2+.

## Receipts (2026-07-11)

- Default build: EXITCODE=0 in 26.29s (var/p1b_build.log).
- OFF config: `cargo check --no-default-features --features
  exact,wire_cuda_backend` EXITCODE=0 in 55.87s (var/p1b_check_off.log).
- Behavior gate on the default binary: boot GREEN; recall probe via gateway
  spine authority → "Knack." (123s cold: prewarm 1652-tok prefill + 1712-tok
  recall turn serialized — the P1c prefix-snapshot target); SPECTEST PASS
  observed on a delivery turn (4/6 salient, authority=head).

## Observation banked (pre-existing, NOT a P1b regression)

An abandoned SSE client (probe process died mid-stream) left the daemon turn
blocked with metrics still responsive; recovered by stack restart. The
kernel's dead-client handling (blocking_send on a closed channel) deserves a
P1c look alongside the snapshot verb.
