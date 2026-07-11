---
type: gate-receipt
title: "P1b-2a — console REHOMED to the gateway; ONE recall authority; two live-play-caught harness fixes"
date: 2026-07-11
status: GREEN (follow-ups banked)
---

# P1b-2a — the rehoming

## What landed

- **Console chat → gateway (:8800)**: `CHAT_BASE` probes `/health` every 15 s;
  gateway serving ⇒ chip `gateway · spine recall`; gateway down ⇒ chip
  `⚠ recall offline — kernel-only (gateway down)` and chat falls back to
  daemon-direct with `auto_recall:false` EXPLICIT (the kernel serves verbs;
  recall policy lives in the harness — degraded but honest). Console now sends
  `session_id` (canonical transcripts; rotates on reload). The daemon keeps the
  metrics/telemetry/abort surface.
- **Kernel in-kernel L5 delivery lane** gated behind `legacy_policy` (cfg!,
  compile-time-false in the kernel build; default build byte-identical).
- **Recall clause fix** (live-play caught): query-normalized token overlap
  diluted under polite prefixes — "quick check: what is my name?" scored 0.33
  vs the 0.34 threshold (bare form scores 1.0). search_memories_ranked now
  also scores the final [.:;!]-clause and takes the max.
- **Late-fence stream hold** (live-play caught): a fence past the 80-char hold
  window streamed RAW to the UI with no recovery path. The decode stream now
  tracks a flushed offset and HOLDS from the first fence marker; the
  end-of-generation parse decides (execute / re-prompt / flush the tail).
- **Persist guard-miss diagnostic**: a silent `pos != committed` miss used to
  mean a silent minutes-long full re-prefill; it now logs both numbers.

## Receipts (2026-07-11, clean serve.py boot)

- Offline: prefixed + bare name queries both `inject_recall` Knack facts;
  spine 9/9, spine-2 12/12, toolrobust 10/10 re-PASS after both fixes.
- Live battery via gateway spine authority: r1 prefixed-recall first-turn
  (170 s = fresh-boot prewarm queue + a web_search tool round);
  **r2 "and my cat?" → "Tuffy." 22 s** (clause fix + canonical transcript);
  r3 fresh session → shear 15.7 µs, 6 s. No raw fences anywhere.
- Gateway restart cost with a warm daemon: prewarm rode the SHEAR
  (`63.6 µs + 6-token suffix`) — gateway bounces are now ~1 s, not a re-grind.

## Banked follow-ups

- r1's final answer text tail-truncated ("I don'") after its tool round —
  agent multi-round composition quirk, needs a round-2 stream trace.
- A gateway launched with a HAND-ROLLED env (not serve.py) produced a wedged
  daemon turn (GPU 1%, no log after S1). serve.py's one-authority env schema
  is the ONLY supported launch — reinforces the P3 lesson; do not sidestep it.
- P1b-2b remains: physically move admission/classify policy to harness
  executors + full #[cfg] source exclusion (G-MEMPOLICY-V3 re-run as its gate).
