---
type: gate-receipt
title: "P1c increment 1 — dead-client guard LANDED; prefix-snapshot-via-capture_batched REFUTED (honest negative, lever ships default-off)"
date: 2026-07-11
status: MIXED (guard GREEN / snapshot composition RED with receipts)
---

# P1c-1

## 1. Dead-client guard — LANDED

`blocking_send` on a full 64-cap SSE channel whose peer is half-open blocks the
turn thread forever (observed twice this session; metrics stay green while the
session wedges). New `send_deadline` (try_send + 20 ms retries, 30 s sustained-
Full ⇒ dead peer ⇒ abort turn) replaces blocking_send at the decode-loop Emit/
Stopped sites and the SPECTEST release/veto sites. A live client drains 64
events in microseconds — the deadline can only fire on a dead peer.
Gate: build GREEN; post-restart coherence "Hello!" through the guarded path.

## 2. Prefix-snapshot via capture_batched — REFUTED at preamble scale

The composition (LCP-miss ⇒ capture_batched(prefix) once ⇒ reset_cold +
replay(P) + suffix prefill) is architecturally clean — batched forward on a
scratch cache, resident session untouched, same-position replay is RoPE-aligned
— but the measurement kills it: capturing the 1652-token preamble ground
**10+ minutes at 100% GPU** (11.9/12 GiB, `recall WRITE: store 540.1 MiB over
48 layers`) with zero files landed before the gate clients timed out. The
episode-capture machinery is built for ~30-token episodes; the preamble is 50×
out-of-distribution (VRAM-starved batched forward + a 540 MiB disk store per
snapshot).

Verdict: code stays as a DEFAULT-OFF lever (`SP_PREFIX_SNAPSHOT=1`, profile
`kv.prefix_snapshot=false`, ADR-011/012 pattern). Any failure path inside the
lever returns 0 ⇒ the byte-identical full-prefill null floor.

## 3. The real fix = P1c-2 (the charter's actual words)

HINDSIGHT §4 said "new CUDA-lane verb: save/restore KV[0..P) + ring state" —
now we know WHY it must be a new verb: the resident cache already HOLDS the
preamble K/V after the prewarm; snapshotting is a device-side row copy
(GPU→host pinned or GPU→GPU spare), restore is the copy back. No re-forward,
no disk, no scratch-cache VRAM spike. Est. ~540 MiB memcpy ≈ sub-second.
The routes-side seam landed here (the LCP-miss else-branch + slot bookkeeping)
is exactly where that verb plugs in.

## Timings recorded

- Boot prewarm grind: ~5 min at 100% GPU (pre-existing, documented in app.py —
  byteexact prefill; queues first turns behind it: hello 270 s, recall 123 s).
- Warm turns remain 5–9 s; strict extensions hold on the P1c binary.
