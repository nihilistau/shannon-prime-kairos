---
type: audit
title: "MEMORY AUDIT — 'is it actually living?' No. It is append-only, single-voiced, and never edits itself."
date: 2026-07-12
status: DIAGNOSED (cleanup done; the living-memory build is the next project)
---

# What the registry actually contained (before cleanup)

- **524 rows.**
- **35 voice-test rows**: `The user said: [voice utterance — injected as 4 latent
  audio frames]` — test data captured into PRODUCTION memory.
- **55 duplicate texts** (same fact stored again and again).
- **415 of 416 real rows begin "The user said:"** — the model has NEVER written a
  memory in its own voice. There is no self/user provenance at all.
- **Zero lifecycle fields in use**: no `supersedes`, `superseded_by`, `revises`,
  `verified`, `confidence`, `lifecycle`. The MEM-OKF v2 schema DEFINES all of
  them (tools/okf_mem.py implements them). The live path writes none.

Cleaned: **524 → 434** (junk + dupes removed, backup kept).

# The honest answer to the operator's question

> "is the model actually reading and writing memories between user turns?
>  editing/superseding, deduping etc?"

**Reading: yes** (harness recall, token-overlap ranked, per-entry policy since
P1b-2b).
**Writing: yes, but only one shape** — B4 NIGHTSHIFT captures the USER's turn
text, verbatim, prefixed "The user said:", if it passes admission hygiene.
**Editing / superseding / deduping / forgetting: NO. None. Ever.**
The store only grows. Nothing is ever revised, merged, contradicted, aged out,
or promoted. There is no self-memory, no reflection, no consolidation.

That is why it feels dead, and it is why the model slips into thinking it IS the
user: literally every memory it holds is phrased as the user speaking.

# What "living" requires (the build, in order)

1. **Provenance**: every row carries `who` ∈ {user, self} and `kind` ∈
   {fact, preference, event, self-belief, persona-shift}. The capture path must
   ALSO capture what SHANNON said/decided when it matters ("I told Knack I'd
   check back about X", "I decided I dislike being called an assistant").
2. **Dedupe on write**: near-duplicate detection (the same overlap metric recall
   already uses) → merge instead of append.
3. **Supersede on conflict**: "my lucky number is 7741" then "my lucky number is
   12" ⇒ the new row `supersedes` the old; recall must return only the live one.
   (The schema field exists; nothing writes it.)
4. **Consolidation tick** (the *kairos* idea): an idle-time pass that reads the
   day's episodes, merges, promotes durable facts, ages out chatter, and writes
   a SELF summary. This is what makes the system a continuing mind rather than a
   log file.
5. **Gates for all of it**: G-MEMORY-LIFECYCLE (write→dedupe→supersede→recall
   returns the live fact), G-MEMORY-PROVENANCE (self vs user rows, and the model
   never claims a user memory as its own).

# Also found while auditing

- `no_repeat_ngram` is NOT the numeric-garbling cause (see G-VERBATIM).
- The DIGIT bug (G-VERBATIM) poisons memory too: any stored number can be read
  back wrong even when the row itself is perfect. **Fix G-VERBATIM before
  trusting any number-bearing memory.**
