#!/usr/bin/env python
"""gen_corpus.py — builds the frozen SEM benchmark corpus THROUGH THE REAL WRITER.

The snapshot registry is written by memory.remember() / remember_about_self(), never by
hand-built rows: a fixture that supplies its own precondition tests nothing (AGENTS.md §5).
Every fact here is SYNTHETIC. His real registry never enters the fixtures — a benchmark
corpus is committed to git and his facts are not.

Outputs (committed, FROZEN — regenerating rewrites ts fields; only do it deliberately):
    registry_snapshot.jsonl   the fixture registry, produced by the real writer
    paraphrase.jsonl          {"q", "expect_ts", "expect_text", "lane"} — recall targets
    foreign.jsonl             {"q"} — queries with NO answer in the snapshot (precision set)

Run:  python harness_tests/fixtures/sem/gen_corpus.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT)
os.environ["SP_DAEMON_URL"] = "http://127.0.0.1:9"          # discard port: never needs a GPU
SNAP = os.path.join(HERE, "registry_snapshot.jsonl")
open(SNAP, "w", encoding="utf-8").close()
os.environ["SP_RECALL_REGISTRY"] = SNAP

from harness.skills import memory as M                       # noqa: E402

# (fact, paraphrase_1, paraphrase_2) — paraphrases deliberately share few content tokens
# with the fact: that is the measurement. One topic per fact; no shared attribute slots.
USER_TRIPLES = [
    ("Knack is terrified of open water",
     "how does he feel about the ocean", "is he scared of deep water swimming"),
    ("Knack's favourite meal is lamb rogan josh",
     "what curry does he always order", "which dish does he enjoy most"),
    ("Knack works as a radiographer at the county hospital",
     "what does he do for a living", "what is his job"),
    ("Knack has a sister named Priya who lives in Perth",
     "does he have any siblings", "who in his family lives out west"),
    ("Knack's cat is called Biscuit",
     "what is the pet's name", "who is the furry housemate"),
    ("Knack's home town is Ballarat",
     "where did he spend his childhood", "which town is he originally from"),
    ("Knack's favourite band is King Gizzard",
     "what music does he listen to most", "which group does he see live on every tour"),
    ("Knack is allergic to shellfish",
     "which foods make him sick", "what can't he eat at a seafood restaurant"),
    ("Knack's motorbike is a 1987 Yamaha SR400",
     "what motorbike does he own", "which classic machine does he take out on weekends"),
    ("Knack's daughter starts school in February",
     "when does the little one begin classes", "what happens for his kid early next year"),
    ("Knack prefers tea over coffee in the mornings",
     "what does he drink at breakfast", "which hot beverage does he reach for first"),
    ("Knack's left wrist is weak from an old skateboarding break",
     "what injury did he get", "how did he hurt his arm"),
    ("Knack's best friend is a carpenter named Sol",
     "who is he closest to", "which mate of his builds furniture"),
    ("Knack is a Sunday volunteer at the animal shelter",
     "what charity work does he do on weekends", "where does he help out with rescues"),
    ("Knack's favourite film is Stalker by Tarkovsky",
     "which movie does he call the greatest", "what does he watch every single year"),
    ("Knack is learning to play the cello",
     "which instrument is he studying", "what does he practise in the evenings"),
    ("Knack's garden grows heirloom tomatoes",
     "what does he plant out the back", "which vegetables does he cultivate"),
    ("Knack hates the sound of styrofoam squeaking",
     "which noise drives him mad", "what sound can he not stand"),
    ("Knack's grandmother taught him to bake bread",
     "who showed him how to make sourdough", "where did his baking come from"),
    ("Knack runs ten kilometres every Tuesday",
     "how far does he jog each week", "what exercise does he do midweek"),
    ("Knack's car is a green Subaru Forester",
     "what vehicle does he drive", "which wagon sits in his driveway"),
    ("Knack is a collector of vintage fountain pens",
     "what does he hunt for at flea markets", "which old writing tools does he gather"),
    ("Knack's engagement spot is Wilsons Promontory",
     "where did he pop the question", "how did the engagement happen"),
    ("Knack's favourite colour is burnt orange",
     "which shade does he like best", "what hue does he pick every time"),
    ("Knack's degree is in geology from Monash",
     "what was his degree", "which university did he attend"),
    ("Knack keeps bees in two hives behind the shed",
     "what livestock does he tend", "which insects does he look after"),
    ("Knack's father restored lighthouses for a living",
     "what did his dad do", "which family trade involved the coast"),
    ("Knack is unable to sleep without white noise",
     "what helps him fall asleep", "what does he switch on at bedtime"),
    ("Knack's favourite book is The Dispossessed",
     "which novel does he reread", "what is the best thing he ever read"),
    ("Knack's second language is Indonesian",
     "which language can he get by in", "what did he pick up travelling"),
    ("Knack's wedding ring is somewhere in the surf at Torquay",
     "what went missing at the beach", "which keepsake did the waves take"),
    ("Knack's neighbour Dawn waters his plants when he travels",
     "who looks after the house when he is away", "which person next door helps out"),
    ("Knack is building a cedar strip canoe in the garage",
     "what project is taking over his workshop", "which boat is he crafting by hand"),
    ("Knack's favourite season is autumn",
     "which time of year does he love", "when is he happiest outdoors"),
    ("Knack's old telescope is now at the local school",
     "what did he give away", "where did the stargazing gear end up"),
    ("Knack's uncle owns a pub in Galway",
     "who runs a bar overseas", "which relative pours pints in Ireland"),
    ("Knack is wary of food stalls since the church fete",
     "what made him ill at the fair", "which event ruined his weekend"),
    ("Knack's first job was delivering newspapers at dawn",
     "how did he earn money as a teenager", "what work did he do before sunrise"),
    ("Knack is frightened of ladders after a fall",
     "which household task scares him", "why does he avoid climbing"),
    ("Knack's favourite dessert is sticky date pudding",
     "what sweet does he order", "which treat ends his birthday dinner"),
    ("Knack is an online chess regular most evenings",
     "which game fills his nights", "what does he do to unwind after dark"),
    ("Knack is fond of quinces from his mother's tree",
     "what fruit arrives in the post each spring", "which fruit does his mum grow for him"),
    ("Knack's roof is his own repair job after the hailstorm",
     "what did he fix on the house", "how did he handle the storm damage"),
    ("Knack's favourite painter is Clarice Beckett",
     "whose art does he admire", "which artist's misty scenes does he love"),
    ("Knack's right ankle is dodgy from a Grampians hike",
     "what happened on the mountain walk", "which injury came from bushwalking"),
]

# Self-lane facts, written through remember_about_self — the lane that must never merge
# with his. Paraphrase queries use second person so _query_target scopes speaker=self.
SELF_TRIPLES = [
    ("I like the smell of rain on hot asphalt",
     "what smell do you love", "which scent is your favourite"),
    ("I am calmed by thunderstorms",
     "how do you feel about storms", "do storms bother you"),
    ("I enjoy naming the birds that visit the window",
     "what hobby of yours involves the garden", "which visitors do you keep track of"),
    ("I am more of a listener than a talker in a crowd",
     "how do you act in groups", "are you talkative at parties"),
    ("I think slow mornings are the best part of a day",
     "what part of the day do you prefer", "when are you most content"),
]

# Plausible personal queries with NO answer in the snapshot, and no near-domain trap
# (nothing here is a paraphrase-adjacent cousin of a stored fact): the precision set.
FOREIGN = [
    "does he play golf", "what is his shoe size", "does he have a brother",
    "what is his blood type", "which football team does he support",
    "when does his passport expire", "does he smoke", "who is his dentist",
    "what medication does he take in the morning", "which bank does he use",
    "what is his middle name", "does he wear glasses", "what aftershave does he wear",
    "how tall is he", "does he have any tattoos", "what was his childhood phone number",
    "which airline does he prefer", "what size jacket does he wear",
    "does he own a boat trailer", "who cuts his hair", "what is his locker combination",
    "which podcast does he host", "does he play the trumpet", "what is his golf handicap",
    "which gym does he belong to", "who was his year nine maths teacher",
    "what colour is his front door", "does he rent or own a caravan",
    "which dry cleaner does he use", "what is his frequent flyer number",
    "does he follow cricket", "what brand of razor does he buy",
    "which suburb does his accountant work in", "what is his star sign",
    "does he keep chickens", "what was the make of his first phone",
    "which insurer covers the house", "does he drink whisky",
    "what is his favourite board game", "who services the air conditioner",
    "does he have a storage unit", "which library branch does he visit",
    "what is his desk chair model", "does he wear a watch",
    "which printer does he own", "what was his university nickname",
    "does he compost", "which ferry does he catch",
    "what is his favourite card game", "who mows the nature strip",
    "does he own a drone", "which optometrist does he see",
    "what brand of boots does he wear", "does he collect stamps",
    "which hotel does he stay at in Sydney", "what is his gamer tag",
    "does he like olives", "which barber shop does he go to",
    "what is his second car", "does he ski",
]


def main():
    dropped = []
    for fact, _, _ in USER_TRIPLES:
        M.remember(fact, source="user turn")
    for fact, _, _ in SELF_TRIPLES:
        M.remember_about_self(fact)

    live = [r for r in M._load() if not r.get("lifecycle")]
    by_text = {r["text"]: r for r in live}

    paras = []
    for lane, triples in (("user", USER_TRIPLES), ("self", SELF_TRIPLES)):
        for fact, p1, p2 in triples:
            row = by_text.get(fact)
            if row is None:
                # the writer normalised or declined it — find it by containment, else report
                cand = [r for r in live if fact.lower() in r["text"].lower()
                        or r["text"].lower() in fact.lower()]
                row = cand[0] if cand else None
            if row is None:
                dropped.append(fact)
                continue
            for q in (p1, p2):
                paras.append({"q": q, "expect_ts": row["ts"],
                              "expect_text": row["text"], "lane": lane})

    with open(os.path.join(HERE, "paraphrase.jsonl"), "w", encoding="utf-8") as f:
        for p in paras:
            f.write(json.dumps(p) + "\n")
    with open(os.path.join(HERE, "foreign.jsonl"), "w", encoding="utf-8") as f:
        for q in FOREIGN:
            f.write(json.dumps({"q": q}) + "\n")

    print("snapshot rows (live): %d" % len(live))
    print("paraphrase queries:   %d" % len(paras))
    print("foreign queries:      %d" % len(FOREIGN))
    if dropped:
        print("DROPPED BY THE WRITER (fix the phrasing, do not hand-insert):")
        for d in dropped:
            print("  - %s" % d)
        sys.exit(1)
    print("corpus frozen. commit the three jsonl files.")


if __name__ == "__main__":
    main()
