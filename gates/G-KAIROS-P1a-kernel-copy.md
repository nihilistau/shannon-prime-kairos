---
type: gate-receipt
title: "G-KAIROS-P1a — kernel tree migrated, kairos build boots + coherent"
gate: "P1 increment a (copy/build/boot); P1 itself stays OPEN (legacy_policy slim, prefix snapshot, batch→persist = P1b/c)"
date: 2026-07-11
status: GREEN
---

# G-KAIROS-P1a — kernel copy + build + boot gate

## What landed

- `engine/` mirrors the staging engine SHAPE so build.rs runs UNPATCHED
  (engine_root = manifest/../..): `tools/sp_daemon` (crate, 125 source files —
  zero of the ~250 debris files at the staging root), `tools/sp_swarm` (path
  dep), `include/sp_engine` (C headers), `src/tokenizer` (C tokenizer).
- `core/` = shannon-prime-system submodule @ `36c2da38` (identical pin to
  staging `lib/shannon-prime-system`). Headers now come from kairos
  (`SP_SYSTEM_INCLUDE=core/include`).
- `engine/build-wirecuda.bat` — the ONE build entry point.
- `profiles/agent.toml` engine_exe → the kairos binary (rollback = one line,
  documented in the profile).

## Receipts (2026-07-11)

- Build: `cargo build --release --features wire_cuda_backend` EXITCODE=0 in
  1m36s (var/engine_build.log).
- Boot: `python serve.py agent` — daemon :3000 + gateway :8800 healths GREEN.
- Persist-KV alive on the kairos binary: `PERSIST-KV: reuse 1677 of 1677
  committed (drop 0); prefill suffix 63` (var/daemon.log).
- Coherence (daemon direct, /v1/chat): "What is the capital of France?" →
  "Paris." in 5 s; "What is 2+2?" → "2+2=4." in 5 s.

## Staging artifact dependencies (fall away at G-CLEAN-BUILD)

- `SP_SYSTEM_BUILD_DIR` → staging `build-cpu` prebuilt math-core .libs
- `SP_CUDA_BACKEND_DIR` → staging `build-host-cuda-backend`
  `sp_cuda_daemon_backend.lib`
- Toolchain env sourced from staging `scripts/env/env-cuda.bat` (machine-level
  compiler pins, not repo policy).

## Observations (NOT kernel failures; banked for the P2-stack backlog)

- Gateway OpenAI surface (`/v1/chat/completions`, blocking) with a hostile
  probe (max_tokens=16, temp=0) truncated mid-fence → recovery re-prompt
  rounds → 299 s and a wrong "5" for 2+2. Same composition would occur on the
  staging binary; the kernel-direct probe is clean. Lesson 5 (coherence probes)
  should use sane budgets; the agent surface deserves its own probe params.
- Same surface answered "capital of France" with "I'll need to search the
  web" — recall/persona/tool policy composition, P2 stack territory.
