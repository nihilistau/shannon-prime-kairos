"""G-PK2-RECALL-LIVE — ADR-008 §recall: the pre-turn spine's text-in-context recall, LIVE on the
12B through the agent gateway. Seeds an isolated registry, then:
  matched query  -> {recall} SSE event fires + the streamed answer states the fact (faithful)
  foreign query  -> NO recall event + a clean parametric answer (no hijack)

Needs: daemon on :3000 (run_console.bat) + gateway on :8800 (_pk2_recall_gateway.bat, which arms
SP_SPINE_RECALL=1 and points SP_RECALL_REGISTRY at %TEMP%\\sp_pk2_recall_live.jsonl).

    python tests/g_pk2_recall_live.py
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

# Seed the isolated registry (the gateway process reads this same path).
with open(REG, "w", encoding="utf-8") as f:
    f.write(json.dumps({"name": "s0", "dir": "", "npos": 0, "topic": "color",
                        "text": "The user's favorite color is teal.",
                        "src": "operator", "ts": "2026-07-07T00:00:00Z"}) + "\n")


def turn(question: str, timeout: int = 420):
    body = {"messages": [{"role": "user", "content": question}], "max_tokens": 96}
    req = urllib.request.Request(GW + "/v1/chat", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    text, recall_evs, tool_evs = "", [], []
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
            elif "tool" in o:
                tool_evs.append(o["tool"]["name"])
    return text.strip(), recall_evs, tool_evs, time.time() - t0


def check(name, ok):
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    return ok


def main() -> int:
    res = []
    print("turn 1 (matched): what is my favorite color?")
    a1, r1, t1, dt1 = turn("What is my favorite color?")
    print(f"  -> {dt1:.0f}s recall_events={r1} tools={t1}\n  answer: {a1[:200]!r}")
    res.append(check("matched: {recall} event fired with the fact",
                     len(r1) >= 1 and any("teal" in f for f in r1[0])))
    res.append(check("matched: answer faithful (states teal)", "teal" in a1.lower()))

    print("\nturn 2 (foreign): capital of France?")
    a2, r2, t2, dt2 = turn("What is the capital of France? One word.")
    print(f"  -> {dt2:.0f}s recall_events={r2} tools={t2}\n  answer: {a2[:200]!r}")
    res.append(check("foreign: recall abstains (no event)", len(r2) == 0))
    res.append(check("foreign: clean parametric answer (Paris)", "paris" in a2.lower()))

    ok = all(res)
    print(f"\nG-PK2-RECALL-LIVE: {'PASS' if ok else 'FAIL'} ({sum(res)}/{len(res)})")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
