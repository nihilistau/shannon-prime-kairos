---
type: index
title: "GATE-INDEX — every executable gate in harness_tests/, one table, one run command each"
date: 2026-07-14
status: LIVE DOCUMENT — every new gate gets a row here, in the same commit that adds the gate
---

# gates/GATE-INDEX.md

54 executable gates live in `harness_tests/g_*.py`. Before this file, there was no
single list of them, no record of which need a GPU, and no record of which are
currently broken. An agent arriving cold could not answer "what proves this still
works?" or "which gates can I run right now with no daemon up?". This is the answer.

Only ~14 of the 54 have a markdown write-up in `gates/*.md`. That is not a defect
this file fixes — a receipt still belongs in its own `G-*.md` when a gate lands or
a regression is found. This file is the index, not a replacement for the receipts.

**Convention, effective now: every new gate added to `harness_tests/` gets a row
in this table in the same commit.** No exceptions — an unindexed gate is exactly
the "can't tell what proves this still works" problem this file exists to kill.

MODE is determined by reading the file, not by its filename (see "GATES THAT
ASSERTED THE PAST" below for why a filename cannot be trusted):

- **OFFLINE** — safe with no GPU, no daemon. `SP_DAEMON_URL` (if set at all) points
  at a discard/dead port (`127.0.0.1:9`, `:1`, `:59999`) and the file makes no real
  HTTP call to a gateway (`:8800`) or daemon (`:3000`).
- **LIVE** — needs the stack up (`python serve.py agent`, or daemon + gateway per
  the file's own docstring). Makes a real call to `:3000` and/or `:8800`.
- **BROKEN** — does not currently produce a trustworthy result. Do not run without
  reading the note.

Several gate docstrings say `python tests/g_x.py`. The real directory is
`harness_tests/`. That path is stale everywhere it appears; the Run column below
gives the correct one.

## DO NOT RUN THE FULL SUITE BLIND

Two gates below are marked BROKEN because they hang. Running `harness_tests/g_*.py`
in a loop without excluding them will stall for up to 15 minutes per file.

## The table

### Memory — admission, durability, provenance

| Gate | File | What it protects | Mode | Run |
|---|---|---|---|---|
| G-DURABILITY + G-IDENTITY-FIREWALL | `harness_tests/g_durability.py` | Replays the 17 real junk rows from the 2026-07-12 firehose audit (turn ≠ fact, must be split) and the identity-firewall bug (her self-answer overwrote the user's identity). | OFFLINE | `python harness_tests/g_durability.py` |
| G-ADMISSION | `harness_tests/g_admission.py` | Feeds the exact class of sentence that filled the registry 404 times (grammatical, declarative, about nobody) and asserts it is refused; a real personal fact still lands, v2 schema. | LIVE | `python harness_tests/g_admission.py` (warm stack, gateway :8800) |
| G-MEMORY-LIFECYCLE / G-MEMORY-PROVENANCE | `harness_tests/g_memory_lifecycle.py` | WRITE / SUPERSEDE / PROVENANCE — a fact can be stored deliberately, a changed fact tombstones the old one forward, self-facts and user-facts never merge. | OFFLINE | `python harness_tests/g_memory_lifecycle.py` |
| G-CLAIM | `harness_tests/g_claim.py` | Three bugs on the REAL code path (`spine.recall_decider`): the attribute-slot collision that let "cat person" overwrite "terrified of open water", the bypassed tombstone filter in automatic recall, and testimony-outranks-inference at the recall seam. | OFFLINE | `python harness_tests/g_claim.py` |
| G-SECRET | `harness_tests/g_secret.py` | The privacy decline is REACHABLE, end to end: `lifecycle.classify()` (`lifecycle.py:245-265`) can now emit `private-secret` — checked FIRST, before relationship/identity/event (`_SECRET`/`_SECRET_POSS` at `lifecycle.py:220-233`) — and `spine.recall_decider()`'s zero-inference decline actually fires off a row `remember()` produced, with the secret text never appearing in the payload. 22/22. | OFFLINE | `python harness_tests/g_secret.py` |
| G-CLOCK | `harness_tests/g_clock.py` | Every timestamp survives its own round trip (`gmtime`/`calendar.timegm`, never `mktime`) — the same UTC-offset bug fixed twice, 8 hours apart, in `watch.py` and `lifecycle.py`. | OFFLINE | `python harness_tests/g_clock.py` |

### Memory — salience, reflection, silence, recall shape

| Gate | File | What it protects | Mode | Run |
|---|---|---|---|---|
| G-SALIENCE | `harness_tests/g_salience.py` | A repeated fact reinforces (`mentions` increments) instead of being silently discarded as "already in memory"; salience must never overrule matching or resurrect pure chatter. | OFFLINE | `python harness_tests/g_salience.py` |
| G-REFLECT | `harness_tests/g_reflect.py` | Idle-clock self-reflection stays silent unless a conclusion is genuinely surprising (bits-of-surprise, not "did she think of something"). | OFFLINE | `python harness_tests/g_reflect.py` |
| G-SILENCE | `harness_tests/g_silence.py` | `silences()` measures days-he-actually-talked-to-her, not calendar days — so a 3-week absence does not read as every topic going silent at once. | OFFLINE | `python harness_tests/g_silence.py` |
| G-RECALL-PRECISION | `harness_tests/g_recall_precision.py` | A memory is injected as CONTEXT, never as a command she must recite verbatim (root cause was `recall.rs:176` defaulting every mem_class to `counterfact` framing). | LIVE | `python harness_tests/g_recall_precision.py` (gateway :8800) |
| G-SELF-REPEAT | `harness_tests/g_self_repeat.py` | She does not parrot her own previous reply verbatim, AND she can still quote a number back exactly (the two halves fight each other — `no_repeat_ngram` fixes one and re-breaks the other). | LIVE | `python harness_tests/g_self_repeat.py` (warm stack, gateway :8800) |

### Memory — notes and watches

| Gate | File | What it protects | Mode | Run |
|---|---|---|---|---|
| G-NOTES | `harness_tests/g_notes.py` | The note store, its lifecycle, and THE PROMISE: a reminder fires, fires once, survives her having nothing else to say, and is never muted by the anti-chatter rules. | OFFLINE | `python harness_tests/g_notes.py` |
| G-WATCH | `harness_tests/g_watch.py` | A "I'll look out for X" promise is backed by a real, auditable check — it actually searches, shows what it saw, and can say no (the expected answer, nearly every time). | OFFLINE | `python harness_tests/g_watch.py` |

### MEM-OKF v2 / PK2 spine (ADR-005 through ADR-008)

| Gate | File | What it protects | Mode | Run |
|---|---|---|---|---|
| G-PK2-SPINE (offline) | `harness_tests/g_pk2_spine_offline.py` | ADR-007 spine fold (decide → execute → verify), the stock deciders, and the VERIFY_FAIL honesty path. | OFFLINE | `python harness_tests/g_pk2_spine_offline.py` |
| G-PK2-SPINE-2 (offline) | `harness_tests/g_pk2_spine2_offline.py` | **BROKEN — do not run.** Named `_offline` but HANGS, observed stuck at 10/12. It calls `harness/server/app.py:_native_chat_sse`, which unconditionally waits on the module-level `threading.Event` `_WARM` (`app.py:737-743`, `while not _WARM.wait(4.0)`, up to 900s). `_WARM` is only ever set by `_prewarm()` (`app.py:1101`), which only runs from the HTTP server startup path behind `SP_GATEWAY_PREWARM=1` (`app.py:1430-1431`). A standalone script never sets it. Its two failing checks: (a) "memory tier stays <=6 hot tools" fails on arithmetic — `spine.py:287` builds `MEMORY_TOOLS` (5, `memory.py:790`) + `MEMORY_TOOLS_EXTRA[:2]` (2, `memory.py:792`) = 7 hot tools, asserted `<=6` at `g_pk2_spine2_offline.py:53`; (b) the recall-note check is the one that blocks on `_WARM`. | BROKEN | DO NOT RUN — hangs up to 15 min |
| G-PK2-SSE-V2 (offline) | `harness_tests/g_pk2_sse_v2_offline.py` | **BROKEN (latent) — do not run.** Same bug as spine-2: monkeypatches `agent_chat_stream` then calls `app._native_chat_sse` (`g_pk2_sse_v2_offline.py:49`), which still hits the `_WARM` gate at `app.py:737` before the monkeypatch is ever reached. Never observed to complete cleanly for the same reason spine-2 doesn't. | BROKEN | DO NOT RUN — same latent hang as spine-2 |
| G-PK2-FLYWHEEL (offline) | `harness_tests/g_pk2_flywheel_offline.py` | ADR-005 flywheel ∘ ADR-008 ring: spine receipts persist into the durable telemetry-okf tier, content-addressed and idempotent, via the existing TelemetrySink. | OFFLINE | `python harness_tests/g_pk2_flywheel_offline.py` |
| G-PK2-MEMOKF-V2 (offline) | `harness_tests/g_pk2_memokf_v2_offline.py` | MEM-OKF v2 provenance (§M1), near-dup reinforcement not duplication (§M2), registry hygiene/compaction (§M3). Was itself an instance of the doctrine-drift pattern — see "GATES THAT ASSERTED THE PAST" below; now fixed. | OFFLINE | `python harness_tests/g_pk2_memokf_v2_offline.py` |
| G-PK2-UI-ENDPOINTS (offline) | `harness_tests/g_pk2_ui_endpoints_offline.py` | The operator-panel gateway surfaces (§U: memory/tasks/persona JSON) and the persona editor round-trip, called directly, no server. | OFFLINE | `python harness_tests/g_pk2_ui_endpoints_offline.py` |
| G-PK2-TOOLROBUST (offline) | `harness_tests/g_pk2_toolrobust_offline.py` | §T2-E3 robustness guards, §T2-E2 coding tools, §T2-E1 task-loop machinery — driven by a `FakeClient` scripting the model's turns, no daemon. | OFFLINE | `python harness_tests/g_pk2_toolrobust_offline.py` |
| G-MEMPOLICY-V3 (offline, rehomed) | `harness_tests/g_mempolicy_v3_offline.py` | Per-entry MEM-OKF policy dispatch: counterfact override framing, secret-present recital, secret-absent zero-inference decline, untagged null floor. **See "GATES THAT ASSERTED THE PAST" — still tests the dispatch, not the producer, but G-SECRET (2026-07-14) now covers the producer end to end, so the decline this certifies is reachable in production.** Also note: this file calls `app._native_chat_sse` (`g_mempolicy_v3_offline.py:91`), the same function spine-2/sse-v2 hang on — its GREEN receipts (`gates/G-MEMPOLICY-V3-rehomed.md`) predate that discovery; not re-verified against the `_WARM` gate here. | OFFLINE | `python harness_tests/g_mempolicy_v3_offline.py` — verify it still completes before trusting it |
| G-PK2-RECALL-LIVE | `harness_tests/g_pk2_recall_live.py` | ADR-008 pre-turn spine recall, LIVE on the 12B through the agent gateway: matched query recalls faithfully, foreign query gets a clean parametric answer (no hijack). | LIVE | `python harness_tests/g_pk2_recall_live.py` (daemon :3000 + gateway :8800, arms `SP_SPINE_RECALL=1`) |
| G-PK2-RECALL-L5-COMPOSE | `harness_tests/g_pk2_recall_l5_compose.py` | Enforces the one-authority rule when both harness recall and the daemon's L5 recall could fire at once (gateway auto-disarms harness recall when `auto_recall=true`). | LIVE | `python harness_tests/g_pk2_recall_l5_compose.py` (`run_console_faithful.bat` + `_pk2_recall_gateway.bat`) |
| G-PK2-TASKLOOP-E2E | `harness_tests/g_pk2_taskloop_e2e.py` | The live agentic coding loop (§T2-E1) on the served 12B: seeded bug + failing test, asserts `run_task` drives `edit_file`/`run_tests` to a real green. | LIVE | `python harness_tests/g_pk2_taskloop_e2e.py` (daemon :3000) |

### KAIROS — autonomous speech policy

| Gate | File | What it protects | Mode | Run |
|---|---|---|---|---|
| G-KAIROS-POLICY | `harness_tests/g_kairos_policy.py` | Silence is the default, speech is earned: ordinary-finish → silent, cut-off → continue, she never answers her own question, chain limit, cooldown, hourly cap, his turn resets her budget. Pure, injected clock and rng. | OFFLINE | `python harness_tests/g_kairos_policy.py` |
| G-TUNING | `harness_tests/g_tuning.py` | A settings knob that does not change behaviour is decoration: bounds/provenance declared, unknown keys refused, values clamped, overrides persist, and moving `kairos.max_chain`/`continue_margin` actually changes the next decision. | OFFLINE | `python harness_tests/g_tuning.py` |
| G-KAIROS-TICK | `harness_tests/g_kairos_tick.py` | The CHECK_IN branch (quiet-room detection) is reachable and fires almost never — proven by driving the scheduler's own clock with an injected `now`, not by waiting 4 real minutes. | OFFLINE | `python harness_tests/g_kairos_tick.py` |
| G-KAIROS-LIVE | `harness_tests/g_kairos_live.py` | The full chain end to end on the real stack: `eot_margin` → SSE `kairos` event → scheduler → continuation → `worth_saying()` → outbox — and that an ordinary turn produces nothing. | LIVE | `python harness_tests/g_kairos_live.py` (warm stack, `SP_KAIROS=1`, gateway :8800) |
| G-KAIROS-CONSOLE | `harness_tests/g_kairos_console.py` | The console actually polls the outbox, and the session key used to file her message (`session_id`, per `console.html`) matches the key `_native_chat_sse` uses — not one of the other three places a session key gets derived. | LIVE | `python harness_tests/g_kairos_console.py` (gateway :8800) |

### Engine / KV / serving performance

| Gate | File | What it protects | Mode | Run |
|---|---|---|---|---|
| G-VRAM | `harness_tests/g_vram.py` | The daemon does not silently spill to host RAM over PCIe (WDDM never errors on this — it just crawls). Asserts the spilled-memory number does not MOVE as context grows, not that it is zero. | LIVE | `python harness_tests/g_vram.py` (daemon :3000) |
| G-PREFIX | `harness_tests/g_prefix.py` | A new chat over the shared preamble reuses the cached prefix instead of re-prefilling all of it from scratch (the 164-second "hello" bug). | LIVE | `python harness_tests/g_prefix.py` (gateway :8800) |
| G-PREFILL-CACHE | `harness_tests/g_prefill_cache.py` | Deliberate lint: `agent_chat_stream(..., tools=[])` must never be used where `tools=None` is meant — `[]` rebuilds the system prompt and diverges the persist-KV cache at token 0, costing a full re-prefill on every subsequent ordinary turn. | OFFLINE | `python harness_tests/g_prefill_cache.py` |
| G-ONESHOT | `harness_tests/g_oneshot.py` | A one-off aux call (watch judge, reflection, summariser) does not evict the user's live conversation from the one resident KV slot, and is not itself charged a full 78-second prefill for a yes/no token. | LIVE | `python harness_tests/g_oneshot.py` (daemon :3000 + gateway :8800) |
| G-PERF-DECODE | `harness_tests/g_perf_decode.py` | A repeatable decode-rate number: pins both generated-token count and context length (an unpinned tok/s figure is meaningless and produced two wrong perf conclusions in one session). | LIVE | `python harness_tests/g_perf_decode.py` (daemon-direct :3000) |
| G-FLOAT-PARITY | `harness_tests/g_float_parity.py` | Per-build certification for float serving (P5a). Documented as necessary-but-not-sufficient: passed 4/4 on a build whose float path still corrupted attended detail in live serving. | LIVE | `python harness_tests/g_float_parity.py` (stack up) |
| G-VERBATIM | `harness_tests/g_verbatim.py` | The served stack can copy a digit string exactly. Root cause (SOLVED, see `gates/G-VERBATIM-digits-broken.md`): `no_repeat_ngram=3` banned re-emitting any trigram already in context, which is exactly what quoting a number does. This is the gate that runs after ANY engine/model/profile/sampler change. | LIVE | `python harness_tests/g_verbatim.py` (daemon :3000) |
| *(no G-ID — see note)* | `harness_tests/g_tool_mask.py` | Rule 1: a turn with no tool call comes back byte-identical with the tool mask ON vs OFF (mask must not change how she talks). Rule 2: a tool she does not have is unsamplable, not merely unlikely. **This gate has no canonical `G-*` identifier — it prints only `A/B: PASS` / `A/B: FAIL` / `A/B: INCONCLUSIVE` (`g_tool_mask.py:141,144,150`). It cannot currently be looked up by name; anyone indexing gates by grepping for `G-` will miss it.** | LIVE | `python harness_tests/g_tool_mask.py` (daemon :3000) |

### Tool calling & agency (harness e2e)

| Gate | File | What it protects | Mode | Run |
|---|---|---|---|---|
| G-HARNESS-DAEMON-E2E | `harness_tests/g_daemon_e2e.py` | First real token off the live daemon through the harness's own inference seam (`SPDaemonClient` + `InferenceConfig.to_sp_chat`). | LIVE | `python harness_tests/g_daemon_e2e.py` (daemon :3000) |
| G-HARNESS-TOOLCALL-E2E | `harness_tests/g_tool_calling_e2e.py` | Live ephemeral `<tool name=...>{json}</tool>` calling on the served 12B: an arithmetic evaluator and a sandboxed Python exec, loop until the model answers. | LIVE | `python harness_tests/g_tool_calling_e2e.py` (daemon :3000) |
| G-HARNESS-GEMMA-TOOLS-E2E | `harness_tests/g_gemma_tools_e2e.py` | Gemma-native ` ```tool_code``` ` calling plus the newer tools (filesystem, shell, web, count_memories) on the live served 12B. | LIVE | `python harness_tests/g_gemma_tools_e2e.py` (daemon :3000) |
| G-HARNESS-MEMTOOLS-E2E | `harness_tests/g_memory_tools_e2e.py` | `list_memories`/`remember`/`forget` as ephemeral tools over the daemon's persistent registry — a direct-curation phase, then a model-driven call proving the served 12B actually invokes one. | LIVE | `python harness_tests/g_memory_tools_e2e.py` (daemon :3000) |
| G-HARNESS-AGENT-MEMORY-E2E | `harness_tests/g_agent_memory_e2e.py` | The model manages its own memory by emitting tool calls inside a real chat (`agent_chat`/`run_with_tools`) instead of the daemon's heuristic auto-forget. | LIVE | `python harness_tests/g_agent_memory_e2e.py` (daemon :3000) |
| G-HARNESS-AGENCY-E2E | `harness_tests/g_agency_loop_e2e.py` | Seeded with a redundant fact pair, the served 12B decides FOR ITSELF to forget the redundant one — tool calling composed with memory tools into self-curation. | LIVE | `python harness_tests/g_agency_loop_e2e.py` (daemon :3000) |
| G-HARNESS-KAIROS-TICK-E2E | `harness_tests/g_kairos_tick_e2e.py` | The agency round fires on a heartbeat tick, with no user turn, and self-curates a seeded-redundant registry — the KAIROS auto-round realized end to end. | LIVE | `python harness_tests/g_kairos_tick_e2e.py` (daemon :3000) |
| G-HARNESS-GATEWAY-E2E | `harness_tests/g_gateway_e2e.py` | The console's `/v1/chat` through the agent gateway: POST messages, SSE deltas back, tools called silently in between. | LIVE | `python harness_tests/g_gateway_e2e.py` (gateway :8800, daemon up) |
| G-HARNESS-HOOK-E2E | `harness_tests/g_hook_e2e.py` | The full live loop: the daemon writes `_current_conversation.json` every turn, and the scheduler's consolidation reads that SAME file and tiers it. Reads a file the live daemon process must have produced — no direct HTTP call, but a live-daemon precondition all the same. | LIVE | `python harness_tests/g_hook_e2e.py` (daemon running and has written `_current_conversation.json`) |
| G-HARNESS-CONSOLIDATE | `harness_tests/g_consolidate_live.py` | The scheduler's consolidation step tiers a fixed local conversation (facts → mid, transcript → long) through the real `remember()`/MEM-OKF mechanism. **Misleadingly named `_live`: `SP_DAEMON_URL` is set to the dead port `:59999` (`g_consolidate_live.py:11`) and nothing in the file makes a real call to `:3000` despite the inline comment claiming "model calls use :3000" — `consolidate_current` is local regex/text extraction, no model round-trip.** | OFFLINE | `python harness_tests/g_consolidate_live.py` |
| G-HARNESS-CONVMEM-E2E | `harness_tests/g_conversation_memory_e2e.py` | Tiered conversation memory + capabilities corpus on MEM-OKF: consolidate a conversation, recall the gist, dig into the full transcript, verify MEM-OKF integrity. | LIVE | `python harness_tests/g_conversation_memory_e2e.py` (daemon :3000) |
| G-ALIVE | `harness_tests/g_alive.py` | Whether memory machinery built elsewhere is actually REACHABLE by the model in a live turn: keep a user fact, keep a self fact, tell them apart, supersede a changed fact, change her own trait — all through the live gateway. | LIVE | `python harness_tests/g_alive.py` (gateway :8800) |
| G-CAPTURE-LIVE | `harness_tests/g_capture_live.py` | Replays the verbatim transcript that produced the 17-junk-row firehose, through the LIVE gateway (the entry point the console actually uses), and reads the registry after — the end-to-end arbiter for the offline `g_durability` rules. | LIVE | `python harness_tests/g_capture_live.py` (gateway :8800) |

### Conversation & voice

| Gate | File | What it protects | Mode | Run |
|---|---|---|---|---|
| G-CONVERSATION | `harness_tests/g_conversation_e2e.py` | A real 10+ turn conversation that grows past the SWA ring (2048 tokens) with long replies requested — reply completeness (length floor, terminal punctuation, no degeneration), recall surviving the ring, per-turn timing. This is the shape that caught the shear regression; short fresh chats do not. | LIVE | `python harness_tests/g_conversation_e2e.py` (gateway :8800) |
| G-VOICE | `harness_tests/g_voice.py` | She still sounds like herself and still picks the right tool once the toolset passes ~6 tools (the point where a 12B "explores and stalls" per `agent.py`'s own comment). | LIVE | `python harness_tests/g_voice.py` (gateway :8800) |
| g-voice0-parity | `harness_tests/g_voice0_parity.py` | The live ear path (POT i16 IR + softmax·W_sub) reproduces the gated KAI-3 FP32-torch export on the same 8 eval events — CTC frame count within ±2, mean cosine ≥0.97. | OFFLINE | `python harness_tests/g_voice0_parity.py` |

### Roleplay & grammar

| Gate | File | What it protects | Mode | Run |
|---|---|---|---|---|
| G-ROLEPLAY | `harness_tests/g_roleplay.py` | Structure enforced in code, not prompt vibes: explicit-ask entry only, the heat ladder cannot skip rungs, the operator's ceiling is absolute, de-escalation is always free, a hard stop wins instantly, exit is clean. | OFFLINE | `python harness_tests/g_roleplay.py` |
| G-GRAMMAR | `harness_tests/g_grammar.py` | The tool-call grammar against every parsing failure this codebase has actually produced (split names, fence-language drift, malformed recovery, multi-call fences, exhausted loops) — free text can be wrong, so the grammar makes the wrong shapes not exist. | OFFLINE | `python harness_tests/g_grammar.py` |

## GATES THAT ASSERTED THE PAST

A gate can stay green for weeks while testing something that no longer matters, or
while supplying its own precondition so thoroughly that it only proves the guard
compiles — never that the thing it guards actually fires. Four confirmed instances:

1. **g_pk2_memokf_v2_offline.py** asserted "near-dup paraphrase REJECTED"
   (`g_pk2_memokf_v2_offline.py:44-45`, in the preserved comment) and had been
   failing since commit `e967fd0` without anyone looking, because task #11
   deliberately changed the answer: a repeat REINFORCES, it does not get
   rejected as a duplicate. Now fixed — the same file asserts
   `"reinforced" in r.lower()` and `mentions >= 2` instead
   (`g_pk2_memokf_v2_offline.py:56-63`).

2. **G-SALIENCE and G-REFLECT** both built a man who had "gone quiet" with no
   record he was ever present. They passed for weeks testing calendar silence —
   the exact bug G-SILENCE exists to kill (`silences()` measuring calendar days
   instead of days-he-actually-talked-to-her).

3. **g_mempolicy_v3_offline.py:34,37** hand-constructs registry rows with
   `mem_class: "counterfact"` and `mem_class: "private-secret"` and asserts the
   spine dispatch honours them. It tests the DISPATCH, never the PRODUCER.
   At the time this was written, `lifecycle.classify()` could only return
   `relationship`, `identity`, `event`, `preference`, or `fact` — it could
   never emit `counterfact` or `private-secret`, so the privacy decline this
   gate certifies had never fired on a real write. Green for weeks
   (`gates/G-MEMPOLICY-V3-rehomed.md`: "PASS 10/10"). At the time, this was
   the most expensive instance of the pattern found so far — a security
   control the test suite vouched for and production could not reach.
   **UPDATE (2026-07-14): the hole is closed.** `lifecycle.classify()`
   (`lifecycle.py:245-265`) now checks for a credential FIRST, before
   `_CLASS_RULES` (`lifecycle.py:235-242`) ever runs, via `_SECRET` /
   `_SECRET_POSS` (`lifecycle.py:220-233`) — so "my wife's password is
   hunter2" classifies as `private-secret`, not `relationship`, and can emit
   the class this file's dispatch test always assumed existed. This gate
   itself is unchanged and still only exercises the dispatch on hand-built
   rows — it does not, on its own, prove the producer works. `harness_tests/g_secret.py`
   (G-SECRET, 22/22, OFFLINE) is the new gate that does: it never sets
   `mem_class`, drives real sentences through `remember()` and
   `spine.recall_decider()`, and asserts the decline actually fires and the
   secret text never appears in the payload. G-SECRET closes the hole this
   entry describes; g_mempolicy_v3_offline.py's dispatch-only scope is still
   accurately described above.

**The lesson: a gate that supplies its own precondition proves only that the
guard compiles.** Assert against the same producer the live path actually calls
(`lifecycle.classify()`, `spine.recall_decider()`, the real registry writer) —
never against a row you hand-built to look like its output.

## DOC DRIFT

`gates/G-KAIROS-P1c-2-shear.md` is stamped `status: GREEN` (2026-07-11, the prefix
shear: O(1) cold new-chat restore, 123s → 5s). `gates/REGRESSION-2026-07-11-shear.md`,
same day, later, documents the same mechanism corrupting live conversations (every
reply truncated to 1-26 characters past `ring_W=2048`) and being disarmed
(`profiles/agent.toml: prefix_snapshot = false`). **The GREEN receipt was never
retracted or marked superseded.** An agent reading `G-KAIROS-P1c-2-shear.md` alone,
without also finding the regression doc, would believe the shear is live and safe.

The repo already has a convention for exactly this — `gates/G-VERBATIM-digits-broken.md`
carries a `supersedes:` frontmatter key naming the receipt it invalidates
(`supersedes: "the RED receipt of 2026-07-12 (six 'eliminations', one of which was
false and cost the whole hunt)"`). It just was not applied to the shear receipt.
**Recommended fix:** add `superseded-by: "gates/REGRESSION-2026-07-11-shear.md
(2026-07-11, same day) — the shear corrupted live conversations past ring_W and was
disarmed"` to `G-KAIROS-P1c-2-shear.md`'s frontmatter, and add
`status: GREEN, but see superseded-by` so a reader does not have to find the
regression doc by luck.
