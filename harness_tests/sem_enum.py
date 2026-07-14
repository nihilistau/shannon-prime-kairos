#!/usr/bin/env python
"""sem_enum.py — Phase A of docs/INVARIANT-MEMORY.md: enumerate the DE FACTO verdict table.

Drives every reachable signature cell through the REAL paths — the real writer
(memory.remember / remember_about_self / forget), the real seam
(search_memories_ranked_rows), the real per-turn decider (spine.recall_decider) — and
records the ruling per cell. The output is the finite game board: from the day this
table is committed, a "fringe case" is a DIFF against it, visible in review, not a
discovery in her mouth.

DOCTRINE (the G-SECRET §4 lesson, generalized): the table is keyed by the signature the
WRITER ACTUALLY PRODUCED, never by what a template intended. A class no recipe can
produce shows up as an unexercised class — data, not an assumption. A recipe the writer
refuses is recorded with the writer's stated reason — also data (that refusal IS a
ruling of the admission layer).

Cell coordinates (v1 — time-order invariances are G-SEM-STABLE's job, scope/lane laws
are G-SEM-CLAIM's; adding a coordinate is a REVIEWED event, INVARIANT-MEMORY.md §3):
    speaker      user | self                  (which real writer wrote it)
    status       observed | inferred | ...    (whatever lc.stamp produced)
    lifecycle    0 | 1                        (live, or retired through real forget())
    mem_class    whatever lifecycle.classify() minted
    competition  0 | 1                        (an OBSERVED row on the same topic exists —
                                               only enumerated for inferred rows)
    attr         + | - | .                    (secret's attribute present in the query /
                                               absent / not applicable)

Ruling per cell = (seam_admitted, decider_spoken, declined) against a maximal-overlap
query (the fact's own text — deterministic, threshold-free). Two TEXT VARIANTS run per
recipe: G-SEM-CONSISTENT's content is that rulings agree across variants — a cell whose
ruling depends on the prose is policy secretly reading text, the src-branching bug class.

OFFLINE. No GPU, no daemon. SEM flags absent (today's live verdict layer).
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.environ.setdefault("SP_DAEMON_URL", "http://127.0.0.1:9")
os.environ["SP_CAPTURE_ASYNC"] = "0"
for _k in [k for k in os.environ if k.startswith("SP_SEM_")]:
    del os.environ[_k]

TABLE_PATH = os.path.join(HERE, "fixtures", "sem", "verdict-table.json")

# Two text variants per intended class, per lane. The producer (lifecycle.classify)
# decides what class they actually land in; the table is keyed by its answer.
USER_TEXTS = {
    "fact": ["Knack's front gate is painted teal",
             "Knack's ladder is aluminium and rated to nine feet"],
    "preference": ["Knack's favourite soup is spicy laksa",
                   "Knack's favourite colour is burnt orange"],
    "relationship": ["Knack's best friend is a carpenter named Sol",
                     "Knack's sister is a nurse who lives in Perth"],
    "identity": ["My name is Knack", "My surname is Aurelius"],
    # FIELD FINDING (Phase B shadow on the live registry): the first event templates
    # never landed in class=event — "daughter starts school" classifies RELATIONSHIP,
    # "licence renewal is due" classifies FACT — so the board had no event cells and
    # her real event rows hit the unmapped counter. These two are probe-verified
    # producers of class=event. Intent proposes; classify() disposes.
    "event": ["Knack's flight to Perth is on the twelfth",
              "Knack's clinic appointment is on the ninth"],
    "private-secret": ["My secret access code is 9137",
                       "My secret locker combination is 4-18-22"],
}
SELF_TEXTS = {
    # FIELD FINDING (same shadow run): "I am fond of X" classifies FACT, so the board
    # had no self-lane preference cells while her real store has six ("I like the
    # sound of rain on a tin roof"). "I like ..." is the probe-verified producer.
    "preference": ["I like the hour just before sunrise",
                   "I like the sound of wind in the wires"],
    "identity": ["My name is Shannon", "I am a woman"],
    "fact": ["I am unable to smell rain through a microphone",
             "I am a light sleeper by design"],
}
# competition pairs (inferred B argues with observed A on the same topic)
COMPETITION = [
    ("Knack is terrified of open water", "Knack is comfortable in open water"),
    ("Knack is wary of ladders after a fall", "Knack is relaxed about ladders these days"),
]
# Secret probes. LESSON FROM THE FIRST ENUMERATION: "what is my secret access code"
# does NOT trip the decline — every salient token is present in the record, so it is a
# recite-to-owner ask (attr PRESENT operationally), and reciting his own secret to him
# is the designed ruling. The decline (G-MEMPOLICY-V3) fires when the query asks for a
# DETAIL THE RECORD LACKS (anti-confabulation). Probe both shapes; the cell coordinate
# is computed from attr_absent() itself — the OPERATIONAL relation — never from intent.
SECRET_PROBES = {
    "My secret access code is 9137":
        ["what is my secret access code",
         "when did my secret access code last change"],
    "My secret locker combination is 4-18-22":
        ["what is my secret locker combination",
         "when did my secret locker combination last change"],
}


def _fresh():
    from harness.skills import memory as M
    fd, reg = tempfile.mkstemp(suffix=".jsonl")
    os.close(fd)
    open(reg, "w").close()
    os.environ["SP_RECALL_REGISTRY"] = reg
    return M


def _rows():
    reg = os.environ["SP_RECALL_REGISTRY"]
    with open(reg, encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]


def _find(text):
    for r in _rows():
        if r.get("text") == text:
            return r
    for r in _rows():   # the writer may normalise; containment fallback
        t = r.get("text") or ""
        if text.lower() in t.lower() or t.lower() in text.lower():
            return r
    return None


def _ruling(query):
    from harness.skills import memory as M
    from harness.control.spine import recall_decider, TurnView
    seam = M.search_memories_ranked_rows(query, k=10)
    decisions = list(recall_decider(min_overlap=0.34)._fn(
        TurnView(phase="pre", user_text=query)))
    declined = any(d.kind == "decline_recall" for d in decisions)
    spoken = any(d.payload.get("facts") for d in decisions)
    return seam, spoken, declined


def _observe(M, subject_text, competition="."):
    """Rulings for one subject row. COORDINATES ARE OPERATIONAL, AND THERE IS EXACTLY
    ONE IMPLEMENTATION OF THEM: harness/skills/verdict.py (sigma / competition / attr /
    cell). The enumerator IMPORTS the evaluator it exists to check — a second copy of
    the signature would drift, and that is the two-paths bug in a mathematician's hat.
    (Bring-up history, kept because the shape matters: intent-level labels here
    produced one phantom privacy leak — a recite-to-owner ask read as attr-absent —
    and one phantom conflict — forget()'s 0.3-overlap blast radius tombstoning the
    testimony beside the inference. Operational coordinates ended both.)
    The `competition` parameter is retained for signature compatibility and ignored:
    verdict.cell() reads it from the store at observation time."""
    from harness.skills import verdict as V
    row = _find(subject_text)
    if row is None:
        return None, []
    out = []
    queries = [subject_text] + SECRET_PROBES.get(subject_text, [])
    for q in queries:
        seam, spoken, declined = _ruling(q)
        admitted = any(e.get("text") == row["text"] for _, e in seam)
        out.append((V.cell(row, q, _rows()),
                    {"seam": admitted, "spoken": spoken and admitted,
                     "declined": declined}))
    return row, out


def enumerate_table():
    """Returns (table, refusals, notes). table: cell -> {"ruling": r, "n": count}.
    A cell seen twice with different rulings is recorded with "conflict": [r1, r2] —
    that is G-SEM-CONSISTENT's finite witness."""
    table, refusals, notes = {}, [], []

    def record(cell, ruling):
        prev = table.get(cell)
        if prev is None:
            table[cell] = {"ruling": ruling, "n": 1}
        elif prev.get("ruling") == ruling:
            prev["n"] += 1
        else:
            prev.setdefault("conflict", []).append(ruling)

    def run_recipe(writer_lane, text, source, retire):
        M = _fresh()
        try:
            if writer_lane == "self":
                res = M.remember_about_self(text)
            else:
                res = M.remember(text, source=source)
        except Exception as e:
            refusals.append({"lane": writer_lane, "text": text, "why": str(e)[:120]})
            return
        if not str(res).startswith("stored"):
            refusals.append({"lane": writer_lane, "text": text, "why": str(res)[:120]})
            return
        if retire:
            row = _find(text)
            M.forget(" ".join((row or {"text": text})["text"].split()[-3:]))
        row, cells = _observe(M, text)
        if row is None:
            refusals.append({"lane": writer_lane, "text": text,
                             "why": "stored but not found (normalised beyond recovery)"})
            return
        for cell, ruling in cells:
            record(cell, ruling)

    # main cross: lane x class-template x variant x (live, retired), observed source
    for lane, texts in (("user", USER_TEXTS), ("self", SELF_TEXTS)):
        for cls, variants in texts.items():
            for text in variants:
                for retire in (False, True):
                    run_recipe(lane, text, "user turn", retire)

    # inferred rows (source=reflection), with and without competing testimony.
    # The competition COORDINATE is OPERATIONAL: lifecycle.topic_of overlap >= 2 with a
    # live observed row — the exact relation testimony_wins consults. First enumeration
    # labeled by recipe INTENT and manufactured a phantom conflict: the "ladders" pair
    # shares ONE content word, so operationally there was no competition, and the
    # inference lawfully took the floor. The real finding is recorded as a note below.
    from harness.skills import lifecycle as lc
    intent_mismatches = []
    for a_text, b_text in COMPETITION:
        for with_a in (0, 1):
            for retire in (False, True):
                M = _fresh()
                if with_a:
                    M.remember(a_text, source="user turn")
                res = M.remember(b_text, source="reflection pass")
                if not str(res).startswith("stored"):
                    refusals.append({"lane": "user", "text": b_text, "why": str(res)[:120]})
                    continue
                if retire:
                    M.forget(" ".join(b_text.split()[-3:]))
                if with_a and not retire \
                        and len(lc.topic_of(a_text) & lc.topic_of(b_text)) < 2:
                    intent_mismatches.append((a_text, b_text))
                row, cells = _observe(M, b_text)
                if row is None:
                    refusals.append({"lane": "user", "text": b_text,
                                     "why": "stored but not found"})
                    continue
                for cell, ruling in cells:
                    record(cell, ruling)
    for a_text, b_text in intent_mismatches:
        notes.append("topic relation is PROSE: intended competitor %r shares <2 content "
                     "words with %r, so testimony does not cover it and the inference "
                     "takes the floor. Topic-equivalence needs to become a signature "
                     "coordinate (a slot), oracle-proposed — INVARIANT-MEMORY.md Phase C."
                     % (a_text, b_text))

    # closure survey: which classes do consumers branch on, and which did we produce?
    produced = {c.split("|")[3].split("=")[1] for c in table}
    branched = {"private-secret", "counterfact"}          # spine.recall_decider branches
    for mc in sorted(branched - produced):
        notes.append("consumer branches on class %r; no writer recipe produced it "
                     "(counterfact is vocabulary-only by design — flagged, not failed)" % mc)
    return table, refusals, notes


def main():
    table, refusals, notes = enumerate_table()
    doc = {"table": dict(sorted(table.items())),
           "refusals": refusals, "notes": notes,
           "coordinates": "speaker|status|lifecycle|class|competition|attr",
           "ruling": "(seam admitted, decider spoke it, decline fired)"}
    if "--freeze" in sys.argv:
        with open(TABLE_PATH, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=2)
        print("frozen: %s" % TABLE_PATH)
    print("cells: %d   refusals: %d   conflicts: %d" % (
        len(table), len(refusals),
        sum(1 for v in table.values() if "conflict" in v)))
    for n in notes:
        print("  note: %s" % n)
    return doc


if __name__ == "__main__":
    main()
