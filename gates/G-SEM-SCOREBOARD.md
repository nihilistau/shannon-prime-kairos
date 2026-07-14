# G-SEM-SCOREBOARD — S1 semantic rank, measured. Result: DOES NOT SHIP (yet). 2026-07-14

**The claim under test:** semantic admission at the recall seam beats the lexical baseline
on the frozen corpus (decider paraphrase hit rate > 0.06) at foreign-decider precision ≥ 0.98.

**Verdict: no embedding space reachable today ships. `[sem].rank` stays `false`.
Four measurements, one diagnosis, one direction. Nothing here is asserted; every number
has a receipt (`var/sem/receipts/sem_rank_score.json` history + the logs under `var/sem/`).**

## The measurements

| # | Space / configuration | decider hit | foreign precision | argmax@1 | Verdict |
|---|---|---|---|---|---|
| 1 | `hash256-v1` (sha1 bag-of-words) | 0.06 | 0.8667 | — | identical to lexical on every metric. Hashing bag-of-words IS lexical in a trench coat. Predicted by the design doc; measured anyway. |
| 2 | `l5-512-v1`, raw cosine, τ-sweep 0.30–0.80 | 0.14 | **0.0167** (best) | 3/100 | every (query, key) pair ≥ 0.70 — absolute τ never bites. hit 2.3× baseline but precision is destroyed. |
| 3 | `l5-512-v1`, **centered** (population-mean removal), τ 0.05–0.40 | 0.10–0.18 | **0.0000** | 2/100 | anisotropy correction does not restore discrimination. Top-1 margins: paraphrase median 0.245 vs foreign 0.218 — no separation. |
| 4 | `l5-512-v1`, `/v1/embed` re-provenanced to the QKEY chat-template (templated user turn, exactly `mint_question_l5` step 2) | — | — | 2/10 probe | cosines compress FURTHER (0.88–0.93, top-2 gaps ~0.01): the template scaffold swamps content. |

Bring-up also caught, and fixed, three bugs of the repo's own bug class:
a **ts-degenerate fixture join** (all 50 corpus facts minted in one second; seam@1 read 1.00
while the probe showed the wrong fact on top — joins are by content address now), a
**stale mtime-keyed index cache** serving a dead vector (key is mtime_ns+size now), and a
**clock-frozen golden** (scores carry the decaying salience recency term; event-class
half-life is 3 days and the golden went stale in hours — the golden pins row identity and
order now, plus a same-instant flags-absent==flags-zero byte check). And one guard fired
unprompted: the first G-SEM-RANK test fact ("spare key under the blue pot") was
auto-classified `private-secret` and DECLINED on the semantic path — G-SEM-CLAIM §3
observed in the wild before it was written.

## The diagnosis, in two parts

1. **The transplanted signal was a ranking signal, not a threshold.** G-REP-LAYER-L5's
   88.5% is recall@1 — the engine only ever uses L5 cosine as an argmax inside its own
   selector ensemble. On a realistic single-person corpus (50 facts, every query the same
   syntactic family), raw L5 cosine does not even rank (3/100), in either provenance.
   Whatever write_ep_l5.py's curated-corpus eval was measuring, it does not transfer to
   QKEY-generated keys on dense personal facts through cosine alone.
2. **Foreign-query rejection is an absence judgment, not a similarity judgment.**
   "Does he play golf" is genuinely NEAR stored question-keys — everything in her store is
   a question about him. No threshold on nearness can decide "this fact is not there."
   The machinery on this box that solves exactly this is the engine's LEARNED selector:
   W_c with the (E+1)-NULL argmax — G-CHAT-B3-WC-DIV2, 360/361 recall AND 50/50 reject.
   The reject class is learned, not thresholded. This is the core boundary thesis
   (ARM/W_c) catching this design like it caught every hand-built signal before it.

## The direction (Phase 3 of docs/SEMANTICS.md, revised)

Stop re-deriving similarity from raw hidden states. **Expose the engine's own live
selector as the semantic admission oracle**: a read-only route (shape:
`/v1/recall_rank {query, candidates[]} -> {scores[], null_score}`) over the W_c + NULL
machinery already running host-side in `recall.rs`/`routes.rs`, consumed at the same
single seam behind the same flag, held to this same scoreboard. The NULL score is the
missing absence judgment. Everything built this session (S0 index, the dual-gate seam,
the corpus, the sweep harness, G-SEM-*) is the measurement rig that decision plugs into —
the rig is the deliverable; the τ-gate was one contender, and it lost on the record.

## What stays shipped

S0 (sidecar index, 81/81 coverage, G-SEM-INDEX 21/21); the S1 seam machinery default-off
(G-SEM-RANK, G-SEM-CLAIM 6/6, G-SEM-CONSERVE); the engine seams `/v1/embed` (QKEY
provenance) and `SP_CAPTURE_L5` ep.l5 mint on `/v1/capture` — grown episodes stop being
L5-invisible to the ENGINE's own selector, which is worth having regardless of S1's τ-gate
losing; and the scoreboard + frozen corpus as the standing bar.
