"""G-VERBATIM — can the served stack COPY what is in its own context?

THE FINDING (2026-07-12, temp 0, tools off, recall off, ngram off, both
byteexact and float, both the reason and base models — all identical):

    "Repeat exactly, nothing else: 4471"        -> "4481"
    "The door code is 4471. The GPU is an RTX 2060." -> "4417 and RTX 3061."
    "Repeat exactly: quartzblanket"             -> quartzblanket  (CORRECT)
    "What is 2+2?"                              -> 4              (CORRECT)

DIGITS get scrambled; WORDS copy fine; ARITHMETIC works. It is not the sampler
(ngram/temp/eot make no difference), not byte-exactness (identical strings),
not my harness. It is the served ENGINE/MODEL path, and it explains every
"garbled number" ever blamed on sampling: the tool time "2014-365", the persona
"RTX 210.", HINDSIGHT's "numeric garbling of tool results".

Suspects, in order (each needs its own experiment):
  1. SP_CUDA_DECODE_INT8 — int8 decode GEMM + the PACKED INT8 EMBEDDING that
     doubles as the tied LM head (the daemon REFUSES to open with it off for
     this model: "tied head needs SP_CUDA_DECODE_INT8=1"). Digit tokens are
     near-neighbours in embedding space; int8 collapse would hit them first and
     leave distinctive words intact — exactly the observed signature.
     Test with a model that carries a separate f16 head (gemma4-12b-st, 11.1 GB).
  2. Weight quantization of the served model (b1 ~6-bit).
  3. Positional/attention read-out of single-char digit tokens.

This gate is the tripwire: ANY change to the engine, sampler, model or profile
re-runs it. Numbers must survive a round trip through the model's own context,
or memory/tools/persona cannot be trusted.

Run with the stack up:  python harness_tests/g_verbatim.py
"""
import json
import sys
import urllib.request

DAEMON = "http://127.0.0.1:3000/v1/chat"
PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)


def ask(system, user, max_tokens=48):
    msgs = ([{"role": "system", "content": system}] if system else []) + \
           [{"role": "user", "content": user}]
    body = json.dumps({"messages": msgs, "max_tokens": max_tokens, "temperature": 0,
                       "auto_recall": False, "no_repeat_ngram": 0,
                       "eot_bias": 0}).encode()
    req = urllib.request.Request(DAEMON, data=body,
                                 headers={"Content-Type": "application/json"})
    out = []
    with urllib.request.urlopen(req, timeout=180) as resp:
        for raw in resp:
            s = raw.decode("utf-8", "replace").strip()
            if s.startswith("data:"):
                p = s[5:].strip()
                if p == "[DONE]":
                    break
                try:
                    out.append(json.loads(p).get("delta", ""))
                except Exception:
                    pass
    return "".join(out).strip()


def main() -> int:
    print("G-VERBATIM — can the model copy its own context? (temp 0, no tools, no recall)\n")

    # 1. the control: a rare WORD must survive (it does today)
    a = ask("The passphrase is quartzblanket.", "State the passphrase exactly.")
    check("WORD copy: quartzblanket", "quartzblanket" in a.lower(), repr(a[:48]))

    # 2. arithmetic (the model is not broken in general)
    a = ask(None, "What is 2+2? Digits only.")
    check("arithmetic: 2+2=4", "4" in a, repr(a[:32]))

    # 3. THE BUG: a number in context must survive a copy
    a = ask("The door code is 4471.", "State the door code exactly, digits only.")
    check("DIGIT copy: 4471", "4471" in a, repr(a[:48]))

    a = ask("The GPU is an RTX 2060.", "State the GPU model exactly.")
    check("DIGIT copy: RTX 2060", "2060" in a, repr(a[:48]))

    a = ask(None, "Repeat exactly, nothing else: 8302")
    check("DIGIT echo: 8302", "8302" in a, repr(a[:48]))

    # 4. the composite: numbers + words together (the tool-output shape)
    a = ask("Tool output: temperature 21.7C, humidity 48%, station K9.",
            "Report the temperature, humidity and station exactly.")
    ok = ("21.7" in a) and ("48" in a) and ("k9" in a.lower())
    check("TOOL-shaped copy: 21.7 / 48 / K9", ok, repr(a[:64]))

    print(f"\nG-VERBATIM: {'PASS' if FAIL == 0 else 'FAIL'} ({PASS}/{PASS + FAIL})")
    if FAIL:
        print("  ^ numbers do not survive the model's own context. Memory, tools and")
        print("    persona details are ALL unreliable until this is fixed. See the")
        print("    suspect list in this file's docstring.")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
