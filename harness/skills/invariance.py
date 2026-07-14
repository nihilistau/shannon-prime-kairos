"""invariance — the ENTRY TEST for invariance maps (Tier 3, INVARIANT-ROADMAP.md §1.1).

The stability family (G-SEM-STABLE) used to be three artisanal theorems. Friedman's
FIN/USE gives the discipline an admissions office: for a FINITE partial self-map f of a
bounded value axis, "can this invariance be demanded of maximal objects?" is completely
characterized, decidable, and LOCALLY checkable —

    FIN/USE: f is fully usable  iff  f is strictly increasing AND both endpoint
    pathologies fail:  NOT(lo < f(lo) and f⁻¹(hi) < hi)  and  NOT(lo < f⁻¹(lo) and
    f(hi) < hi).
    FIN/USE*: fully usable  iff  every TWO-ELEMENT restriction is usable.

Engineering reading: an invariance gate over the time/value axis is admissible iff its
map is monotone and does not simultaneously lift one endpoint while reaching the other
from strictly inside. The pairwise theorem means the check is local — no global search.

USE: any transformation proposed for the G-SEM-STABLE family passes through
admissible() BEFORE it becomes a gate. A map this module rejects is not a worse
invariance — it is one the mathematics says CANNOT be consistently demanded of maximal
views at all, and gating it would be pinning a promise that provably cannot hold.

Maps are finite dicts {a: b} of Fractions/floats over an axis [lo, hi]; identity points
may be included or omitted (only the moved points matter to the conditions). Unbounded
axes (our time line) pass the endpoint conditions vacuously — declare the bounds you
actually enforce.
"""
from fractions import Fraction


def _pairs(f: dict):
    return sorted((Fraction(a).limit_denominator(10**9),
                   Fraction(b).limit_denominator(10**9)) for a, b in f.items())


def admissible(f: dict, lo=None, hi=None):
    """(ok, why) for a finite map on the axis [lo, hi] (either bound may be None =
    unbounded on that side; the matching endpoint condition is then vacuous)."""
    pts = _pairs(f)
    if not pts:
        return True, "empty map (identity): trivially usable"
    # strictly increasing (FIN/USE i->iii, via Thm 3.5.1.1's necessity)
    for i in range(len(pts) - 1):
        (a1, b1), (a2, b2) = pts[i], pts[i + 1]
        if a1 == a2:
            return False, "not a function: %s mapped twice" % a1
        if not (b1 < b2):
            return False, ("not strictly increasing: f(%s)=%s !< f(%s)=%s"
                           % (a1, b1, a2, b2))
    dom = {a for a, _ in pts}
    rng = {b for _, b in pts}
    if lo is not None:
        LO = Fraction(lo)
        if any(x < LO for x in dom | rng):
            return False, "map leaves the declared axis (below lo)"
    if hi is not None:
        HI = Fraction(hi)
        if any(x > HI for x in dom | rng):
            return False, "map leaves the declared axis (above hi)"
    # endpoint pathologies (FIN/USE iii): each needs BOTH conjuncts to hold to be fatal
    def fwd(x):
        d = dict(pts)
        return d.get(x, x)

    def inv(x):
        d = {b: a for a, b in pts}
        return d.get(x, x)

    if lo is not None and hi is not None:
        LO, HI = Fraction(lo), Fraction(hi)
        if LO < fwd(LO) and inv(HI) < HI:
            return False, ("endpoint pathology: f lifts lo while hi is reached from "
                           "strictly inside — FIN/USE says this invariance cannot be "
                           "demanded of maximal objects")
        if LO < inv(LO) and fwd(HI) < HI:
            return False, ("endpoint pathology (dual): f⁻¹ lifts lo while f pulls hi "
                           "strictly inside")
    return True, "strictly increasing, endpoints clean: usable (FIN/USE)"


def admissible_pairwise(f: dict, lo=None, hi=None):
    """FIN/USE*: the LOCAL form — usable iff every two-element restriction is usable.
    Exists so the gate can assert the locality theorem holds on real batteries (the
    global and pairwise answers must agree; disagreement is a bug in THIS module)."""
    pts = _pairs(f)
    if len(pts) <= 1:
        return admissible(f, lo, hi)
    for i in range(len(pts)):
        for j in range(i + 1, len(pts)):
            ok, why = admissible(dict([pts[i], pts[j]]), lo, hi)
            if not ok:
                return False, "2-element restriction {%s, %s}: %s" % (
                    pts[i][0], pts[j][0], why)
    return True, "every two-element restriction is usable (FIN/USE*)"
