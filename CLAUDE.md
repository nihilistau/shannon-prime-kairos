# CLAUDE.md — shannon-prime-kairos

**Read [`AGENTS.md`](AGENTS.md) first. It is the canonical orientation file for this repo.**

This file is a POINTER, not a copy. That is deliberate.

Two copies of one truth is the exact bug this codebase keeps getting hit by — an invariant enforced in
one of two paths is enforced in neither, because the unguarded path is the one that runs. It has cost us
a recall filter, a privacy guarantee, and a tombstone architecture. `core/CLAUDE.md` and
`engine/lib/shannon-prime-system/CLAUDE.md` are already byte-identical twins of each other and *will*
drift. This file will not become the third. Everything lives in `AGENTS.md`; this one only says where.

---

## The short version

- **Orientation, the bug class, the traps, the gates:** [`AGENTS.md`](AGENTS.md)
- **Memory and recall (read before touching `harness/skills/`):** [`docs/MEMORY-AND-RECALL.md`](docs/MEMORY-AND-RECALL.md)
- **What proves it still works:** [`gates/GATE-INDEX.md`](gates/GATE-INDEX.md)
- **The math core (a different repo, carried as a submodule):** [`core/CLAUDE.md`](core/CLAUDE.md) —
  that file is about `shannon-prime-system`, NOT about kairos. Do not take its status lines as kairos status.

## Non-negotiables (the full list is in AGENTS.md §1)

1. No claim without a repeatable gate. Name the command or do not make the claim.
2. Nothing in memory is ever deleted — tombstone or quarantine, never `open(p, "w")` minus a row.
3. Be honest about measured vs asserted. A verdict you cannot defend is a lie with a timestamp on it.
4. Her word never outranks his. An inference may never retire an observation.
5. Verdicts are rulings of committed finite tables over order-invariant signatures —
   prose and magnitudes never rule. See [`docs/INVARIANT-MEMORY.md`](docs/INVARIANT-MEMORY.md).

## Start the stack

```
python serve.py agent
```

`serve.py` is the only door into the engine. If a knob is not mapped in `build_env`, it does not exist.

## Before you say you are done

```
python harness_tests/g_claim.py
python harness_tests/g_durability.py
python harness_tests/g_memory_lifecycle.py
```

These are offline — no GPU, no daemon. The full list, and which gates need a live stack, is in
[`gates/GATE-INDEX.md`](gates/GATE-INDEX.md).
