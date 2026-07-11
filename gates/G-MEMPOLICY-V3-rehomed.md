---
type: gate-receipt
title: "P1b-2b — MEM-OKF per-entry policy dispatch REHOMED to the harness recall executor; G-MEMPOLICY-V3 offline 10/10; GOLD 25/25"
date: 2026-07-11
status: GREEN
---

# P1b-2b + gold + r1

## Charter correction first

The task was framed as "move admission/classify to harness" — but the
MIGRATION-MAP verdict for B4 NIGHTSHIFT growth + registry persistence is
**KEEP (engine)**: capture/admission run on the batched forward and stay
kernel-side. What the map marks REWRITE→harness is the **MEM-OKF policy
dispatch** — and post-rehoming that gap was REAL: harness spine recall
returned raw registry text with no per-entry policy, so a private-secret row
could be blindly injected into a recall note.

## What landed (all Python — the rehoming dividend)

- `search_memories_ranked_rows` (rows, not just text) + `attr_absent` in
  harness/skills/memory.py; DECLINE_MSG doctrine constant.
- spine `recall_decider` dispatch: private-secret + absent attr ⇒
  `decline_recall` (secret text never leaves the decider); private-secret +
  present attr ⇒ recite; counterfact ⇒ authoritative override framing;
  persona/untagged ⇒ plain note.
- Gateway `decline_recall` short-circuit: the fixed decline streams with
  **ZERO model inference** (turn never reaches the daemon; confab/leak
  impossible by construction) + typed `recall_decline` event + canonical
  transcript append.
- Calibration honesty: the engine runner's `>= 0.6·|qs|` absent rule is
  untrippable on its own printed data — recalibrated to "≥2 salient absent AND
  ≥ half the salient set". Question/aux words joined the match stop-list
  (they diluted "when did my locker combination last change?" to 0.33 vs the
  0.34 threshold — the same class of miss as the morning's clause bug).
- serve.py `--gateway-only`: schema-checked gateway bounce (the hand-rolled
  env wedge can't recur — the launcher owns the env).
- r1 truncation fix: post-tool rounds keep `eot_bias=0` (at temp 0.15 the
  +4-biased EOT beat the repetition-penalized 't mid-word — died at "I don'"
  twice). Round observability line added ([agent] round/is_tool/buf/flushed/calls).

## Receipts (2026-07-11)

- **G-MEMPOLICY-V3 (offline, rehomed): PASS 10/10** — counterfact framing,
  secret recite, decline decided, zero-inference (stub never called), typed
  event, transcript append, no-leak, null floor. Audit trio re-PASS after the
  stop-list change (spine 9/9, spine-2 12/12, toolrobust 10/10).
- **GOLD: 25/25 (100%)** on the kairos-built math-core (clang-cl + Ninja from
  the core/ submodule; `__udivti3` needed clang_rt.builtins-x86_64 in the exe
  linker flags; T_RING3_NATIVE needed its fixture copied from the
  shannon-prime-system checkout — both environmental, zero math failures).
- The persist guard-miss diagnostic caught a live anomaly on its first day:
  `pos=3011 != committed 2969` — a prewarm read position mid-turn of a
  concurrent client; the guard fails CLOSED (full prefill). Banked: turn
  serialization across the position-read + LCP window.

## Banked

- Multi-client queueing on the single resident session makes concurrent-probe
  timing measurements meaningless — bench discipline: one client at a time.
- mem_class provenance: live rows are classified by the kernel heuristic at
  capture; the harness dispatch trusts the tag. A memory_doctor audit pass
  over old rows' classes would harden the attr-gate's reach.
