"""G-FLOAT-PARITY — per-build certification for float serving (P5a).

STATUS 2026-07-11: these four probes are NECESSARY BUT NOT SUFFICIENT — they
PASSED 4/4 on a build whose float path then corrupted ATTENDED DETAIL in live
serving (persona read back as "Shannon-15 / RTX 3067"; a tool time copied as
"2014-365"). Simple facts answer from WEIGHTS; the float damage lives in
ATTENDED ROWS. Full certification additionally requires:
  (a) an attended-persona probe: prefill the real preamble in float, ask for
      the persona's hardware/name, require verbatim correctness;
  (b) a tool-number copy probe: a tool round whose output digits must be
      copied exactly through a float round-2.
Until those exist and PASS, float serving stays REFUTED (profile
decode.byteexact = true) and this gate documents the bar.

Run with the stack up:  python harness_tests/g_float_parity.py
"""
import json
import sys
import urllib.request

PROBES = [
    ("What is the capital of France? One word.", "paris"),
    ("What is 6 times 7? Digits only.", "42"),
    ("Name the largest planet in our solar system. One word.", "jupiter"),
    ("What color is a stop sign? One word.", "red"),
]


def chat(msg: str, byteexact: bool) -> str:
    body = json.dumps({"messages": [{"role": "user", "content": msg}],
                       "max_tokens": 32, "temperature": 0,
                       "byteexact": byteexact, "auto_recall": False}).encode()
    req = urllib.request.Request("http://127.0.0.1:3000/v1/chat", data=body,
                                 headers={"Content-Type": "application/json"})
    out = []
    with urllib.request.urlopen(req, timeout=280) as resp:
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
    ok = 0
    for q, want in PROBES:
        fa = chat(q, byteexact=False)
        ea = chat(q, byteexact=True)
        f_ok = want in fa.lower()
        e_ok = want in ea.lower()
        both = f_ok and e_ok
        ok += both
        print(f"  [{'PASS' if both else 'FAIL'}] {q[:44]:44} float={fa[:24]!r}({'Y' if f_ok else 'n'}) "
              f"exact={ea[:24]!r}({'Y' if e_ok else 'n'})")
    verdict = "PASS" if ok == len(PROBES) else "FAIL"
    print(f"\nG-FLOAT-PARITY: {verdict} ({ok}/{len(PROBES)}) — float serving "
          f"{'CERTIFIED for this binary' if verdict == 'PASS' else 'REFUSED: keep byteexact serving'}")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
