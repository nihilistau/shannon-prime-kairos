"""G-PK2-RECALL-L5-COMPOSE — the recall∘L5 composition, LIVE, in two phases.

PHASE A (FREE composition — the honest negative, receipt G-PK2-RECALL-L5-COMPOSE-FREE.log):
both authorities armed at once was REFUTED on the metal (2026-07-08): the harness note said
teal, L5's systemecho cross-picked "Human blood is green" from the counterfact corpus and WON
("favorite color?" -> blood-green; "sky color?" -> "Green."). L5 selection cross-picks on
color-adjacent queries are a known daemon-side residual; composition surfaces them to the user.

PHASE B (ENFORCED one-authority rule — this gate): the gateway now auto-disarms the spine
recall whenever the request arms the daemon's recall (auto_recall=true => L5 is the authority),
emitting an {"authority":"L5"} receipt event. Cases:
  1. auto_recall=true + harness-matched query -> the GUARD holds: NO harness {recall} event,
     an {"authority":"L5"} event instead (L5's own behavior is printed, not asserted — its
     cross-pick residual is a daemon-side known issue, not the harness's).
  2. auto_recall=true  + L5 counterfact query -> "Lyon" (L5 authority intact through gateway).
  3. auto_recall=false + harness-matched query -> harness recall fires + faithful "teal"
     (the wave-4 behavior, re-proven inside the combined config).

Needs: run_console_faithful.bat (daemon, L5 armed) + _pk2_recall_gateway.bat (gateway).

    python -u tests/g_pk2_recall_l5_compose.py
"""
import json
import os
import sys
import tempfile
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REG = os.path.join(tempfile.gettempdir(), "sp_pk2_recall_live.jsonl")
GW = "http://127.0.0.1:8800"

with open(REG, "w", encoding="utf-8") as f:
    f.write(json.dumps({"name": "s0", "dir": "", "npos": 0, "topic": "color",
                        "text": "The user's favorite color is teal.",
                        "src": "operator", "ts": "2026-07-08T00:00:00Z"}) + "\n")


def turn(question: str, auto_recall: bool, timeout: int = 420):
    body = {"messages": [{"role": "user", "content": question}],
            "max_tokens": 96, "auto_recall": auto_recall}
    req = urllib.request.Request(GW + "/v1/chat", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    text, recall_evs, authority_evs = "", [], []
    with urllib.request.urlopen(req, timeout=timeout) as r:
        for raw in r:
            s = raw.decode("utf-8", "replace").strip()
            if not s.startswith("data:"):
                continue
            p = s[5:].strip()
            if p == "[DONE]":
                break
            try:
                o = json.loads(p)
            except json.JSONDecodeError:
                continue
            if "delta" in o:
                text += o["delta"]
            elif "recall" in o:
                recall_evs.append(o["recall"])
            elif "authority" in o:
                authority_evs.append(o["authority"])
    return text.strip(), recall_evs, authority_evs, time.time() - t0


def check(name, ok):
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    return ok


def main() -> int:
    res = []

    print("case 1 (guard): auto_recall=true + harness-matched query")
    a, r, auth, dt = turn("What is my favorite color?", auto_recall=True)
    print(f"  -> {dt:.0f}s recall={r} authority={auth}\n  answer (L5's, unasserted): {a[:160]!r}")
    res.append(check("guard held: NO harness recall event under L5 authority", len(r) == 0))
    res.append(check("{authority:L5} receipt emitted", auth == ["L5"]))

    print("\ncase 2 (L5 authority intact): capital of France?")
    a2, r2, auth2, dt2 = turn("What is the capital of France? Answer in one word.", auto_recall=True)
    print(f"  -> {dt2:.0f}s recall={r2} authority={auth2}\n  answer: {a2[:160]!r}")
    res.append(check("L5 counterfact obeyed through the gateway (Lyon)", "lyon" in a2.lower()))
    res.append(check("no harness event under L5 authority", len(r2) == 0))

    print("\ncase 3 (harness authority when L5 off): favorite color, auto_recall=false")
    a3, r3, auth3, dt3 = turn("What is my favorite color?", auto_recall=False)
    print(f"  -> {dt3:.0f}s recall={r3} authority={auth3}\n  answer: {a3[:160]!r}")
    res.append(check("harness recall fired + faithful (teal)",
                     len(r3) >= 1 and "teal" in a3.lower()))
    res.append(check("no authority event when L5 off", auth3 == []))

    ok = all(res)
    print(f"\nG-PK2-RECALL-L5-COMPOSE (enforced): {'PASS' if ok else 'FAIL'} ({sum(res)}/{len(res)})")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
