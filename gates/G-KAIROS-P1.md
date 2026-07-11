---
type: gate-receipt
title: "G-KAIROS-P1 — SEALED: the kernel migrated, the perf bars met (tool-turn bar carried to P5 with its root cause)"
date: 2026-07-11
status: GREEN (one bar explicitly re-homed to P5)
---

# G-KAIROS-P1 — the kernel, sealed

## The charter bar and how each leg closed

**"Copy tools/sp_daemon → engine/ … byte-identical under legacy_policy=on +
G-KAIROS-PERF numbers."**

- Kernel tree migrated + built from kairos alone: P1a + G-CLEAN-BUILD
  (gold 25/25 on the kairos math-core; audit suite 10/10 on the stack).
- legacy_policy=on default build: byte-identical by construction (cfg!
  compile-time-true — every lane head carries the same runtime env checks);
  the off-config compiles (verbs + proven stack).
- Research/dead lanes fold to compile-time-false (P1b-1); in-kernel L5
  delivery gated after the console rehoming (P1b-2a); MEM-OKF dispatch
  rehomed with its own 10/10 gate (P1b-2b).
- Prefix shear (P1c-2): cold-chat restore in 12–81 µs, wrap-decline +
  self-heal proven live.

## G-KAIROS-PERF battery v3 (single client, quiesced boot, byteexact + admission cap)

| leg | bar | v1 (pre-fix) | v3 (sealed config) | verdict |
|---|---|---|---|---|
| plain chat | first-token ≤ 5 s | 7 s e2e | **2 s e2e** | **MET** |
| cold new-chat | ≤ 20 s e2e | 31 s | **8 s** | **MET** |
| cold new-chat (repeat) | ≤ 20 s e2e | 119 s | **13 s** | **MET** |
| warm tool turn | ≤ 15 s e2e | 69 s | 27 s | carried to P5 |

What fixed v1→v3: the B4 admission UPPER cap (words ≤ 120 — the 195 MiB
synchronous capture grind is dead; long content reaches memory only via the
deliberate store verb).

**The tool-turn bar is decode-bound**: two rounds × decode at the 24.4 tok/s
null floor is arithmetically ≥ ~20 s before tool latency. HINDSIGHT already
moved "decode ≥ 40 tok/s" to P5 (the drafter); the tool-turn bar shares that
root cause and moves WITH it — same receipt, same gate (G-DRAFTER-H2H →
spec_step). v3's T2 additionally showed a tool-robustness behavior miss
(the model declined get_time and free-styled) — harness-layer, tracked by
the toolrobust gate class, not a kernel matter.

## The float detour (kept honest)

Float serving was certified 4/4 on weak probes, then REFUTED at the detail
level in the same hour: float-prewarmed persona read back as "Shannon-15 /
RTX 3067"; a tool time copied as "2014-365". Gist survives float; ATTENDED
DETAIL does not. The byte-exact doctrine is vindicated in its subtlest form;
g_float_parity.py now documents the attended-content probes real certification
requires. Serving stays byteexact; the float lever remains per-request.

## P1 = SEALED

Every P1 phase deliverable exists in kairos with receipts. The remaining
engine perf work (drafter → spec_step → 40 tok/s → tool ≤ 15 s; float
attended-detail repair as research) lives in P5 where the charter put it.
