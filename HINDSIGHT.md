---
type: charter
title: "PROJECT HINDSIGHT — Shannon-Prime rebuilt with 8 months of hindsight"
description: "The charter: what we would build from scratch knowing what we know now; the keep/rewrite/drop verdicts; the gated migration into shannon-prime-kairos; the performance program back to llama.cpp parity."
tags: [hindsight, charter, kairos, architecture, migration, performance]
sp_status: ACTIVE
sp_gate: "phase gates G-KAIROS-P0..P5 (defined §6)"
sp_commit: "kairos genesis"
sp_repro: "read this file; every claim cites its OKFS receipt"
---

# PROJECT HINDSIGHT

## 0. Why (the operator's ask, 2026-07-10)

Eight months of continuous building stacked research on research. The system
works — byte-exact 12B, real memory, real tool calling, personality, a proven
engine — but the *composition* rotted: flags fight each other (B4 silently
killed the O(1) conversation cache → minutes-long tool calls), three recall
authorities coexist, ~150 launcher .bats encode config as env-var ladders, and
the daily driver is whichever bat was edited last. HindSight = look at the
whole organism as it stands, keep what's proven, rewrite what composition
broke, drop what's dead, in ONE production repo: **kairos**.

## 1. The ten lessons that define the rebuild

1. **Policy in the kernel was the mistake.** routes.rs grew a ~4000-line
   env-branch ladder where recall/memory/persona policy lives inside the
   inference loop. ADR-002 (decide latent / execute clean) was right — apply it
   to the PROCESS architecture: the Rust daemon is a **kernel** (inference,
   KV, capture verbs, zero policy); ALL policy (recall delivery, memory
   admission, persona, tools, telemetry) lives in the harness layer.
2. **Flags are not a config system.** `set "VAR"` no-ops, banner drift, and
   mutually-hostile flags (SP_B4_NIGHTSHIFT vs SP_PERSIST_KV) each cost a day.
   Kairos: ONE `config.toml` per profile, a loader that echoes the EFFECTIVE
   config at boot, and a generated flags registry doc. Launchers become
   `serve.bat <profile>`.
3. **One recall authority.** L5-cosine + attr-gate + per-entry MEM-OKF policy
   is the proven stack (OKFS 171c675e, cbea4d38). C2-sig scan (dead at
   TAU=+inf), W_c (superseded), judge cascade (refuted) — carried as research,
   not wired.
4. **The conversation cache is sacred.** Nothing may touch the resident
   session except prefill/decode of the conversation itself. Capture, query
   embeds, judges run on separate handles/batched forwards BY CONSTRUCTION
   (typestate, like Tier1Decider/Tier2Executor). Persist-KV LCP reuse is the
   default; the system preamble is a first-class cached prefix.
5. **Byte-exactness needs a coherence gate.** SHA parity passed bit-identical
   garbage twice. Every kairos gate pairs determinism with a curl-level
   coherence probe.
6. **Composition needs its own gates.** Everything was individually GREEN and
   collectively broken. Each kairos phase gate exercises the WHOLE profile
   (memory+persist+recall+tools together), not just the new part.
7. **Live-play is a gate class** (the Hodor lesson). Every phase ends with an
   operator session.
8. **The mount lies, native git tells the truth.** All ops on Windows repos
   via native PowerShell. (Binding since 2026-06-25; still catching us.)
9. **OKFS is the memory of the project itself.** Pre-flight lookup before
   building; every verdict recorded with receipts. Kairos seeds its store with
   continuity pointers to the staging stores rather than copying 400 entries.
10. **Honest negatives ship default-off with receipts** (ADR-011/012 pattern) —
   they are levers and refutation records, not dead code.

## 2. What kairos IS (target architecture)

```
kairos/
  engine/          Rust daemon KERNEL (from tools/sp_daemon, slimmed):
                   /v1/chat (SSE), /v1/capture, /v1/embed, session verbs,
                   persist-KV LCP + prefix snapshot, NO policy branches.
  core/            math-core as the SAME git submodule (shannon-prime-system).
  harness/         the agent layer (from shannon-prime-harness): gateway :8800,
                   spine (decide→execute→verify), tools (@skill + MCP bridge),
                   memory policy (MEM-OKF v2), personality, task loop, agency.
  mcp/             FastMCP server + bridge (landed 2026-07-10, G-MCP-SERVER).
  console/         the web console (gateway-autodetect, cards, persona editor).
  memory-okf/      production OKFS store (okf_mem.py/okf_validate.py in tools/).
  gates/           every G-* gate that seals a migrated subsystem + receipts.
  profiles/        config.toml per serve profile (chat / agent / gate / bench).
  tools/           memory_doctor, okf tooling, bench harnesses.
```

Two processes stay (kernel + harness) — merging them buys nothing and loses
Rust/Python isolation. What changes is the CONTRACT: the kernel exposes ~8
verbs; the harness owns every decision. The console speaks only to the harness.

## 3. Keep / rewrite / drop (the hindsight verdicts)

**KEEP AS-IS (proven, migrate by re-gating):** math-core (byte-exact OK_Q4B
forward, CRT/NTT, 24/24 gates); the kvdecode resident-cache lane + SWA ring +
persist-KV LCP; capture/mint verbs; L5 recall + attr-gate + MEM-OKF v2 policy
dispatch + SP_QKEY_MINT; B4 admission + registry persistence (+ memory_doctor);
the harness (spine, run_with_tools with fence-drift parsing, skills, PF-B1..B5
personality, MCP layer); MTP T8 (40.8 tok/s bit-identical — re-gate and turn ON
in the agent profile); ADR-011 CPU FFN offload (VRAM lever, default-off);
the console; OKFS/MEM-OKF tooling; the decision heads (spectest veto armed;
route/W_c/INT2 carried unarmed).

**REWRITE (works, but composition-hostile):** routes.rs recall/memory region →
policy moves to harness, kernel keeps verbs (the ~1500-line else-ladder dies;
the spine variant — which leaked persona records on foreign questions,
OKFS 1264a862 — is superseded by harness-side policy rather than fixed
in-kernel); env-flag config → profiles/config.toml + effective-config banner;
launcher zoo (~150 bats) → `serve.bat <profile>`; registry loading → WARN on
dead rows + startup orphan scan (rot was silent for weeks); tool preamble →
assembled once per session, cached as a KV prefix snapshot, not re-sent text.

**DROP from production (stay in staging as research/receipts):** C2-sig q·K
recall scan; the 26B judge cascade (refuted); two-stage delivery (refuted);
margin-NULL (convicted); FM steering (convicted); dp4a prefill GEMM (honest
negative); diffusion-judge serving lane (sealed research); the SNE/faithful
test corpora (GATE-ONLY, never near a production registry); poison-pill/DH
swarm mechanics (rejected, receipts kept); ~40 root-level scratch bats.

**PPT-LAT / L1 ABI necessity (the operator's question):** the lattice is NOT in
the production serve path — the daily driver is engine-CUDA + daemon + harness
end to end. L1 ABI is required ONLY for dual-model co-residency (MeMo executive
+memory, telepathy CPU delegate) — keep the verbs, skip the rest. PPT-LAT stays
the research lane in the lattice repo (PPT-ARM primary, lattice extension —
OKFS reference). Kairos takes ZERO lattice code into the serve path.

## 4. The performance program (why 100× off is a composition bug, not physics)

Measured hardware truth: decode null floor **24.4 tok/s** (llama.cpp ~53 on the
same box; we've been within 10%); **MTP T8 = 40.8 tok/s bit-identical, sitting
default-off**. The minutes-long agent turns decompose as:

| cost | cause | fix | status |
|---|---|---|---|
| ~1.5k-tok re-prefill EVERY turn | SP_B4_NIGHTSHIFT force-disabled persist-KV (routes.rs:1390) | SP_PERSIST_B4=1 (capture runs on the batched forward, not the session; pos==cl guards the rest) | **fixed 2026-07-10**, gate G-PERSIST-B4 pending seal |
| fresh-conversation cold prefill | LCP reuse bounded by REWIND_BOUND=32 → new chats re-prefill the constant preamble | preamble **prefix snapshot** (engine has snapshot/rewind verbs from KAI-1b): snapshot after the system prefix once, restore + suffix-prefill per new chat | kairos P1 |
| prefill ms/tok itself (~75–233ms) | byte-exact integer-attention prefill; float path produces garbage; ADR-009 batch (~7×) DECLINES under persist | (a) fix batch→persist handoff (batch-prefill the suffix, then continue per-token), (b) the float-path repair = the single biggest engine unlock | kairos P1–P2 |
| decode 24.4 vs 53 | MTP off; per-token launch overheads | enable MTP (40.8 proven); profile the residual gap to llama.cpp with pinned clocks | kairos P1 |
| tool-round turnaround | preamble re-sent as text each round | rounds are strict extensions (persist already covers); preamble snapshot covers round 1 | mostly free after persist fix |
| numeric garbling of tool results | 0.6/1.3 sampling paraphrases numbers | post-tool rounds at temp 0.15/rep 1.05 + verbatim rule | **fixed 2026-07-10** |

Gate for the program: **G-KAIROS-PERF** — agent profile, warm session: simple
tool turn ≤ 15 s end-to-end; plain chat turn ≤ 5 s to first token; decode ≥ 40
tok/s (MTP); cold new-chat ≤ 20 s (snapshot restore + suffix). Stretch: within
15% of llama.cpp decode on the same weights.

## 5. Memory architecture (unchanged doctrine, cleaner seams)

MEM-OKF v2 is the single format across engine (execute), harness (ingest),
agency (curate), L5 (retrieve). Kairos changes only the seams: capture on a
dedicated handle; registry writes through one library (no inline JSON in three
places); load warns on rot; memory_doctor ships in tools/; the production
registry lives under `var/memory/` with the backup/remint discipline from the
2026-07-10 audit. One recall authority per serve, enforced by config schema
(profiles cannot express two).

## 6. Migration phases (each = one gate + one operator live-play)

- **P0 (today): genesis.** This charter, MIGRATION-MAP.md, OKFS store seeded
  with continuity pointers, profiles/ sketched. Gate G-KAIROS-P0 = okf_validate
  GREEN on the seed store.
- **P1: the kernel.** Copy tools/sp_daemon → engine/ (history pointer in OKFS),
  math-core submodule, slim the routes policy region behind a `legacy_policy`
  feature flag (on = byte-identical today-behavior; off = verbs only). Land
  preamble prefix-snapshot + batch→persist handoff + MTP-on profile.
  Gate G-KAIROS-P1 = today's serve byte-identical under legacy_policy=on +
  G-KAIROS-PERF numbers under the new profile.
- **P2: the harness.** Copy harness → harness/, move recall/memory/persona
  policy from kernel to harness executors (spine verify law). Gate = the
  2026-07-10 audit suite (persistence across restart, personality 5/5,
  G-MCP-SERVER, toolrobust) all GREEN against the kairos stack.
- **P3: console + profiles.** Console autodetect, profiles replace launcher
  zoo. Gate = live-play session, zero localStorage/bat edits needed.
- **P4: production cutover.** Daily driver = kairos serve.bat agent. Staging
  repos get ARCHIVED-status READMEs pointing here; OKFS stores cross-linked.
- **P5: the perf ladder.** Float-path repair, prefill program, llama.cpp
  parity bench (pinned clocks, both engines on-box — the perf-methodology
  lesson), published in gates/receipts.

## 7. Continuity

Staging repos are never rewritten or deleted; every kairos subsystem's OKFS
entry carries `mem_provenance` pointing at the staging commit it was proven at.
The staging OKFS stores remain the research record; kairos's store holds only
production doctrine + phase receipts.
