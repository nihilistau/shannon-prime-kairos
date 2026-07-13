# AGENTS.md — shannon-prime-kairos

**This is the canonical orientation file for anyone — human or agent — working in this repo.**
`CLAUDE.md` points here. It is not a copy. There is exactly one of these, on purpose (see THE BUG CLASS).

Kairos is the production rebuild of Shannon-Prime: a local AI companion. Gemma-4-12B on one RTX 2060
(12 GB), a Rust + CUDA engine, a Python harness/gateway, a served console. It runs on the operator's
own machine and remembers him. That last part is the whole product, and it is where all the danger is.

---

## 0. THE BUG CLASS — read this before you touch anything

This project has one recurring, near-fatal failure mode. It has bitten at least six times. Every time,
it looked like a different bug. It is not:

> **AN INVARIANT ENFORCED IN ONE OF TWO PATHS IS ENFORCED IN NEITHER —
> because the unguarded path is the one that runs.**

Real instances, all found in the tree, all fixed:

| The rule | Where it was enforced | Where it was NOT | What actually happened |
|---|---|---|---|
| a tombstoned fact is never recalled | `memory.recall()` | `spine.recall_decider()` — the AUTOMATIC per-turn injection | superseded facts injected into her context on **every turn, for weeks**, ranked above the truth |
| the recall seam filters retired rows | `search_memories_ranked_rows()` | `search_memories_ranked()` — **the next function in the file** | the `search_memories` tool, live in two toolsets, still served tombstones |
| a turn arms the presence ledger | one of two turn paths | the other | absence became unmeasurable |
| nothing is ever destroyed | the whole lifecycle architecture | `forget()`, which did `open(p, "w")` and dropped the row | the audit lane was defeated by one live tool call |
| the privacy decline protects secrets | `spine.recall_decider()` checks `mem_class == "private-secret"` | `lifecycle.classify()` **cannot emit that class** | **the guard has never fired and cannot** — see TRAPS |

The corollaries, learned the hard way:

- **Fix the class, not the instance.** After fixing one of these, *grep for the other one*. The twin is
  usually adjacent. Twice it was literally the next function.
- **Put the rule in the seam, not the caller.** A rule you must remember to apply is a rule you will
  forget. If two callers need it, it belongs in the thing they both call.
- **A gate that supplies its own precondition proves only that the guard compiles.** See
  `gates/GATE-INDEX.md` → "GATES THAT ASSERTED THE PAST".
- **Measure the thing, not the proxy.** Several days were lost to `nvidia-smi` (lies under WDDM),
  `cudaMemGetInfo` (returns free=0 under WDDM), and a kill-regex that matched the probe's own process.

---

## 1. NON-NEGOTIABLES

1. **No claim without a repeatable gate.** If you say it is fixed, name the command that proves it.
   "It should work now" is not a receipt.
2. **Nothing in memory is ever deleted.** Tombstone (`lifecycle = 1`) or quarantine. Never `open(p, "w")`
   minus a row. The audit lane must always be able to answer *what did she believe, when, and who told her*.
3. **Honesty about what is measured vs asserted.** If you did not run it, say so. If a number came from a
   proxy, name the proxy. A verdict you cannot defend is worse than no verdict — it is a lie with a
   timestamp on it.
4. **Her word never outranks his.** An inference may never retire an observation. She is allowed to be
   wrong about him; she is not allowed to say it over him.

---

## 2. THE STACK, AND THE ONE DOOR

```
console (browser)  ──HTTP──▶  harness gateway :8800  ──HTTP──▶  sp-daemon :3000  ──▶  CUDA / gemma4-12B
                                (Python)                          (Rust)
```

- **`serve.py` is THE ONLY DOOR into the engine**, and as of 2026-07-14 that is *literally* true rather
  than aspirational. It reads a profile (`profiles/*.toml`) and maps it to the engine/gateway environment
  with an explicit table. **Anything not in that table does not exist**: the base environment is stripped of
  every `SP_*`, so a stray var in your shell cannot reach the engine. It used to inherit the lot —
  270 `SP_*` are read by the tree, 49 were mapped, **221 came from whatever shell you were standing in**,
  and 28 of those touch memory (`SP_DECIDE` is an autonomous supersede pass; `SP_FORGET` is autonomous
  forgetting). Those are now pinned hard-off by name. Gate: **G-ONEDOOR**.
  Start the stack with `python serve.py agent`.
- **Deliberate overrides still work; accidental ones do not.** `set SP_PASSTHROUGH=SP_XBAR_ROW,SP_ARM_DUMP`
  keeps exactly those, and announces them at boot. It cannot be used to smuggle in a memory writer.
- **`profiles/agent.toml` is the live production profile.** Read it before you theorise about behaviour;
  it is the ground truth for what is armed. `serve.py` refuses to boot a profile that arms two memory
  writers (**G-ONEWRITER**), so the profile cannot lie to you either.

| Where | What lives there |
|---|---|
| `engine/` | the Rust daemon (`tools/sp_daemon`) and the CUDA kernels (`src/backends/cuda/cuda_forward.cu`). The KV cache, the ring, prefill, fp16 KV, `/v1/capture`, `/v1/oneshot`. |
| `core/` | the math core (`shannon-prime-system`), carried ALSO as a submodule at `engine/lib/shannon-prime-system`. Its `CLAUDE.md` is about the math core, not about kairos. |
| `harness/` | the Python brain. `skills/` (memory, notes, lifecycle), `model/` (person, presence, ear), `control/` (spine, agency), `kairos/` (the scheduler — unprompted speech), `server/app.py` (the gateway). |
| `harness_tests/` | the gates. ~54 of them. `gates/GATE-INDEX.md` indexes them. |
| `gates/` | gate write-ups and receipts (markdown). |
| `profiles/` | the TOML profiles `serve.py` reads. |
| `memory-okf*/` | the MEM-OKF knowledge stores (content-addressed, tiered: `LUT.md` → `sum/` → `full/`). Tool: `tools/okf_mem.py`. |
| `var/` | ALL runtime state. Gitignored. The fact registry, notes, the presence ledger, logs. |
| `docs/` | ADRs and deep-dives. |

---

## 3. MEMORY AND RECALL — the part you are most likely to break

**Full reference: [`docs/MEMORY-AND-RECALL.md`](docs/MEMORY-AND-RECALL.md). Read it before changing anything under `harness/skills/`.**

The essentials, so you do not have to guess:

- **The fact registry** is `var/memory/registry.jsonl` (path from `SP_RECALL_REGISTRY`). One JSON row per fact.
- **Two axes that are constantly confused. They are not the same thing:**
  - `speaker` — **who the fact is ABOUT** (`user` | `self`). Set from the *author of the turn*, never
    inferred from the sentence. ("My name is Knack" said by him is a fact about HIM.)
  - `status` — **where the claim CAME FROM** (`observed` | `inferred` | `confirmed` | `disputed`).
    He said it, versus she concluded it.
- **`lifecycle`** — `0` live, `1` retired. The tombstone flag, and **the one field both the Rust engine and
  the Python harness key on**. Nothing is deleted; things are retired.
- **`src` is free-text provenance PROSE.** Maintenance scripts append to it. **It is not an enum and you may
  not branch on it.** Branching on it was a real bug: a cleanup pass appended `" | cleanup: ..."` and silently
  turned reflections back into evidence.
- **One read seam.** Every door a fact can reach her mouth through funnels into
  `memory.search_memories_ranked_rows()`, which filters tombstones and applies `lifecycle.testimony_wins()`.
  If you add a reader, **use the seam**. Do not re-implement the filter.
- **Framing happens at READ time** (`lifecycle.render()`): "Knack told me: …" / "I've come to think: …" /
  "About myself: …". This is what stops a fact he said in the first person coming back in her voice.
- **Three write paths exist.** Only one is authoritative (`memory.remember()`). The other two are the
  daemon's — see TRAPS.

---

## 4. TRAPS — live, verified, not yet fixed

These are real. They are not hypotheticals. Do not be the next person to rediscover them.

1. ~~**THE PRIVACY DECLINE CANNOT FIRE.**~~ **FIXED 2026-07-14 — G-SECRET 22/22.**
   For the record, because the shape of it is the whole lesson: `spine.recall_decider()` protected
   secrets by checking `mem_class == "private-secret"`, and `lifecycle.classify()` — the only classifier
   the authoritative writer runs — could emit exactly `relationship | identity | event | preference |
   fact`. **The consumer branched on a value the producer could not produce.** The decline had never
   fired once. `private-secret` was only ever minted by the *daemon's* classifier, armed by `growth=true`;
   the 2026-07-12 "one memory authority" fix set `growth=false` and took the only producer with it, so
   **the privacy guarantee was collateral damage of a correctness fix.** `g_mempolicy_v3` stayed green
   throughout because it hand-builds the `private-secret` row and tests the *dispatch*, never the *producer*.
   The audit found one real credential already sitting in his live store as a plain `fact`
   (`'My access code is 4471'`) — reclassified in place, provenance appended to `src`, nothing destroyed.
   `harness_tests/g_secret.py` §4 now asserts the generalisation, and that is the part worth keeping:
   **every class the decider branches on must be one the writer can produce.** Add an `if mc == "..."`
   branch with no producer and the gate fails the day you write it, not eight weeks later when it leaks.

2. ~~**`store_verb = true` on the live profile.**~~ ~~**`growth = true` in 8 non-live profiles.**~~
   **BOTH FIXED 2026-07-14 — G-ONEWRITER 35/35.** Kept here because the shape is instructive:
   the daemon had **two** write flags, and the 2026-07-12 "one memory authority" fix turned off one.
   The comment announcing that fix literally said *"the daemon no longer writes memories. Recall, **the
   store verb**, and classification are untouched"* — it **named** the second write path while declaring
   the daemon no longer wrote. So `"note that I'll be late"` was still a registry write, performed by the
   daemon, with `speaker` hardcoded, no `status`, and none of admission / firewall / dedupe / supersede /
   secret-classification — **and zero model inference, so she never saw the turn.**
   The remedy for *an invariant enforced in one of two paths* was enforced in one of two paths.
   Both flags are now false on all 13 profiles, and **`serve.py` refuses to boot** any profile that arms
   either while `agent.authority = 'spine'`. A rule in a comment gets applied to the file the comment is
   in; this one lives in the door.

4. **`_AUTHOR` / `_QUESTION` are process-wide module globals** in `harness/skills/memory.py`, under a
   `ThreadingHTTPServer`. Concurrent turns can cross-contaminate speaker attribution. Known risk.

5. **`status: disputed` is vocabulary-only.** Nothing writes it. The write-time contradiction detector was
   deliberately deleted (it was a semantic judgment made out of substring matching). The rule it was trying
   to enforce lives at the read seam now, in `testimony_wins()`.

6. **Two gates are named `_offline` and are not.** `g_pk2_spine2_offline` and `g_pk2_sse_v2_offline` call
   `app._native_chat_sse`, which blocks on a `threading.Event` (`_WARM`) that only the HTTP-server startup
   path ever sets. They hang for up to 900s. See `gates/GATE-INDEX.md`.

---

## 5. THE GATES

**Doctrine: no claim without a repeatable gate.** The index is [`gates/GATE-INDEX.md`](gates/GATE-INDEX.md) —
every gate, what it protects, and crucially **whether it needs a GPU**.

- **OFFLINE gates** point `SP_DAEMON_URL` at a discard port and need no GPU and no daemon. Run these freely.
  They cover most of the memory system: `g_claim`, `g_salience`, `g_durability`, `g_memory_lifecycle`,
  `g_silence`, `g_clock`, `g_reflect`, `g_notes`, `g_watch`, `g_grammar`, `g_tuning`, `g_roleplay`.
- **LIVE gates** need `python serve.py agent` running.

Run one: `python harness_tests/g_claim.py`

**If you touch memory or recall, the minimum bar is:**

```
python harness_tests/g_claim.py            # the seam, the slot, testimony over inference
python harness_tests/g_durability.py       # a turn is not a fact; the identity firewall
python harness_tests/g_memory_lifecycle.py # write / supersede / provenance
python harness_tests/g_salience.py         # a repeat is a second data point
python harness_tests/g_silence.py          # absence is only information if you were looking
python harness_tests/g_clock.py            # every timestamp survives its own round trip
```

**Writing a gate? Two rules, both bought with real regressions:**

1. **Assert through the REAL path**, not a hand-called helper. G-CLAIM asserts through
   `spine.recall_decider()` — the function that actually runs — precisely because the bug it protects
   against lived in the path nobody was testing.
2. **Do not supply your own precondition.** If your gate hand-builds the row that makes the guard fire, you
   have tested the guard, not the system. That mistake is currently costing us a privacy guarantee.

---

## 6. KEEPING THIS FILE TRUE

This file rots faster than the code. When you land a change that alters any of the following, **update this
file in the same commit**:

- a new read path or write path into memory → §3 and `docs/MEMORY-AND-RECALL.md`
- a new gate → a row in `gates/GATE-INDEX.md`
- a trap fixed → strike it from §4 (and say so in the commit)
- a new trap found → add it to §4, even if you are not fixing it now. **An unwritten trap is a trap that gets
  rediscovered at 3am.**

The commit messages in this repo are unusually long on purpose: they carry the *reasoning*, not just the
change. `git log` is a primary source. Read it before you assume something is arbitrary.
