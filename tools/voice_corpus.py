"""voice_corpus.py — P1 conversational corpus + vsub selection (ADR-KAI4 P1).

Generates conversational sentences (what you actually say to Shannon: greetings,
status/time/memory questions, acknowledgements, and the "Hey Shannon" wake
phrases), tokenizes each with the REAL gemma tokenizer (sp_tok_enc), and picks a
vsub of <=508 token-ids (V+1<=512, GNA head padded to div-4). Sentences whose
tokens fall outside the capped vsub are dropped so every CTC target is legible.

Out: var/voice/corpus.jsonl  [{text, ids(vsub-indexed), gids(gemma)}]
     var/voice/vsub.npy       int64 [V] gemma token ids (index i -> vsub[i])
Run: python tools/voice_corpus.py
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import subprocess
import tempfile

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "var", "voice")
TOKENIZER = r"D:\F\shannon-prime-repos\models\gemma4-12b-b1.sp-tokenizer"
SP_TOK_ENC = r"D:\F\shannon-prime-repos\shannon-prime-system-engine\build-cpu\tools\sp_tok_dump\sp_tok_enc.exe"

# ── conversational surface (heavy word reuse keeps the token set small) ──
WAKE = ["hey shannon", "hey shannon are you there", "shannon", "okay shannon",
        "hey shannon wake up", "shannon can you hear me"]
GREET = ["hi", "hi there", "hey there", "hello", "good morning", "good evening",
         "how are you", "how are you doing", "how is it going", "how have you been"]
ACK = ["thanks", "thank you", "okay", "got it", "nice", "cool", "sounds good",
       "that is great", "well done", "good job", "perfect", "no worries"]
QUESTION = [
    "what time is it", "what is the time", "what day is it", "what is the date",
    "what is my name", "do you remember my name", "what do you remember about me",
    "what did we talk about", "what were we talking about", "what is my cat called",
    "what is the weather", "can you check the weather", "how is the system running",
    "how much memory is free", "what is the status", "are you listening",
    "can you hear me", "what can you do", "who made you", "what are you thinking about"]
TELL = [
    "my name is knack", "my cat is called tuffy", "i am doing well",
    "i am good thanks", "i like talking to you", "remember that i like tea",
    "i was born in australia", "my favourite colour is teal", "i work on you every day",
    "the weather is nice today", "i am tired today", "let us build something"]
COMMAND = [
    "tell me a joke", "tell me about yourself", "run a quick check",
    "search the web for me", "check the time please", "save that to memory",
    "forget that", "keep listening", "stop listening", "start over", "never mind"]
CHAT = [
    "that is interesting", "i see what you mean", "i agree with you",
    "i am not sure about that", "let me think about it", "that makes sense",
    "you are funny", "i like your sense of humour", "tell me more",
    "what do you think", "why do you say that", "how does that work"]

# ── compositional templates: many sentences from a small reused vocabulary, so
#    the CTC ear generalizes across contexts (the KAI-3 data-starvation fix). ──
def _templated() -> list[str]:
    out = list(ALL_BASE)
    subj = ["my name", "my cat", "the time", "the date", "the weather",
            "the status", "my memory", "the system"]
    for s in subj:
        out += [f"what is {s}", f"do you know {s}", f"can you tell me {s}",
                f"tell me {s}", f"what about {s}"]
    verbs = ["like", "love", "enjoy", "want", "need", "remember", "forget"]
    objs = ["tea", "coffee", "this", "that", "talking to you", "the weather",
            "my cat", "the quiet", "a joke", "the time"]
    for v in verbs:
        for o in objs:
            out.append(f"i {v} {o}")
    acts = ["tell me a joke", "check the time", "check the weather",
            "search the web", "save that", "start over", "keep listening",
            "stop listening", "run a check", "give me the status"]
    pre = ["can you", "could you", "please", "will you", "would you"]
    for p in pre:
        for act in acts:
            out.append(f"{p} {act}")
    fillers = ["that is nice", "that is great", "that is interesting", "i see",
               "i agree", "i am not sure", "let me think", "sounds good",
               "makes sense", "tell me more", "why is that", "how so"]
    out += fillers * 2
    # richer combinations for the bake: question x subject, greeting x follow,
    # wake x request — heavy word reuse keeps vsub bounded while sentences grow.
    qwords = ["what is", "where is", "when is", "how is", "do you know"]
    for q in qwords:
        for s in subj:
            out.append(f"{q} {s} today")
    follow = ["how are you", "what is new", "what can you do", "are you there",
              "can you hear me", "what time is it"]
    for g in ["hi", "hey", "hello", "hey shannon", "good morning"]:
        for fw in follow:
            out.append(f"{g} {fw}")
    for w in ["hey shannon", "okay shannon", "shannon"]:
        for act in acts:
            out.append(f"{w} {act}")
    return out


ALL_BASE = (WAKE * 4 + GREET * 3 + ACK * 2 + QUESTION * 3 + TELL * 3
            + COMMAND * 2 + CHAT * 2)
ALL = _templated()


def tok(text: str) -> list[int]:
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write(text)
        p = f.name
    try:
        out = subprocess.run([SP_TOK_ENC, TOKENIZER, p], capture_output=True, text=True, timeout=30)
        ids = [int(x) for x in out.stdout.splitlines() if x.strip().isdigit()]
        return ids[1:] if ids and ids[0] == 2 else ids   # drop forced BOS
    finally:
        os.unlink(p)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vmax", type=int, default=508)  # V+1 <= 512, head div-4
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)

    sentences = sorted(set(s.strip().lower() for s in ALL if s.strip()))
    toks = {s: tok(s) for s in sentences}
    freq = collections.Counter()
    for ids in toks.values():
        freq.update(ids)
    vsub = [t for t, _ in freq.most_common(a.vmax)]
    vset = set(vsub)
    vmap = {t: i for i, t in enumerate(vsub)}
    print(f"sentences={len(sentences)} distinct_tokens={len(freq)} vsub={len(vsub)}")

    corpus = []
    for s, ids in toks.items():
        if not ids or any(t not in vset for t in ids):
            continue
        corpus.append({"text": s, "gids": ids, "ids": [vmap[t] for t in ids]})
    dropped = len(sentences) - len(corpus)
    print(f"kept={len(corpus)} dropped_out_of_vsub={dropped}")

    np.save(os.path.join(OUT, "vsub.npy"), np.array(vsub, dtype=np.int64))
    with open(os.path.join(OUT, "corpus.jsonl"), "w", encoding="utf-8") as f:
        for row in corpus:
            f.write(json.dumps(row) + "\n")
    print(f"wrote {os.path.join(OUT, 'corpus.jsonl')} + vsub.npy")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
