# gates/ — the acceptance bar

Every migrated subsystem lands with its G-* gate GREEN + receipts here.
Phase gates: G-KAIROS-P0 (OKFS seed conform) .. G-KAIROS-P5 (llama.cpp parity ladder).
See HINDSIGHT.md section 6 and MIGRATION-MAP.md.

**GATE-INDEX.md is the full list**: every executable gate in `harness_tests/g_*.py`,
grouped by area, with what it protects, whether it needs a GPU/daemon (OFFLINE /
LIVE / BROKEN), and its run command. Start there for "what proves this still works?"
or "what can I run right now with no stack up?". Convention: every new gate gets a
row in GATE-INDEX.md in the same commit that adds it — an unindexed gate is the
exact problem that file exists to prevent.
