# shannon-prime-kairos — the PRODUCTION repo

**Project HindSight** (started 2026-07-10): the 8-month Shannon-Prime build,
re-assembled as we would build it knowing what we know now. This repo is the
**production** home; the four staging/research repos stay alive as the lab:

| staging repo | role going forward |
|---|---|
| `shannon-prime-system-engine` | engine research staging (CUDA/daemon experiments land here first) |
| `shannon-prime-system` | math-core (stays the submodule of record) |
| `shannon-prime-harness` | agent/harness research staging |
| `shannon-prime-lattice` | papers, OKFS research store, PPT-LAT research lane |

**Nothing lands here without its gate GREEN + receipts.** Proven subsystems
migrate in phases (see `HINDSIGHT.md` §6); everything else stays in staging.
OKFS is canonical here exactly as it is in the lattice — `memory-okf/` is this
repo's production knowledge store, seeded with continuity pointers back to the
staging stores.

Start: `HINDSIGHT.md` (the charter) → `MIGRATION-MAP.md` (keep/rewrite/drop,
per subsystem) → `gates/` (the acceptance bar for every phase).
