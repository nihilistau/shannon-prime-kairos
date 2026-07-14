# The Fringe Case Is a Cell: Building Agent Memory on Invariant Maximality

*(draft for a Hugging Face forum post — Research / Show and Tell. Follows on from my
replies in the AlphaAvatar v0.6.4 thread about surprisal, silence, and provenance.)*

---

A while back, in the AlphaAvatar thread, I wrote about information-as-surprisal — the dog
that didn't bark, the neighbour who doesn't wave one morning — and about why "Knack said
his cat's name is Tuffy" and "the system inferred Knack is a cat person" must never
collapse into the same kind of memory. This post is what those two ideas grew into once
we stopped treating them as features and started treating them as symptoms of one
problem. We rebuilt the entire memory/semantics layer of our companion system
(Shannon-Prime / kairos: a local 12B on one RTX 2060, Rust engine, Python harness,
one user, real persistent memory) on a single foundation, and I want to lay out what it
is, why it works, where it works, and how I'd suggest implementing it.

## The problem: memory correctness is a whack-a-mole machine

Count the rules a real agent-memory system ends up enforcing: tombstoned facts never
recalled; an inference never spoken over the user's own testimony; self-facts and
user-facts never merged; secrets declined when the query asks for a detail the record
lacks; attribute slots supersede while properties accumulate; corrections propagate;
provenance survives maintenance scripts. Every one of ours was added after a live
failure. The cat fact ate the open-water fact (one slot, two topics). A cleanup pass
appended to a provenance string and silently turned her conclusions back into my
testimony. A privacy guard checked for a class that nothing could produce — it had
never fired once, and couldn't.

Each fix was a hand-written conditional at some seam. And each conditional created new
boundary behaviour, because **rules written as code have an unbounded case space**. A
regex over prose, a threshold over a score, an `if` over ad-hoc fields — these can meet
a new input shape forever. Your test suite pins the cases you have *met*. Nothing bounds
the cases you haven't. That's the whack-a-mole machine, and discipline only slows it.

We also measured the seductive alternative properly before rejecting it: semantic
similarity as policy. We wired our model's own layer-5 query embeddings (measured
88.5% paraphrase recall as a *ranking* signal) into recall admission as a cosine
threshold, swept the threshold over a frozen 160-query corpus, tried raw, centered,
and re-provenanced variants. Best foreign-query precision at any usable recall: 0.017.
The lesson wasn't "bad embedding." It was: **"semantically similar" has no finite
refutation semantics.** There is no witness you can put in a test that proves a
similarity verdict wrong. Anything built on magnitudes is a preference. If you build
*policy* on it, you tune forever and prove nothing.

## The foundation: Friedman's invariant maximality, taken literally

Harvey Friedman's Invariant Maximality program (the current book-in-progress form:
order-invariant constraints on Q[-1,1]^k, maximal solutions, invariance under partial
self-maps f of the value axis) is usually discussed as metamathematics — which
statements need large cardinals. We're using it as an engineering blueprint, because
three of its structural results are exactly the missing discipline:

**1. Order-invariant relations are finite objects.** A relation on Q^k whose membership
depends only on the *order type* of the tuple — the pattern of <, =, > — is fully
specified by finitely many order types. Translate: give every memory row a small
**signature** σ = (speaker, status, lifecycle, class, slot, time coordinates), and
require every *correctness* decision to be a function of the order type of a small
tuple of signatures. Then the rule space is **finite and enumerable**. A "fringe case"
is an unclassified cell in a finite table. The game board has edges you can walk.

**2. Value-anonymity is a theorem, not a style guide.** Friedman's GC/MAX/f result:
for *general* (value-dependent) constraints, the only invariance you can demand of
maximal objects is the identity. In engineering terms: the moment your policy layer
inspects raw values — prose, magnitudes, calendar dates — you provably forfeit every
invariance guarantee. "Policy sees order types only" isn't hygiene. It's the hypothesis
the guarantees stand on.

**3. The demandable property language is universal sentences with bounded negation.**
The newest form of the program demands the maximal object satisfy
(Q[-1, sup(fld(S))], <, S) ⊨ φ, with φ universal — and you may mention what is NOT in S
only within a region bounded by S's field. Three things fall out of this that we had
been doing by instinct and can now do by license:

- Gate assertions should be **∀-statements over the cells** ("for all tombstoned rows:
  silent on every path"), which is the mathematically maximal demandable class.
- **Absence is only assertable where you were looking.** Bounded negative mention is
  formally the dog-that-didn't-bark from my earlier post: my `silences()` only flags a
  broken cadence on a claim that HAD a cadence — an expectation the store's own field
  established. Unbounded absence claims aren't in the class, and shouldn't be in your
  memory system either.
- **Existential demands aren't in the class.** You cannot demand "there exists a fact
  such that…" of the maximal view — which derives, rather than legislates, the design
  asymmetry that every failure should fall toward *silence* (a lost sentence) and never
  toward speaking wrongly (a lost fact, or her voice over mine).

## The architecture: three strata, one entry bar

The entry bar (this is the whole system in one sentence): **a mechanism may
participate in verdicts iff every violation of its correctness claim has a finite,
machine-checkable witness.** That's the Π⁰₂ discipline from the conservation theorems
(WKL₀ over PRA: ideal reasoning is admissible exactly when it mints no unwitnessable
concrete claims). It sorts everything:

- **Verdict layer** — rules as *data*: committed decision tables over signature cells,
  evaluated at one seam. Admission to speech, privacy declines, supersede permission,
  framing ("Knack told me:" vs "I've come to think:"), evidence gating for reflection.
  Violations are cells — printable, diffable, reviewable.
- **Rank layer** — magnitudes, welcome and confined: recency decay, salience,
  surprisal-in-bits, embedding cosine, learned selector scores. Rank orders the
  *admitted*. It never admits, never retires, never rules. (Surprisal from my earlier
  post lives here, happily: importance is derived, but importance is never a verdict.)
- **Oracle layer** — the model itself, quarantined: LLM judgments ("do these two
  statements concern the same subject?") and embeddings *propose* — links, candidates,
  reclassifications — into an append-only sidecar. Proposals flow through the verdict
  table like everything else. Crucially we choose the failure direction: in our system
  an oracle's link can only push toward silence (a wrong link silences one inference;
  a missing link is yesterday's behaviour). The oracle can be arbitrarily wrong, or
  switched off, and no non-negotiable can break — not because a guard remembers to
  fire, but because the violating object has no cell to live in.

On top sit the **meta-gates**, which is where the maximality theory earns its name:

- **Completeness**: enumerate every reachable cell *through the real writer and the
  real recall path* (not hand-built rows — a fixture that supplies its own precondition
  tests nothing), record the ruling, freeze the table. An unruled cell is the gate's
  finite witness.
- **Consistency**: same cell, different prose ⇒ same ruling. This is the check that
  catches "policy secretly reading text."
- **Invariance**: verdicts survive the *provable* transformation class — uniform time
  translation (order types unchanged ⇒ verdicts unchanged), future extension (the past
  doesn't flip because the world grew), unrelated retirement. Friedman's FIN/USE
  theorem even gives a decidable admissibility test for *new* invariance maps
  (strictly increasing + two endpoint conditions, checkable pairwise) — so the
  invariance family is extensible with a bouncer. And deliberately NOT demanded:
  invariance under reordering observations. What he said second superseding what he
  said first is load-bearing. A memory invariant under observation order cannot learn.

## Does it work? The receipts

We converted eight decision sites in two days. **Every single conversion found a live
bug or drift on the day it landed.** Not hypotheticals — things that were already
wrong:

- The **first field shadow** over the live store (a read-only check that everything
  admitted is table-admissible) found two unmapped cells in minutes: her self-lane
  preference rows and event-class rows — my enumeration templates had never landed in
  those classes. The fix was a reviewed diff against a committed table.
- **Unifying the class vocabulary** (four enumerations and three class→delivery maps
  had grown across Python and Rust) found that a two-day-old incident fix — "a
  remembered thing is CONTEXT, not a command" — had been applied in *one of three*
  copies. The other two were still stamping the pre-incident delivery onto every new
  concept.
- **Converting the framing/evidence/supersede verdicts** found the *normalization law
  itself* had forked: a legacy row with a missing status field was "her conclusion" to
  the renderer and "his testimony" to the seam — ground truth in one place and a guess
  in the other, same row, simultaneously.
- The **enumerator's own bring-up** caught a phantom privacy leak and a phantom
  conflict — both caused by labeling cells by *intent* instead of computing coordinates
  from the system's *operational relations*. That correction is now doctrine: the cell
  is what the code computes, never what the recipe meant.
- And the prose-topic gap the enumeration surfaced ("wary of ladders after a fall"
  shares one content word with "relaxed about ladders these days", so testimony failed
  to cover the inference) was closed by an oracle-proposed same-subject link — under
  quarantine, so the judge model's measured unreliability (zero false positives, zero
  true positives across four prompts — small greedy models are bad at this!) cost
  nothing but yield.

Two of the converted systems (the unprompted-speech gate and a state ladder) turned out
to be *pure functions with threshold-mediated magnitudes*, so their enumeration is
**exhaustive** — all 512 cells each, walked edge to edge. There, no runtime shadow is
even needed: the world cannot produce a shape the board missed, and properties that
used to be paragraphs of argued comments ("a promise outranks manners"; "a stop always
wins, gated by nothing"; "no rung is ever skipped") are now ∀-theorems checked over
every cell on every run.

## How I'd suggest implementing it (in any stack)

1. **Write the signature first.** Small, finite coordinates + rational time fields.
   Everything policy may see. If a policy-relevant distinction isn't in σ, it's
   invisible to every check — so adding a coordinate is a reviewed event.
2. **Compute coordinates from operational relations**, never from intent. If your
   system has a topic-overlap function, the competition coordinate is *that function's
   answer over the store at observation time*, not what your test meant to set up.
3. **Enumerate through the real paths.** Real writer, real recall, real decider. Let
   the writer refuse recipes — a refusal is a ruling of your admission layer, with a
   reason attached.
4. **Freeze the table. Gate the diff.** From that commit forward, changing behaviour
   without saying so trips a gate — that day, not months later at 3am.
5. **Write your gates in the φ-fragment**: ∀ over cells, negation only where bounded
   by what the store covers, no existential demands.
6. **Shadow before cutover.** Run the evaluator read-only against live traffic;
   count divergences and unmapped cells with witnesses. Cut over only on a
   zero-divergence receipt — and even then, let the table only *exclude* (authority
   moves; the old code stays as belt-and-braces).
7. **Confine, don't convert, your magnitudes** — and quarantine your models. Rank
   ranks. Oracles propose. Choose every oracle's failure direction so a wrong answer
   costs a sentence, never a fact.
8. **Keep one copy of everything.** One normalization function, one vocabulary
   registry, one signature implementation — and where a consumer can't import it
   (our Rust engine), parse its *source* in the gate and convict drift at the seam.

## What it doesn't do (honesty section)

The classifiers stay fallible: is-this-memorable, which-class, is-this-the-same-subject
are prose/model judgments, and no table fixes that — the table fixes what their outputs
are *allowed to do*. The enumeration sees only σ. Multi-round promises (invariances
that must survive unbounded re-completion as the store grows forever) are
axiom-conditional in the strict sense — falsifiable forever, verifiable never — and we
label them as such rather than pretending a test suite closes them. And none of this
makes retrieval semantically smarter by itself; it makes the system *safe to make
smarter*, because the clever parts are structurally incapable of breaking the promises.

That's the trade we chose, and after watching the same five bugs regrow for months, I'd
make it again: put the intelligence where it can only propose, put the mathematics
where it rules, and make every fringe case a diff instead of a discovery.

Repo: github.com/nihilistau/shannon-prime-kairos — the foundation doc is
`docs/INVARIANT-MEMORY.md`, the extension map `docs/INVARIANT-ROADMAP.md`, and every
claim above has a gate in `harness_tests/` with the receipt in the commit that landed
it. Friedman's current manuscripts (the Invariant Maximality chapters, 2024–2026) are
on his OSU page and are far richer than the 2014 paper most people cite — FIN/USE and
the usability hierarchy are the parts an engineer can take home.
