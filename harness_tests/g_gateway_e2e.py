"""G-HARNESS-GATEWAY-E2E -- the console's /v1/chat through the AGENT gateway (:8800).
Simulates the console: POST {messages} -> SSE {delta}; the model calls its tools (silently)
and the final answer streams. Gateway + daemon must be up."""
import json, sys, urllib.request
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def chat(msgs):
    body = json.dumps({"messages": msgs, "max_tokens": 140, "temperature": 0}).encode()
    req = urllib.request.Request("http://127.0.0.1:8800/v1/chat", data=body,
                                 headers={"Content-Type": "application/json"})
    out = []
    with urllib.request.urlopen(req, timeout=240) as r:
        for raw in r:
            s = raw.decode("utf-8", "replace").strip()
            if not s.startswith("data:"):
                continue
            p = s[5:].strip()
            if p == "[DONE]":
                break
            try:
                out.append(json.loads(p).get("delta", ""))
            except Exception:
                pass
    return "".join(out)


h = [{"role": "user", "content": "Please remember that my favourite colour is teal."}]
r1 = chat(h)
print("TURN1 (stream):", " ".join(r1.split())[:200], flush=True)
h.append({"role": "assistant", "content": r1})
h.append({"role": "user", "content": "What is my favourite colour?"})
r2 = chat(h)
print("TURN2 (stream):", " ".join(r2.split())[:200], flush=True)
print("G-HARNESS-GATEWAY-E2E:", "PASS" if (r1 and r2) else "FAIL")
