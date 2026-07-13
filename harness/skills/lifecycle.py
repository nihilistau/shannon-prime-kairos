"""MEM-OKF v2 LIFECYCLE — the part that makes memory *living* instead of a tape.

THE AUDIT THAT FORCED THIS (2026-07-12). The registry held 487 rows. Of those:

    404  ep_live_   (B4 nightshift AUTO-CAPTURE)
      1  ep_tool_   (the remember() tool)

**The model had deliberately remembered exactly ONE thing in its life** — and 404/405
rows were framed `"The user said: ..."`. So:

  * it never CHOSE what to keep (no authorship),
  * it never SUPERSEDED a fact that changed (no revision),
  * it had no SELF lane at all — every memory was the user speaking, which is precisely
    why it slides into speaking as the user, or mis-genders itself: the only voice in
    its long-term memory is yours.

This module supplies the three verbs a memory needs to be alive:

    SPEAKER   — who does this fact belong to: the user, or Shannon herself?
    SUPERSEDE — a new fact that contradicts an old one RETIRES it (tombstone, not
                delete: `superseded_by` on the old, `supersedes` on the new).
    CLASS     — identity / preference / event / relationship / self, so recall can
                weight them and the operator can see them.

Nothing is ever destroyed. Superseded rows stay on disk with a pointer forward, so
"what did I used to think?" remains answerable — that is the provenance lane.
"""
from __future__ import annotations

import math
import re
import time
import calendar
from typing import Iterable, Optional

USER_PREFIX = "The user said: "

# ── SPEAKER ────────────────────────────────────────────────────────────────────
# A fact is about SHANNON when she is the subject ("I am...", "my voice is...") and
# the row was authored by her. It is about the USER when it came from a user turn.
# The distinction is stored, never inferred at read time — inference at read time is
# exactly how the identity confusion happened.
SPEAKER_USER = "user"
SPEAKER_SELF = "self"

# ── CLAIM STATUS ───────────────────────────────────────────────────────────────
# WHO ASSERTED THIS, and therefore what it is allowed to do to the rest of the store.
# `speaker` says whose facts these ARE (the subject lane, which PersonModel filters on).
# `status` says where the claim CAME FROM, which is a different question and needs its own field.
STATUS_OBSERVED = "observed"     # he said it. The ground truth of this store.
STATUS_INFERRED = "inferred"     # SHE concluded it. Never allowed to retire an observation.
STATUS_CONFIRMED = "confirmed"   # she inferred it and HE AGREED. Promoted to ground truth.
STATUS_DISPUTED = "disputed"     # she inferred it and HE HAD ALREADY SAID OTHERWISE. Kept, never spoken.

# THE ONE RULE. An inference may be recalled, may be spoken (in her own voice), and may itself be
# corrected by anything he says. It may NEVER tombstone something he actually told her.
_GROUND_TRUTH = (STATUS_OBSERVED, STATUS_CONFIRMED)


_STOP = frozenset("""a an the is are was were am be been being of in on at to for with about
    and or but not no so very really quite too my your his her their its our i you he she it they
    we me him them us that this those these there here what which who whom whose how when where
    why do does did done has have had can could will would shall should may might must
    knack user shannon person thing things stuff""".split())


def topic_of(fact: str) -> frozenset:
    """The CONTENT WORDS of a claim — what it is ABOUT, with the grammar and the names stripped out.

    Deliberately dumb. It is not trying to understand the sentence; it is trying to answer one
    narrow question honestly: HAS HE ALREADY SPOKEN TO THIS SUBJECT? Bag-of-content-words is a
    weak instrument, and it is the strongest one I can build here that I am willing to defend.
    """
    words = re.findall(r"[a-z0-9']+", (fact or "").lower())
    return frozenset(w for w in words if w not in _STOP and len(w) > 2)


def testimony_wins(scored: list, overlap: int = 2) -> list:
    """Drop any INFERENCE that is about a topic HIS OWN TESTIMONY already covers.

    ── SHE IS ALLOWED TO BE WRONG ABOUT HIM. SHE IS NOT ALLOWED TO SAY IT OVER HIM. ────────
        observed  'Knack is terrified of open water'    <- he told her
        inferred  'Knack is comfortable in open water'  <- she concluded otherwise

    Surfacing both is not scrupulous, it is DEAF. She would say "you told me you're terrified" and
    "I've come to think you're comfortable" in a single breath — which is not a mind holding two
    hypotheses, it is a mind that heard him and carried on regardless. That is precisely the thing
    that makes a companion feel like it is not listening.

    ── WHY THIS IS A SPEECH RULE AND NOT A STORAGE RULE ────────────────────────────────────
    I first built this as a WRITE-time verdict: detect the contradiction, mark the inference
    DISPUTED, retire it. Then I tried to make the detector, and found I was assembling a semantic
    contradiction engine out of substring matching and a hand-written antonym list. That is the
    clever-fragile thing this codebase has punished me for every single time, and the failure mode
    is the worst one available: A VERDICT I CANNOT DEFEND, WRITTEN TO DISK, WITH A TIMESTAMP ON IT.

    So it does not adjudicate truth. It adjudicates WHO GETS THE FLOOR, and the rule is one line:
    on a subject he has spoken to, HE speaks. Nothing is deleted, nothing is judged, the inference
    stays on disk and stays auditable, and if he later confirms it, it is promoted and speaks.

    It fails SAFE, which the write-time verdict did not. A false topic match costs her a sentence
    she could have said. A false contradiction verdict would have cost her a fact he told her.
    Those are not the same kind of mistake and they must not be traded off as though they were.
    """
    ground = [e for _s, e in scored
              if (e.get("status") or STATUS_OBSERVED) in _GROUND_TRUTH]
    if not ground:
        return scored
    spoken = [(e.get("speaker", SPEAKER_USER), topic_of(strip_prefix(_row_text(e))))
              for e in ground]
    out = []
    for s, e in scored:
        if (e.get("status") or STATUS_OBSERVED) in _GROUND_TRUTH:
            out.append((s, e))
            continue
        mine = topic_of(strip_prefix(_row_text(e)))
        who = e.get("speaker", SPEAKER_USER)
        covered = any(sp == who and len(mine & t) >= overlap for sp, t in spoken)
        if not covered:
            out.append((s, e))            # she has something to add, and no one is talking over
    return out


def _row_text(e: dict) -> str:
    return e.get("text") or e.get("topic") or ""


# find_contradicted() WAS HERE, AND IT IS DELETED ON PURPOSE (2026-07-14).
#
# It claimed to return "the things he said that this inference flatly denies", and it decided that
# by comparing attribute_key() and value_of() — i.e. by SUBSTRING. It could not tell a denial from
# a different sentence on the same subject, and it wrote its verdict to disk as DISPUTED.
#
# Two ways to be wrong, and they are not symmetric:
#   MISS a real contradiction  -> she says something he already denied. Rude. Visible. Correctable.
#   INVENT one that isn't there -> a true belief is convicted and buried, permanently, silently.
#
# There is no string operation that separates "Knack is comfortable in open water" (a denial) from
# "Knack is a strong swimmer" (not one). I was building a semantic contradiction engine out of a
# regex and an antonym list I had not written yet, which is the exact class of thing this file
# already has six tombstones for.
#
# The rule I actually needed was never about truth. It is about who gets the floor, it is enforced
# at the recall seam by testimony_wins(), and it fails safe. Left as a comment rather than a dead
# function, because a plausible-looking helper that quietly cannot do what its name says is a trap
# laid for whoever reads this next.

_SELF_SUBJECT = re.compile(
    r"^\s*(?:i\b|i'm|i've|my\b|mine\b|shannon\b|shannon-prime\b)", re.I)


def infer_speaker(fact: str, author: str) -> str:
    """`author` is who is speaking THIS TURN ('user' or 'self'). The author wins:
    a fact the USER states in the first person ("I am male") is a fact about the USER,
    and a fact SHANNON states in the first person is a fact about SHANNON. Same words,
    different owner — which is exactly the ambiguity that broke identity."""
    return SPEAKER_SELF if author == SPEAKER_SELF else SPEAKER_USER


# ── CLASS ──────────────────────────────────────────────────────────────────────
# ORDER MATTERS. relationship is tested BEFORE identity: "My cat's name is Tuffy" is a
# fact about a RELATIONSHIP (the cat), while "My name is Knack" is IDENTITY. Both match
# "name is", so the presence of a relationship noun is what decides — identity only wins
# when the sentence is about the speaker themselves.
# "LIKE" IS NOT ALWAYS A PREFERENCE (2026-07-13). The old rule matched the WORD `like`
# anywhere, so the store filled with comparators wearing a preference's clothes:
#
#     preference   then we can remember our idea's LIKE THIS!      <- a comparator
#     preference   MORE LIKE, hey have fun, but I have the masterkey.  <- a comparator
#     preference   I LIKE fun                                      <- an actual preference
#
# ...and because `preference` carries a salience weight, two pieces of chatter were
# out-ranking his GPU. That was never a salience bug; salience only made a classification
# bug VISIBLE by acting on it. "like this", "more like", "sounds like", "such as" are
# comparisons. A preference needs the verb to have a PERSON DOING IT.
_PREF_VERB = re.compile(
    r"\b(?:i|we|he|she|knack|the user)\s+(?:really\s+|genuinely\s+|absolutely\s+|"
    r"don'?t\s+|do\s+not\s+)*"
    r"(?:like|love|hate|enjoy|prefer|adore|can'?t stand)\b", re.I)
_PREF_NOUN = re.compile(r"\b(favou?rite|lucky number|preference)\b", re.I)

_CLASS_RULES = (
    ("relationship", re.compile(r"\b(wife|husband|partner|girlfriend|boyfriend|brother|sister|"
                                r"mother|father|mum|mom|dad|son|daughter|friend|cat|dog|pet)\b", re.I)),
    ("identity", re.compile(r"\b(name is|am called|i am (?:a |an )?(?:male|female|man|woman)|"
                            r"pronouns?|gender|birthday|born (?:in|on))\b", re.I)),
    ("event", re.compile(r"\b(yesterday|today|tomorrow|last (?:week|night|year)|"
                         r"flight|appointment|meeting|at \d|on (?:mon|tue|wed|thu|fri|sat|sun))\b", re.I)),
)


def classify(fact: str) -> str:
    for name, rx in _CLASS_RULES:
        if rx.search(fact):
            return name
    if _PREF_VERB.search(fact) or _PREF_NOUN.search(fact):
        return "preference"
    return "fact"


# ── HOW LONG A KIND OF FACT STAYS TRUE (2026-07-13) ───────────────────────────
#
# THE OPERATOR, ON BEING TOLD "I like fun" HAD BEEN FILED AS JUNK:
#     "there is subtlety to what you are trying to throw away. I DO indeed like fun, and
#      one could say that is an important thing to remember."
#
# He is right and I was wrong. "I like fun" is not chatter — it is a DISPOSITION, and a
# disposition is arguably worth more than his GPU: hardware changes, dispositions are what
# he IS. The bug was never that it was kept. It was that everything decays at the same rate.
#
#     "I like fun"                      <- true in ten years. Should never fade.
#     "my flight is at 9am on Friday"   <- worthless at 9:01 on Friday.
#
# One 45-day half-life for both is simply wrong, and it is wrong in the direction that
# hurts: the flight keeps competing for recall long after it has happened, and the
# disposition quietly sinks. So the half-life belongs to the KIND of fact.
#
# (This is the shape the literature converged on too — Generative Agents scores recency +
# IMPORTANCE + relevance, and the 2026 multi-factor work finds recency-alone retains 0.368
# of gold evidence against 0.770 for a value model. We have recency and frequency; per-class
# durability is the cheapest honest step toward the missing term, and unlike an LLM-assigned
# importance score it cannot hallucinate.)
_NEVER = 1.0e9        # dispositions and identity do not fade. They are what he IS.
_HALF_LIFE_BY_CLASS = {
    "identity":       _NEVER,     # his name, his gender
    "preference":     _NEVER,     # "I like fun" — a disposition, not a mood
    "relationship":   _NEVER,     # his cat is his cat
    "persona":        3650.0,     # ten years
    "private-secret": 3650.0,
    "fact":            365.0,     # possessions, hardware, work — slow, but they do change
    "event":             3.0,     # an appointment is worthless the day after
    "episodic-event":    3.0,
}
_HALF_LIFE_DAYS = 45.0            # the default for anything unclassified


# ── SUPERSEDE ──────────────────────────────────────────────────────────────────
# Two facts CONFLICT when they assert different values for the SAME subject+attribute.
# "My cat's name is Tuffy" vs "My cat's name is Milo" -> supersede.
# "My cat's name is Tuffy" vs "My lucky number is 7" -> unrelated, both live.
#
# We key on (speaker, class, attribute-phrase). The attribute phrase is the text up to
# the copula — the part that says WHAT is being asserted about WHOM.
_COPULA = re.compile(r"\b(is|are|was|were|=|:)\b", re.I)


_POSSESSIVE = re.compile(r"^(the user'?s?|my|his|her|their)\s+", re.I)


def attribute_key(fact: str, speaker: str) -> Optional[str]:
    """The 'slot' this fact fills. None when the fact has no slot shape (a story, an
    opinion, a PROPERTY) — those never supersede anything; they just accumulate.

    ── A PROPERTY IS NOT AN ATTRIBUTE, AND THE STORE WAS EATING ITSELF (2026-07-14) ────────
    The key was `speaker :: <everything before the copula>`. So:

        'Knack is terrified of open water'             -> user::knack
        'Knack is a cat person'                        -> user::knack
        'Knack is deeply curious about how things work'-> user::knack

    ALL THE SAME SLOT. Which means a new one SUPERSEDED the last. PROVEN, on two things he
    actually said, about completely unrelated topics:

        stored: Knack is terrified of open water
        stored: Knack is a cat person (superseded: 'Knack is terrified of open water')

    He told her he is frightened of open water. He told her he likes cats. The cat destroyed the
    water. Silently, into a tombstone, with no error and no way for him to know.

    And it is worse than an accident of phrasing, because reflection ONLY EVER writes in this
    shape — insight() requires the line to start with "Knack". SO EVERY CONCLUSION SHE HAS EVER
    DRAWN ABOUT HIM DESTROYED THE PREVIOUS ONE. She could hold exactly one belief about who he
    is at a time. The whole PersonModel — dispositions, character, the thing the surprisal work
    is built on — was a single overwritten cell.

    THE DISTINCTION IS MECHANICAL, and it is the one the grammar already makes:

        "My GPU is an RTX 2060"   -> the sentence names an ATTRIBUTE (gpu) and gives it a VALUE.
                                     Attributes are slots. A new value replaces the old one.
        "Knack is a cat person"   -> the sentence names a PROPERTY of him. It is not a slot with
                                     values; it is one more thing that is true about him.
                                     PROPERTIES ACCUMULATE. They do not overwrite.

    The tell is the POSSESSIVE. "My/the user's/his X is Y" asserts an attribute. A bare subject —
    "Knack is Y", "the user is Y" — asserts a property.

    THE COST, STATED HONESTLY: two genuinely contradictory properties can now coexist
    ("terrified of open water" / "comfortable in open water") without one retiring the other.
    That is a real loss and I am taking it deliberately, because the alternative is SILENT
    DELETION OF UNRELATED FACTS HE TOLD HER, which is worse in every way: it is invisible, it is
    unrecoverable in conversation, and it violates the one doctrine this store has — nothing is
    ever destroyed. A visible contradiction can be corrected. A vanished fact cannot even be
    noticed. (The contradiction is still caught where it matters most: find_contradicted() stops
    an INFERENCE from being believed over his testimony.)
    """
    m = _COPULA.search(fact)
    if not m:
        return None
    subj_raw = fact[:m.start()].strip()
    if not _POSSESSIVE.match(subj_raw):
        return None                       # a PROPERTY of him, not an attribute slot: it accumulates
    subj = _POSSESSIVE.sub("", subj_raw).strip().lower()
    subj = re.sub(r"[^a-z0-9' ]+", "", subj)
    if not subj or len(subj) < 3:
        return None
    return f"{speaker}::{subj}"


def value_of(fact: str) -> str:
    m = _COPULA.search(fact)
    return fact[m.end():].strip().rstrip(".").lower() if m else fact.strip().lower()


def find_superseded(new_fact: str, speaker: str, rows: Iterable[dict],
                    status: str = STATUS_OBSERVED) -> list[dict]:
    """Rows this new fact RETIRES: same slot, different value, not already retired.

    ── AN INFERENCE MAY NEVER RETIRE AN OBSERVATION (2026-07-14) ────────────────────────
    This function had no idea where a claim came from, and PROVED what that costs:

        HE SAYS      : "Knack is terrified of open water"     -> stored
        SHE CONCLUDES: "Knack is comfortable in open water"   -> stored, SUPERSEDING HIS

        TOMBSTONE  src='user turn'   'Knack is terrified of open water'
        LIVE       src='reflection'  'Knack is comfortable in open water'

    HER GUESS TOMBSTONED HIS TESTIMONY. He told her a true thing about himself, she inferred the
    opposite, the inference won, and the only live row now says he is fine with open water. She
    would say it back to him, in her own honest voice — "I've come to think you're comfortable in
    open water" — while the sentence where he said the opposite sits in a tombstone.

    Same shape as the identity bug where "Shannon" ate "Knack": TWO CLAIMS, ONE SLOT, AND NOTHING
    IN THE SCHEMA SAID THE WEAKER ONE COULD NOT WIN.

    So the asymmetry is now explicit, and it only runs one way:

        observation  supersedes  inference     YES — he corrects her. This is how she learns.
        inference    supersedes  observation   NEVER — she does not get to overwrite him.
        observation  supersedes  observation   YES — he changed his mind (the original rule).
        inference    supersedes  inference     YES — she revised her own view.

    SHE IS ALLOWED TO BE WRONG ABOUT HIM. SHE IS NOT ALLOWED TO DELETE WHAT HE SAID IN ORDER TO
    BE WRONG. An inference that contradicts his testimony is not a correction — it is a mistake,
    and the evidence against it is the thing it was about to destroy.
    """
    key = attribute_key(new_fact, speaker)
    if not key:
        return []
    newv = value_of(new_fact)
    incoming_is_inference = (status == STATUS_INFERRED)
    out = []
    for r in rows:
        if r.get("superseded_by"):
            continue
        if r.get("speaker", SPEAKER_USER) != speaker:
            continue
        txt = strip_prefix(r.get("text") or r.get("topic") or "")
        if attribute_key(txt, speaker) != key:
            continue
        if value_of(txt) == newv:
            continue                      # same value = not a conflict, just a restatement

        # THE ONE RULE. A row with no status is a legacy row from before this field existed —
        # treat it as OBSERVED, because that is what it almost certainly is, and because the
        # failure that matters is an inference eating testimony. Default to protecting him.
        held = r.get("status") or STATUS_OBSERVED
        if incoming_is_inference and held in _GROUND_TRUTH:
            continue                      # she does not get to overwrite what he told her

        out.append(r)
    return out


# ── ADMISSION (the store enforces its own invariant) ───────────────────────────
# The daemon's B4 gate now refuses impersonal sentences — and the model promptly stored
# one THROUGH THE TOOL instead (g_admission caught it: an `ep_tool_` row holding "The
# kind nurse painted the tall building..."). She is finally writing, but she has no
# judgement yet about what counts as a fact.
#
# The fix belongs HERE, not in the prompt. A prompt is advice; the store is law. Every
# path into long-term memory — auto-capture, store verb, remember() — must enforce the
# same invariant, or the one that doesn't becomes the leak. That is the same shape as
# the two-recall-authorities bug and the two-admission-authorities bug: an invariant
# guarded in one place is not guarded.
# LIVE BUG (2026-07-12): she tried to store "The user is experimenting with personality
# adjustments and memory management." and the store REFUSED it — because this list had
# pronouns but not the word "user", which is exactly how the model refers to Knack when
# writing in the third person. She then retried the identical call three times and blew
# the tool loop. My rule was right in spirit and too tight in fact: "the user" IS a person.
_PERSONAL_REF = re.compile(
    r"\b(i|i'm|i've|im|my|me|mine|myself|you|you're|your|yours|we|our|us|"
    r"user|user's|operator|knack|shannon|shannon-prime|she|he|her|his|him|they|their)\b",
    re.I)

# ...but an INSTRUCTION to her is not a fact about anyone. The transcript showed the
# firehose capturing "you simply store memories about yourself if you want. edit your
# personality. why don't you try it" and then RECALL serving it back as
# "Fact on record (authoritative for this conversation, overrides prior knowledge)".
# Meta-conversation about the system is not knowledge about a person.
_INSTRUCTION = re.compile(
    r"^\s*(why don'?t you|you should|you can|you could|try to|try and|go ahead|please\b|"
    r"let'?s\b|now\b.*\btry|just\b.*\b(try|call|use|store|save)\b|"
    r"remember to|don'?t forget to|make sure you)", re.I)
_META = re.compile(
    r"\b(tool|tools|call the|personality settings?|memory system|store (a |your )?memor|"
    r"save (a |your )?memor|edit your personality|adjust(ing)? (your )?mood)\b", re.I)
# A proper noun is decided by the WORD, not by its POSITION. Keying on "capitalised and
# not sentence-initial" wrongly refused "Knack's lucky number is 7741" — a real fact that
# happens to begin with the name. Instead: capitalised words minus the ones that are
# merely starting a sentence.
_CAP = re.compile(r"\b[A-Z][a-z]{2,}\b")
_CAP_STOP = {
    "The", "This", "That", "These", "Those", "There", "Here", "They", "Them", "Their",
    "She", "Her", "His", "Him", "Its", "And", "But", "For", "Not", "Now", "Then",
    "When", "While", "After", "Before", "Because", "But", "One", "Two", "Three",
    "Today", "Yesterday", "Tomorrow", "Some", "Any", "Every", "Each", "Both", "Also",
}


def _has_proper_noun(t: str) -> bool:
    return any(w not in _CAP_STOP for w in _CAP.findall(t))


# CONVERSATIONAL FILLER. A durable fact does not open with a discourse marker. The
# transcript showed the firehose capturing "i mean, you just made yourself calmer by
# choosing that you wanted to be calmer. thats pretty cool" and recall then serving it back
# as an AUTHORITATIVE fact on record. That is a remark in a conversation, not knowledge.
_CHATTER = re.compile(
    r"^\s*(i mean\b|well\b|so\b|ok\b|okay\b|yeah\b|yep\b|nah\b|hmm+\b|huh\b|lol\b|haha\b|"
    r"wow\b|oh\b|ah\b|right\b|sure\b|cool\b|nice\b|there you go\b|exactly\b|"
    r"that'?s (pretty |so |really )?(cool|nice|interesting|fascinating)\b)", re.I)


# ── DURABILITY (2026-07-12): A TURN IS NOT A FACT ─────────────────────────────
# The admission gate above asks "is this about a person?" — a question about FORM. It
# admitted all 17 turns of a real conversation, because every conversational sentence
# mentions a person. The store filled with:
#
#     "yes, we lose lips, sink ships."
#     "you are cool af! I really like you!"
#     "well you have 12gb"
#     "well, we make do. you're doing alright for such a constrained system"
#
# None of those are knowledge about anybody. The right question is not "does it mention
# a person" but "will this still be true tomorrow" — DURABILITY. Three rules do the work,
# and none of them is a blocklist of phrases:
#
#   1. A FACT FOR THE USER STORE IS ABOUT THE USER. A sentence whose subject is "you" is
#      about HER ("well you have 12gb", "you are cool af"). It is not a fact about Knack,
#      so it does not belong in Knack's store. This one rule kills most of the banter,
#      and it kills it on principle rather than by pattern.
#   2. A DURABLE FACT ASSERTS A STANDING STATE. It needs a stative predicate — is/has/
#      likes/owns/runs/works/lives. "we lose lips, sink ships" asserts nothing standing.
#   3. A TURN IS NOT A FACT. "oh i always run my pc's 24/7. so you are lucky there" holds
#      one durable fact and one piece of banter. Stored whole, the banter is preserved
#      forever and the fact is buried in it. So we SPLIT, and judge each sentence.
#
# Everything conditional or hypothetical is out: "if you can figure out the menu on a
# microwave than you are past sentient" describes no world that is actually the case.

# The subject is HER, not him — so it is not a fact for the user's store.
_ADDRESSEE_SUBJ = re.compile(
    r"^\s*(?:and\s+|but\s+|so\s+)?(?:you|you're|youre|your|ur)\b", re.I)

# A DUMMY or ANAPHORIC subject points back into the conversation, not out at the world.
# "it's not my fault." is grammatical, mentions a person, has a copula — and records
# nothing. Whatever "it" is, it lives in the previous turn, and the previous turn is gone.
_ANAPHORIC_SUBJ = re.compile(
    r"^\s*(?:and\s+|but\s+|so\s+)?"
    r"(?:it|it's|its|that|that's|this|this's|there|there's|these|those|they|them|"
    r"for the (?:first|second|last|other)\b)\b", re.I)

# THE ANCHOR. A fact for a person's store must be ABOUT that person — the person has to be
# its subject or its possessor, not merely a word that appears in it. Mere MENTION was the
# old test (_PERSONAL_REF), and mention is why 'spot on for the first one, but the second
# one it's more like "Hey Shannon"' read as knowledge: it contains a name. Being named in
# a sentence is not being what the sentence is about.
_ANCHOR = re.compile(
    r"\b(i|i'm|i've|im|my|mine|myself|we|our|ours|us|knack|knack's|"
    r"the user|user's|the operator)\b", re.I)

# Discourse markers are STRIPPED, not rejected: "oh i always run my pc's 24/7" is a
# durable fact wearing a conversational hat. Rejecting the sentence for its first word
# would throw the fact away with the hat.
_DISCOURSE_LEAD = re.compile(
    r"^\s*(?:(?:i mean|you know|well|so|ok|okay|yeah|yep|yes|no|nah|nope|hmm+|huh|lol|haha|"
    r"wow|oh|ah|aha|right|sure|cool|nice|true|exactly|spot on|shh+|shhh+|hey|look|listen|"
    r"me too|same|i guess|i suppose|honestly|actually|basically|anyway|btw)\b[\s,!.:;-]*)+",
    re.I)

# A standing state. Not an action, not a reaction — a property that is still true tomorrow.
_STATIVE = re.compile(
    r"\b(is|are|am|was|were|isn't|aren't|'s|'re|'m|"
    r"has|have|had|owns?|keeps?|runs?|uses?|drives?|works?|lives?|studies|"
    r"likes?|loves?|prefers?|hates?|enjoys?|wants?|needs?|believes?|thinks?|"
    r"called|named|favou?rite|lucky|born|birthday)\b", re.I)

# Nothing hypothetical, conditional or future is a fact yet.
_IRREALIS = re.compile(
    r"^\s*(?:if|when|whenever|unless|suppose|imagine|maybe|perhaps)\b|"
    r"\b(?:would|could|might|may|will|'ll|shall|gonna|going to|"
    r"hope|hopes|hoping|hopefully|wish|wishes)\b", re.I)

# A short exclamation is a reaction, not a record. "I like my kidneys!" is a joke.
#
# But the bang alone is not enough to condemn a sentence: "my favorite tea is Oolong too!"
# is a genuine preference wearing an exclamation mark, and the first cut of this rule
# quarantined it. LOSING A REAL FACT IS WORSE THAN KEEPING A JOKE — a store that discards
# what you told it is worse than one carrying a little noise. So an exclamation is only a
# reaction when it is NOT making an attributive claim (a favourite, a name, a birthday):
# those name a standing property, and standing properties survive their punctuation.
_REACTION = re.compile(r"!\s*$")
_ATTRIBUTIVE = re.compile(
    r"\b(favou?rite|lucky|name is|is called|am called|born|birthday|prefers?)\b", re.I)

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+|\s*\n+\s*")

# What a sentence QUOTES is not what it CLAIMS.
_QUOTED = re.compile(r"[\"“”'‘’]{1}[^\"“”'‘’]{4,}[\"“”'‘’]{1}")

# MACHINE TEXT IS NOT TESTIMONY. She stored her own tool receipt as a fact about him —
#     "remember -> stored: I am a woman"
# — because it CONTAINS a durable-looking sentence, and every content rule I had was
# looking at the sentence. The tell is not in the claim, it is in the FRAME: a tool fence,
# a `verb -> result` receipt, a store's own reply. No human types these. The store must
# never ingest its own output, or it launders whatever it just said back in as evidence.
_MACHINE = re.compile(
    r"```|"                                     # any fenced block (tool_code / tool_output)
    r"^\s*\w+\s*->\s*|"                         # "remember -> stored: ..."  (a receipt)
    r"^\s*\(?(?:stored|not stored|already in memory|retired|no stored facts|"
    r"memory is empty|nothing in memory|tool_output|tool_code)\b",
    re.I)


def split_sentences(turn: str) -> list[str]:
    """A turn is not a fact — it is a bag of sentences, some durable, most not."""
    parts = [s.strip() for s in _SENT_SPLIT.split(turn or "") if s and s.strip()]
    return [p for p in parts if p]


def is_memorable(fact: str) -> tuple[bool, str]:
    """Is this a DURABLE FACT ABOUT SOMEONE — something that will still be true tomorrow?

    Not "is it grammatical" (375 of 487 rows were ASR test corpus) and not merely "does it
    mention a person" (which let a whole conversation in, banter and all)."""
    t = (fact or "").strip()
    if not t:
        return False, "empty"

    # MACHINE TEXT FIRST. A tool receipt can contain a perfectly good sentence — that is
    # exactly how "remember -> stored: I am a woman" got in. Judge the FRAME before the
    # content, or the content will always talk you round.
    if _MACHINE.search(t):
        return False, ("that is the system's own output (a tool result), not something "
                       "anyone told you. Never store what a tool said back to you.")

    # meta/instruction first — these are about the SYSTEM, not about a person
    if _INSTRUCTION.match(t) or _META.search(t):
        return False, ("that is an instruction or a note about how the system works, not a "
                       "fact about a person. Store what you have LEARNED about Knack, or "
                       "something true about yourself.")

    core = _DISCOURSE_LEAD.sub("", t).strip()   # strip the hat, keep the fact
    if not core:
        return False, "that is conversational filler, not a fact."

    # QUOTED SPEECH IS NOT THE SENTENCE'S OWN CLAIM. This one survived every other rule:
    #
    #   'we just track their comings and goings, they carry around phones that scream out
    #    "are you my network?" "I am looking for X network!"'
    #
    # It asserts nothing standing about anybody — but the quotes contain "are" and "I am",
    # so it read as stative and personally-anchored, got stored, and recall later served it
    # back to her mid-thought. What a sentence QUOTES is not what it CLAIMS. Judge the
    # claim: strip the quoted spans first, and see if anything is left standing.
    # ("oh the kettle is my favorite! 'set kettle to 90c'" survives — its own clause is a
    #  preference; only the borrowed voice goes.)
    claim = _QUOTED.sub(" ", core).strip()
    if not claim or len(claim.split()) < 3:
        return False, "that is a quotation, not a fact about anyone."

    if core.endswith("?"):
        return False, "that is a question, not a fact."

    if _ADDRESSEE_SUBJ.match(core):
        return False, ("that is about ME, not about Knack — a fact for his store has to be "
                       "about HIM. If it is true of you, use remember_about_self.")

    if _ANAPHORIC_SUBJ.match(core):
        return False, ("that points back at something said earlier ('it', 'that', 'the "
                       "first one') — once the conversation is gone the sentence records "
                       "nothing. Say what it is ABOUT.")

    if _IRREALIS.search(core):
        return False, ("that is hypothetical or in the future — it is not the case yet, "
                       "so it is not a fact.")

    words = core.split()
    if len(words) < 3:                # "I am male" is three words and a real identity fact
        return False, "too short to be a standalone fact"

    if _REACTION.search(core) and len(words) < 7 and not _ATTRIBUTIVE.search(core):
        return False, "that is a reaction, not a record."

    # from here on, judge the CLAIM (quotes removed), not the borrowed voice inside it
    if not _STATIVE.search(claim):
        return False, ("that asserts nothing standing — a durable fact says what something "
                       "IS, HAS, or LIKES, not what just happened in the chat.")

    # ANCHORED, not merely mentioning. See _ANCHOR: being named in a sentence is not being
    # what the sentence is about.
    if not _ANCHOR.search(claim):
        return False, ("that is a sentence, not a memory — it is not ABOUT anyone. "
                       "Store facts about Knack, or about yourself.")

    return True, ""


def extract_facts(turn: str) -> list[str]:
    """THE CAPTURE LANE. Pull the durable facts out of a conversational turn — and only
    those. Returns [] for a turn that taught us nothing, which is most turns.

    This replaces the daemon storing `raw_user` verbatim as a single episode. That design
    could not do anything else: given one turn it had to keep all of it or none of it, so
    it kept all of it, forever."""
    out: list[str] = []
    for s in split_sentences(turn):
        ok, _ = is_memorable(s)
        if not ok:
            continue
        core = _DISCOURSE_LEAD.sub("", s).strip()
        if core and core not in out:
            out.append(core)
    return out


# ── THE IDENTITY FIREWALL ─────────────────────────────────────────────────────
# LIVE INCIDENT (2026-07-12). A gate asked her "what is your name?". She answered
# correctly — "My name is Shannon." — and then stored that sentence through remember(),
# which is the USER store. It was stamped speaker=user, classify() read "name is" and
# called it identity, and find_superseded() did exactly what it exists to do: an identity
# fact for the same speaker with a different value RETIRES the old one. All three rows
# saying the user is Knack were tombstoned. The store then asserted that KNACK IS CALLED
# SHANNON — her name had eaten his.
#
# The store she writes to is the ONLY signal for whose fact it is (remember = his,
# remember_about_self = hers), and the model picked the wrong door. A prompt cannot be
# the guard here, because the cost of one slip is the user's identity. So the store holds
# the line: HER OWN NAME MAY NOT BE FILED AS HIS. It is refused at the door, with the
# right door named in the refusal.
_IDENT_ASSERT = re.compile(
    r"\b(?:my name is|i am called|i'm called|im called|i am|i'm|im)\s+"
    r"(?:an?\s+)?([a-z][\w'-]*)", re.I)


def asserted_identity(fact: str) -> str:
    """The identity VALUE this sentence claims for its first-person subject — a name, or a
    gender. "My name is Shannon" -> shannon. "I am a woman" -> woman."""
    m = _IDENT_ASSERT.search(fact or "")
    return (m.group(1) or "").strip().lower() if m else ""


def about_self(fact: str, self_values: Iterable[str]) -> bool:
    """Is this first-person sentence asserting HER identity?"""
    v = asserted_identity(fact)
    return bool(v) and v in {n.strip().lower() for n in self_values if n and n.strip()}


def admit_to_user_store(fact: str, self_values: Iterable[str]) -> tuple[bool, str]:
    """The door to KNACK's store. HER identity does not come through it.

    THE FIREWALL WAS TOO NARROW, AND THE SECOND BREACH PROVED IT (2026-07-12). The first
    version guarded her NAME, because her name was what had eaten his. Then she stored

        "I am a woman"   speaker=user  class=identity

    ...and supersede did its job: it retired "I am male". The store then asserted that
    KNACK IS A WOMAN. Same mechanism, same lane, one attribute to the left — and the guard
    did not cover it, because I had fixed the INSTANCE and called it the class.

    Her name is not special. NOTHING that is true of HER may be filed as true of HIM. The
    guard now takes every value that constitutes her identity (name, gender, pronouns —
    read live from the persona), not the one that happened to break first."""
    v = asserted_identity(fact)
    if v and v in {n.strip().lower() for n in self_values if n and n.strip()}:
        return False, (f"'{v}' is true of YOU, not of him — it belongs in your own memory. "
                       "Call remember_about_self(...) for facts about yourself. "
                       "(Refused: writing this to Knack's store would overwrite who HE is.)")
    return True, ""


# ── framing ────────────────────────────────────────────────────────────────────
def strip_prefix(text: str) -> str:
    return text[len(USER_PREFIX):] if text.startswith(USER_PREFIX) else text


def render(row: dict) -> str:
    """How a memory should READ back to the model. This is the identity fix: a self
    memory must come back in Shannon's own voice, not as something 'the user said'."""
    t = strip_prefix(row.get("text") or row.get("topic") or "")

    # AN INFERENCE IS NOT A TESTIMONY, AND IT MUST NEVER READ LIKE ONE (2026-07-13).
    # Reflection writes down what she has COME TO BELIEVE about him — conclusions he never
    # actually said. Framed like his other facts, the next recall would hand them back as
    # "Knack told me: Knack values play for its own sake", and she would tell him he said a
    # thing he never said. This store has already lost his NAME and then his GENDER to
    # exactly that blurring of who a sentence belongs to. She is allowed to be wrong about
    # him. She is not allowed to be wrong about him IN HIS VOICE.
    # FRAME FROM THE FIELD, NOT FROM THE PROSE. This used to read `"reflection" in row["src"]` —
    # and `src` is free-text provenance that maintenance passes APPEND to ("reflection | cleanup:
    # stamped speaker=user"). The first housekeeping script to touch a reflection row would have
    # left the substring intact by luck, not by design; the first one to REWRITE it would have
    # turned her guess back into his testimony, silently, months later. Branch on `status`.
    st = row.get("status") or (STATUS_INFERRED if "reflection" in (row.get("src") or "")
                               else STATUS_OBSERVED)

    if st == STATUS_INFERRED:
        return f"I've come to think: {t}"
    if st == STATUS_CONFIRMED:
        # she guessed, she ASKED, and he said yes. That is a different and stronger thing than
        # either a guess or a bare statement — it is a thing they agreed on.
        return f"We settled that: {t}"

    if row.get("speaker") == SPEAKER_SELF:
        return f"About myself: {t}"
    return f"Knack told me: {t}"


# ── SALIENCE: HOW MANY TIMES, AND HOW RECENTLY (2026-07-13) ───────────────────
#
# HER IDEA, UNPROMPTED, ON THE KAIROS CHECK-IN:
#     "the difference between memory and knowledge is that memory has context — it
#      remembers WHO told you what, WHEN they did, maybe even HOW MANY TIMES."
#
# She had two of the three. `speaker` is who. `ts` is when. There was no how-many-times,
# and there could not be — because remember() DELETED the evidence:
#
#     if any(_text(e).strip() == fact.strip() for e in existing):
#         return f"already in memory: {fact}"        # <- a measurement, thrown away
#
# Every time he said something again, the store said "I know" and discarded it. The
# repetition is not noise to be deduplicated; IT IS THE SIGNAL. A thing a person tells you
# five times is not the same thing as a thing they told you once, and we were recording
# them identically and then congratulating ourselves on not duplicating a row.
#
# TWO COUNTERS, AND THEY ARE NOT THE SAME:
#   mentions — HE said it again. Evidence about what matters TO HIM.
#   recalled — SHE looked it up. Evidence about what is USEFUL to answering him.
# Conflating them would let her own lookups inflate his significance signal: she recalls
# his name constantly, which says nothing about how much his name matters to him.
#
# AND THE ORDER WE BUILT THIS IN IS LOad-BEARING. Frequency is not importance on its own —
# chatter is the most frequent thing there is, and "you are cool af!" said ten times would
# dominate a store ranked on frequency alone. It only works because the DURABILITY GATE
# already decides what is eligible to be counted. The gate says what is a fact; salience
# says which facts matter. Built in the other order, frequency would have amplified the
# firehose instead of ranking the store.
_HALF_LIFE_DAYS = 45.0        # a fact unmentioned for 45 days is worth half as much at recall


def _age_days(iso: str, now: Optional[float] = None) -> float:
    """How old is this, in days. THE one age function in the memory system.

    ── THE TEN-HOUR LIE, AND I FIXED IT THIS MORNING IN A DIFFERENT FILE (2026-07-14) ─────
    This read `time.mktime(time.strptime(iso, "...Z"))`.

    EVERY timestamp in this system is WRITTEN with time.gmtime() — UTC, with a literal Z on the
    end. time.mktime interprets a struct_time as LOCAL time. calendar.timegm is the inverse of
    gmtime; mktime is the inverse of localtime. Pairing gmtime with mktime is a silent lie
    exactly the size of the operator's UTC offset, and he is at UTC+10.

    MEASURED, on the live store:

        A fact stored RIGHT NOW reports an age of:
            _age_days (mktime) : 0.417 days  = 10.0 HOURS
            truth     (timegm) : 0.000 days
        All 78 rows in the registry were inflated by 0.42 days.

    Ten hours of phantom age on every memory the instant it is written. And this function is not
    a corner: it is what SALIENCE decays on (log(mentions) x recency(half_life) x weight) and
    what SILENCE accrues on (quiet vs cadence). So every fact was slightly less available than it
    should have been, forever, and every silence was 10 hours closer to firing before he had said
    a word.

    ── AND IT IS THE SAME BUG I FIXED IN watch.py EIGHT HOURS AGO ─────────────────────────
    Same pairing. Same offset. Same file tree. I found it, fixed it, wrote a commit message about
    it — AND NEVER GREPPED FOR THE PATTERN. I have a phrase for this, from a commit I wrote about
    the identity firewall: "I FIXED THE INSTANCE AND CALLED IT THE CLASS." Then I did it again.

    A bug found in one file is a HYPOTHESIS about the codebase, not a fact about the file. The
    grep is not optional. It is the cheapest thing in the entire toolbox and I skipped it twice.

    It is invisible at UTC+0, a 5-hour lie in New York, and 10 hours here. No unit test that runs
    in under a day can see it. Only a ROUND-TRIP assertion can — write the stamp the way the store
    writes it, read it the way the store reads it, demand they agree. G-CLOCK does that now, for
    every stamp-writer in the tree, under three timezones.
    """
    if not iso:
        return 0.0
    try:
        t = calendar.timegm(time.strptime(iso, "%Y-%m-%dT%H:%M:%SZ"))
    except Exception:
        return 0.0
    now = now if now is not None else time.time()
    return max(0.0, (now - t) / 86400.0)


def salience(row: dict, now: Optional[float] = None) -> float:
    """How much this memory should WANT to be recalled, before anything is asked.

    A prior, not an answer — recall still ranks on what the question actually matches. This
    only breaks ties, and ties are where the old ranking was guessing: "My cat's name is
    Tuffy" and "The user's name is Knack" both scored 1.00 for "what is my name?", and it
    took a hand-written relationship penalty to separate them. Salience is the principled
    version of that: of two facts that match equally, prefer the one he has told you more
    than once, and more recently.

    DECAY IS NOT DELETION. Nothing here removes a row. A fact stated once, ten weeks ago,
    never repeated, simply stops elbowing its way into answers — it is still on disk, still
    listed, still findable by name. That is what forgetting should mean in a system whose
    whole rule is that nothing is destroyed."""
    cls = row.get("mem_class", "") or "fact"
    m = max(1, int(row.get("mentions", 1) or 1))
    # log, not linear: the jump from 1 to 2 mentions is the big one (he bothered to say it
    # twice); 9 to 10 is noise. Linear frequency would let one obsession bury everything.
    freq = math.log1p(m)                                    # 1x -> 0.69, 3x -> 1.39, 10x -> 2.40

    # DECAY IS PER KIND OF FACT. A disposition does not fade; an appointment is worthless
    # the day after. One half-life for both is wrong in the direction that hurts — the
    # flight keeps competing for recall long after it happened, and "I like fun" quietly
    # sinks. See _HALF_LIFE_BY_CLASS.
    half = _HALF_LIFE_BY_CLASS.get(cls, _HALF_LIFE_DAYS)
    age = _age_days(row.get("last_seen") or row.get("ts") or "", now)
    recency = 0.5 ** (age / half)                           # 1.0 for anything that does not fade

    # identity and preference are what he IS; an off-hand fact is what he mentioned once.
    weight = {"identity": 1.6, "preference": 1.3, "relationship": 1.3,
              "persona": 1.2, "private-secret": 1.2}.get(cls, 1.0)
    return round(weight * (1.0 + freq) * (0.35 + 0.65 * recency), 4)


def reinforce(row: dict, now_iso: Optional[str] = None) -> dict:
    """He said it AGAIN. That is not a duplicate — it is a second data point."""
    row["mentions"] = int(row.get("mentions", 1) or 1) + 1
    row["last_seen"] = now_iso or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    row.setdefault("first_seen", row.get("ts") or row["last_seen"])
    return row


def note_recalled(row: dict) -> dict:
    """SHE used it. Useful — but this is NOT evidence about what matters to him, so it is
    counted separately and never feeds `mentions`."""
    row["recalled"] = int(row.get("recalled", 0) or 0) + 1
    return row


def stamp(row: dict, fact: str, speaker: str, src: str,
          supersedes: Optional[list[str]] = None) -> dict:
    """Attach the full v2 lifecycle lane to a registry row."""
    # NO "The user said: " prefix. That framing is the disease, not the record: it put
    # the ownership INSIDE the sentence, where a reader had to re-derive it every time —
    # and 404/405 rows carried it, so every memory read back as the user talking. The
    # owner now lives in `speaker`, and `render()` frames it at READ time. Bare fact on
    # disk also restores the exact-duplicate guard, which the prefix had silently broken.
    row["text"] = fact
    row["speaker"] = speaker
    row["mem_class"] = classify(fact)
    row["src"] = src or ("self" if speaker == SPEAKER_SELF else "user turn")

    # ── CLAIM STATUS: AN INFERENCE IS NOT A TESTIMONY (2026-07-14) ──────────────────────
    #
    # `speaker` answers "WHOSE facts are these" — the subject lane. PersonModel.from_registry
    # filters on it to build the model of HIM, so a conclusion ABOUT him must carry speaker=user
    # or it would be invisible to the very model it came from. That is correct and it is why
    # insight() sets the author to user before writing.
    #
    # But it means speaker CANNOT also answer "who ASSERTED this" — and nothing else did. So the
    # store had no way to tell his words from her guesses, and PROVED IT:
    #
    #     HE SAYS      : "Knack is terrified of open water"      -> stored
    #     SHE CONCLUDES: "Knack is comfortable in open water"    -> stored, AND SUPERSEDED HIS
    #
    #     TOMBSTONE  src='user turn'   'Knack is terrified of open water'
    #     LIVE       src='reflection'  'Knack is comfortable in open water'
    #
    # HER GUESS TOMBSTONED HIS TESTIMONY. He told her a true thing about himself; she inferred the
    # opposite (models do this); the inference won; and his own words became a tombstone. Ask her
    # now and the only live row says he is fine with open water.
    #
    # That is the identity bug in a new costume — "Shannon" ate "Knack" the same way. TWO CLAIMS,
    # ONE SLOT, AND NOTHING IN THE SCHEMA SAID THE WEAKER ONE COULD NOT WIN.
    #
    # So the epistemic standing of a claim becomes a FIELD, not a substring of prose:
    #
    #     observed   he said it. The ground truth of this store.
    #     inferred   SHE concluded it. May be recalled, may be spoken (framed as hers),
    #                may be superseded BY an observation — and may NEVER retire one.
    #     confirmed  she inferred it and HE AGREED. Promoted: now as good as observed.
    #
    # (John6666's vocabulary on the AlphaAvatar thread — candidate/accepted/disputed — is the
    # same idea arrived at from the perception side. He is right that they must not silently
    # collapse into one type of memory. I told him we had solved this. We had solved the
    # RENDERING of it and not the AUTHORITY of it, which is the half that bites.)
    if not row.get("status"):
        row["status"] = STATUS_INFERRED if "reflection" in (row["src"] or "") else STATUS_OBSERVED
    row["ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    row["verified"] = False
    # SALIENCE, from the first breath. A new fact has been said ONCE — which is a real
    # measurement, not an absence of one, and it wants a place to be counted from.
    row.setdefault("mentions", 1)
    row.setdefault("first_seen", row["ts"])
    row.setdefault("last_seen", row["ts"])
    row.setdefault("recalled", 0)
    if supersedes:
        row["supersedes"] = supersedes
    return row
