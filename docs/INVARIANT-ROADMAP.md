# INVARIANT-ROADMAP.md — how far the foundation carries

**Status: ROADMAP (2026-07-14). [`INVARIANT-MEMORY.md`](INVARIANT-MEMORY.md) is the foundation
(built, gated, armed); THIS file is where it goes next — the updated mathematics mapped to
engineering, the inventory of every decision site still ruling by hand, and the honest limits.
Nothing here is built until its row moves to a phase in the foundation doc with a gate attached.**

Sources: Friedman's current book chapters (*Invariant Maximality Derivations*, Oct 2025;
*Reversals*, Jun 2025; the Jan 2026 N-shift reorganization, Lectures 29–33) and a full
decision-site survey of this tree. The 2014 paper we started from is three generations stale;
the current program is richer in exactly the directions we can use.

---

## 1. THE UPDATED MATHEMATICS, MAPPED

The program's new shape: everything lives in Q[−1,1]; the Lead Template is **OC/MAX/f** — *every
order constraint on S ⊆ [−1,1]^k has an f-invariant maximal solution* — parameterized by a partial
self-map **f :: Q[−1,1] → Q[−1,1]** of the value axis, and the central question is **which f are
usable** (demandable of maximal objects). Each result below carries a design rule for us.

### 1.1 FIN/USE — invariance admissibility is DECIDABLE (the biggest gift)

For finite f, usability is completely characterized, provable in weak arithmetic, and **locally
checkable**: f is fully usable iff strictly increasing + two endpoint conditions, iff **every
2-element restriction is usable**, with EXPTIME witnesses.

> **Design rule: invariances stop being hand-picked.** Today G-SEM-STABLE gates three instances
> (time translation, future extension, unrelated retirement). FIN/USE licenses a
> **G-SEM-ADMISSIBLE** meta-gate: any PROPOSED invariance map over the time/value axis is
> machine-checked for admissibility (monotone + endpoint conditions, pairwise) BEFORE it becomes
> a gate. The invariance family becomes a parameterized, extensible set with an entry test,
> instead of three artisanal theorems.

### 1.2 GC/MAX/f triviality — the signature discipline is a theorem, not a taste

For general (value-dependent) constraints, the ONLY usable f is the identity: no nontrivial
invariance is demandable of maximal objects unless the constraint language is order-invariant.

> **Design rule, now theorem-shaped:** a policy layer that inspects raw values (dates, magnitudes,
> prose) forfeits every invariance guarantee at the maximal-object level. Our "policy sees order
> types only" rule (INVARIANT-MEMORY.md §1.1) is not hygiene — it is the exact hypothesis the
> guarantees stand on.

### 1.3 The usability hierarchy — label gates by what they cost

Strength grades along (identity on a live region) + (shifted ladder of landmark points) ×
(dimension): pure finite shift → weak arithmetic; interval + ladder → climbs through Zermelo to
subtle cardinals (Con(SRP)). All forms stay falsifiable (implicitly Π⁰₁): violations are finite
objects.

> **Design rule: every gate gets a strength label.** Single-round checks (one greedy completion,
> one enumeration pass — FIN/USE territory) are DECIDABLE and we own them outright. Multi-round
> promises (an invariance that must survive iterated re-completion as the store grows forever)
> are AXIOM-CONDITIONAL — still falsifiable, never fully verifiable. The gate index should say
> which kind each gate is. Nothing changes operationally; the CLAIMS get honest.

### 1.4 The sixteen equivalences — representation freedom

Square / root / clique / independent-set / free-set / emulator (given a fixed point) forms are
pairwise interchangeable over RCA₀ at identical strength.

> **Design rule:** the maximal-consistent-view can be implemented as whichever structure is
> cheapest (a clique over a compatibility graph, an independent set over a conflict graph — same
> guarantees, same cost). Pick the data structure for engineering reasons; the math is indifferent.

### 1.5 Joint usability — composing invariance gates

Several maps (finite strictly-increasing pieces + identity on initial segments) can be demanded
SIMULTANEOUSLY of one maximal object — and whether each fixed region includes its right endpoint
changes the consistency budget of the composite.

> **Design rule:** multiple invariance gates (aging, quarantine boundaries, landmark shifts)
> compose coherently, but each gate's fixed-region boundary convention is a SEMANTIC decision to
> be stated in the gate's docstring, not a style choice.

### 1.6 The φ-form — our gate language, formalized (operator's pointer, 2026-07-14)

The newest material demands the maximal object SATISFY a universal sentence:
**(Q[−1, sup(fld(S))], <, S) ⊨ φ**, φ universal — and S may be mentioned NEGATIVELY (what is not
in S) provided the mention is BOUNDED by S's field.

> **Design rule, and it is the deepest one:** the demandable property language for the store is
> exactly **∀-sentences over (time-order, membership) with bounded negation**. Three corollaries:
> 1. G-SEM-TABLE's ∀-theorems are already sentences of this language — the gate style we
>    converged on is the mathematically maximal demandable class, not an aesthetic.
> 2. **Bounded negative mention IS the presence-ledger law.** "Nothing in this region is in S"
>    is only a legitimate demand inside a region the store's field covers — G-SILENCE's "absence
>    is only information if you were looking," derived instead of legislated.
> 3. **Existential demands are NOT in the class.** "There exists a fact such that…" cannot be
>    demanded of the maximal view — which is the fail-toward-silence asymmetry (a gate may
>    require silence, never require speech), also now derived.
> Future gates should be WRITTEN in this fragment: quantify over cells/rows, use bounded
> negation, never assert existence. A linter for gate assertions is cheap and worth it.

### 1.7 The N-shift reorganization (Jan 2026)

The book's seminal statement is now a SINGLE canonical invariance (the N-shift — add 1 to the
N-tail) on maximal chains, with the f-theory as "Local Invariance" behind it. Our G-SEM-STABLE
time-translation check is the scaled shadow of exactly this canonical map.

---

## 2. THE EXTENSION MAP (from the decision-site survey)

Every site below still rules via hand conditionals. Tiered by value/risk; each conversion follows
the proven recipe: operational signature → committed table → shadow → meta-gates → cutover.

### Tier 1 — next (high value, low risk, recipe applies directly)

1. **`kairos/impulse.decide()` — the unprompted-speech gate. DONE 2026-07-14.**
   **G-KAIROS-TABLE 12/12**: because decide() is pure and every magnitude enters through a
   threshold, the verdict domain booleanizes EXACTLY — the enumeration is **exhaustive (all 512
   cells through the real decide(), committed at `fixtures/kairos/impulse-table.json`)**, so no
   runtime shadow is needed: complete coverage means any cascade change trips the gate as a cell
   diff. The ~80 lines of argued check-ordering are now a committed PRECEDENCE artifact that the
   code PROVABLY implements (first-match semantics over every cell), and the argued properties
   are φ-fragment ∀-theorems over the whole domain: spam bounds dominate even promises; a clear
   promise always reminds; she never fills a silence she made; his turn buys her budget; nothing
   speaks around the bounds. This is the discipline's strongest form — a domain with edges you
   can walk.
2. **One class vocabulary, one frozen artifact. DONE 2026-07-14 — and it found a LIVE drift.**
   The 2026-07-12 engine fix (fact → system: "a remembered thing is CONTEXT, not a command") had
   been applied in ONE of the THREE class→delivery copies; `okf_mem.py` and `self_model.py` still
   said fact → recite — the exact delivery behind the recited-memory incident. Now:
   `harness/skills/memclass.py` is THE registry (classes + deliveries + per-class producers — the
   G-SECRET §4 producer/consumer closure held globally); okf_mem and self_model CONSUME it (their
   literals are deleted, and **G-MEMCLASS 28/28** asserts the literals stay deleted — equality can
   be faked by a faithful copy, absence cannot); `lifecycle.classify` is probe-held to its declared
   productions; `recall.rs` is pinned AT THE SOURCE (match arms and classifier returns parsed from
   the Rust and held to the registry — the G-ONEDOOR trick); the verdict table's class coordinates
   and the spine's branched classes join the same registry. Bonus fix: `self-fact` concepts used
   to FAIL OKF conformance under the old seven-class vocabulary.
3. **`scheduler._is_evidence()` + `lifecycle.find_superseded()` + `lifecycle.render()`.
   DONE 2026-07-14 — and the conversion found the NORMALIZATION LAW itself had diverged.**
   A legacy row (status missing, src sniffing "reflection") was HER CONCLUSION to render and
   _is_evidence (both carried the migration shim) but HIS TESTIMONY to testimony_wins and σ
   (plain observed-default): ground truth at the seam, a conclusion at the mouth — one live row
   sat in that crack. Now: `lifecycle.status_of()` is THE normalization (structured field wins;
   src sniff is the one sanctioned legacy read, protect-him default), consumed by σ,
   testimony_wins, render, find_superseded, and is_evidence. The three verdicts are σ
   projections reading committed tables in `verdict.py` (`FRAMING`, `may_supersede`,
   `is_evidence`), and **G-SEM-PROJ 25/25** walks every cell of all three through the REAL
   consumers — including the supersede matrix through the real writer (attribute shapes,
   because properties accumulate) and the seam check that a legacy reflection row no longer
   wears testimony's shield. Full 20-gate suite green.

### Tier 2 — DONE 2026-07-14 (all four, one commit; the principle is now AGENTS.md §1.5)

4. `spine.hygiene_decider` — DONE: `memory.registry_status()` is a three-value enum
   (ok / needs-compaction / unconfigured); the decider consumes it; the prose report is a
   receipt, not a branch target.
5. `app.py` one-authority guard — DONE: `spine.authority_lane()`, a pure function enumerated
   exhaustively (16 cells, **G-LANE-TABLE 15/15**) with the body-count theorem held over every
   cell: NEVER both authorities on one turn, the lane never arms what the caller didn't ask for.
6. `roleplay/ladder.step()` — DONE: 512 cells walked edge to edge (**G-LADDER-TABLE 10/10**,
   `fixtures/roleplay/ladder-table.json`): a stop always wins gated by nothing; cooling always
   works; the build is the scene; the ceiling is the operator's word; no rung is ever skipped.
7. Spine decider priorities — DONE: `spine.PRIORITIES` is the committed ordering; every stock
   constructor provably consumes it.

### Tier 3 — the far edge (the foundation's full reach)

8. **Maximal-consistent-view recall as an explicit greedy completion.** OC/MAX's constructive
   residue: maximality alone is cheap, canonical (enumerate in code-length order, insert what
   stays consistent), and EXPTIME-witnessed. Recall's result set becomes literally a maximal
   square in the table-compatibility relation, built greedily over a canonical key order — the
   final form of Phase C.
9. **G-SEM-ADMISSIBLE** (§1.1) — the invariance entry test, parameterizing the stability family.
10. **The gate-language linter** (§1.6) — assert gate claims are ∀-with-bounded-negation.
11. **Engine delivery dispatch** (`routes.rs` 2973–3096) — the `delivery_mode` switch consumes
    the unified class→delivery table instead of a hand-written chain.
12. **Strength labels in GATE-INDEX** (§1.3) — DECIDABLE vs AXIOM-CONDITIONAL per gate.

### Deliberately OUT of scope for tables (and why)

- **Admission-by-content** (`is_memorable`, `worth_saying`, `classify`): classifiers over prose.
  They are PRODUCERS, quarantined exactly like oracles — their OUTPUT vocabulary gets unified and
  pinned (Tier 1.2), their internals stay regex/model and fallible, their failures land in the
  admission direction (refuse/misfile), never in verdicts.
- **The rank layer** (`salience`, `surprisal`, `silences`, cadence math): magnitudes by design;
  the foundation CONFINES them (rank orders the admitted; never admits, never rules), it does
  not convert them.
- **Model-deferred judgment** (`agency`): the one place that deliberately asks the model to
  judge; it proposes, the table disposes — already the quarantine shape.

---

## 3. HOW FAR, HONESTLY

The foundation carries as far as decisions over finite signatures reach — which the survey shows
is almost every verdict in the system — and stops, on purpose, at three boundaries: the
enumeration sees only σ (a distinction missing from the signature is invisible to every meta-gate;
adding one is a reviewed event); classifiers and oracles remain fallible producers whose failure
directions are chosen, not eliminated; and multi-round invariance promises are conditional claims
that stay falsifiable forever without becoming verifiable (§1.3 — label them). Within those
boundaries, what the mathematics now licenses that we have not yet built: a decidable entry test
for new invariances, a formally maximal gate language with bounded negation, representation-free
maximal views with canonical greedy witnesses, and composition rules for stacking invariance
gates. That is the map. One tier at a time, one gate per claim, and the commit message carries
the reasoning.
