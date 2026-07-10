# MIGRATION-MAP — every subsystem, its verdict, its gate, its source of truth

Verdicts: **KEEP** (migrate by re-gating, minimal change) · **REWRITE**
(functionality kept, seam changes) · **RESEARCH** (stays in staging; not in the
production path) · **DEAD** (refuted/convicted; receipts only).

| subsystem | today (staging) | verdict | kairos home | gate to land | OKFS receipt |
|---|---|---|---|---|---|
| math-core byte-exact forward (OK_Q4B, CRT/NTT, Barrett) | shannon-prime-system (submodule) | KEEP | core/ (same submodule) | G-CLEAN-BUILD + gold 24/24 | 55e022c6, gold-instrument |
| kvdecode resident lane + SWA ring + persist-KV LCP | engine routes.rs/daemon.rs | KEEP (+prefix snapshot) | engine/ | G-PERSIST-B4, G-KAIROS-P1 | 55e022c6 |
| capture/mint verbs (ep.k/ep.l5, qkey) | engine | KEEP (dedicated handle) | engine/ | G-B4-GROW-RECALL-L5 re-run | 9ca1ce0f, 5d76b8f0 |
| L5 recall + attr-gate + MEM-OKF policy dispatch | engine routes.rs inline | REWRITE (policy → harness) | harness/ | audit suite + G-MEMPOLICY-V3 re-run | 171c675e, cbea4d38 |
| SP_SPINE in-kernel recall variant | engine | DEAD in production (persona leak on foreign Qs) | — | — | 1264a862 |
| B4 NIGHTSHIFT growth + registry persistence | engine | KEEP | engine/ + tools/memory_doctor | G-B4-GROW-RECALL-L5 | 9ca1ce0f |
| C2-sig q·K scan / W_c head / judge cascade / two-stage / margin-NULL / FM steering | engine | RESEARCH or DEAD | staging | — | 2637657d, 2f92e487, cbea4d38 |
| harness: run_with_tools + fence-drift parse + skills | harness | KEEP | harness/ | G-PK2-TOOLROBUST + parser gate | 6baa9fa3 |
| spine (decide→execute→verify) + task loop + agency | harness | KEEP | harness/ | G-PK2-SPINE/-2 + flywheel | ADR-007/008 |
| personality PF-B1..B5 (+ tools wired) | harness | KEEP (close the interceptor-vs-spine gating asymmetry during move) | harness/ | h_personality_* 5/5 | dd122e50 |
| FastMCP server + bridge | harness/mcp_server | KEEP | mcp/ | G-MCP-SERVER 3/3 | 6baa9fa3 |
| web console (autodetect, cards, persona editor) | engine frontend_mockups | KEEP | console/ | live-play | 6baa9fa3 |
| decision heads: spectest veto | engine + f3 head | KEEP (armed) | engine/heads/ | G-SPECTEST-V2 | c57745f1 |
| decision heads: route / INT2 / W_c | engine | RESEARCH (carried unarmed) | staging | — | 96642630 |
| MTP/spec_step verify machinery | engine (spec.rs unwired; cpu_forward qwen3_mtp_*) | KEEP machinery; **blocked on a high-acceptance drafter** (prompt-lookup = 0.87× on real text — degenerate-prompt 1.76× was an artifact) | engine/ (P5) | drafter H2H gate first | mtp-t8 honest correction |
| ADR-011 FFN offload / ADR-012 full tail | engine + submodule | KEEP default-off (VRAM levers + refutation receipts) | engine/ | G-ADR11/12 receipts carried | project notes |
| batched prefill under ring (ADR-009) | engine | REWRITE (make it a valid persist base / suffix-batch) | engine/ | G-KAIROS-PERF | ADR-009 |
| dp4a prefill GEMM | engine | DEAD (honest negative) | — | — | PK2 wave 2 |
| diffusion judge lane (N-series, prefix-KV, packed) | engine | RESEARCH (sealed) | staging | — | 597a1613 |
| XBAR rings / KAIROS audio / telepathy / swarm | engine+lattice | RESEARCH (until a production consumer exists) | staging | — | various |
| PPT-LAT lattice engine | lattice | RESEARCH (never the default engine) | staging | — | feedback: lattice-not-default |
| L1 ABI | engine/core | KEEP verbs only (dual-model co-residency: MeMo/telepathy delegate) | core/ | sp_memo smoke | 52353675 |
| OKFS/MEM-OKF tooling (okf_mem, okf_validate) | lattice tools/ | KEEP | tools/ | G-OKF-CONFORM on kairos store | reference-mem-okf |
| launcher zoo (~150 .bats) | engine root | REWRITE → profiles/*.toml + serve.bat | profiles/ | G-KAIROS-P3 | audit pt1/pt2 |
| test corpora (SNE/faithful/61-fact) | engine _faithful_corpus | RESEARCH (GATE-ONLY, never production registry) | staging | — | Hodor/SNE leak notes |
