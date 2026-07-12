"""G-KAIROS-CONSOLE — the last mile. She speaks, and a human can actually see it.

THE WHOLE CHAIN WAS BUILT EXCEPT THIS. The impulse fires, the policy allows it, she
generates, worth_saying() approves, the scheduler files the message in the outbox — and
nothing was listening. console.html never polled /v1/kairos/outbox. An armed kairos would
have spoken into a void, and every symptom would have read "she never speaks".

AND IT WOULD STILL HAVE BEEN INVISIBLE AFTER WIRING THE POLL, because the session key was
derived in four places under two different rules:

    _agent_text / _kairos_after_turn :  session | session_id | default
    _native_chat_sse                 :  session | chat_id    | default

console.html sends `session_id`. So on the console path — the one a human actually uses —
her message was filed under "default" while the console would have polled for its own uuid.
She would have spoken, correctly, into a session nobody was listening to.

A key derived in more than one place is a key that disagrees with itself. This gate drives
the gateway EXACTLY as console.html does (session_id, not session) and demands the message
come back out under the key the console asks with.
"""
from __future__ import annotations

import json
import re
import os
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GW = "http://127.0.0.1:8800"
PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" :: {detail}" if detail else ""))


def post(path, body):
    req = urllib.request.Request(GW + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=600).read().decode())


def get(path):
    return json.loads(urllib.request.urlopen(GW + path, timeout=30).read().decode())


def main() -> int:
    print("G-KAIROS-CONSOLE - she speaks, and a human can see it.\n")

    # ── 1. the console page must actually poll the outbox ───────────────────────
    page = open(os.path.join(ROOT, "console", "console.html"), encoding="utf-8").read()
    check("console.html polls the kairos outbox at all",
          "/v1/kairos/outbox" in page,
          "the entire chain is unobservable without this")
    check("...and renders her unprompted turn into the transcript",
          "unprompted" in page and "appendMessage" in page)
    check("...and pushes it into history (or she forgets she spoke)",
          re.search(r"history\.push\(\s*\{\s*role:\s*'assistant',\s*content:\s*m\.text",
                    page) is not None,
          "shown-but-not-remembered leaves a hole in the next turn's context")

    # ── 2. THE KEY. Drive it exactly as the console does: session_id. ───────────
    sess = f"gkc{int(time.time()) % 100000}"
    post("/v1/tuning", {"values": {"kairos.enabled": True, "kairos.cooldown_s": 0.0}})
    try:
        # a turn guillotined mid-sentence -> she should want to continue
        post("/v1/chat/completions", {
            "messages": [{"role": "user",
                          "content": "Describe a thunderstorm over the ocean in vivid detail, at length."}],
            "max_tokens": 40, "temperature": 0, "tools": False,
            "session_id": sess,           # <- what console.html sends. NOT "session".
        })

        got = []
        deadline = time.time() + 240      # the continuation is a full 12B turn
        while time.time() < deadline:
            time.sleep(2)
            got = get(f"/v1/kairos/outbox?session={sess}")["messages"]
            if got:
                break

        check("a turn sent as the CONSOLE sends it (session_id) reaches the outbox "
              "under the key the console polls",
              bool(got),
              repr(got[0]["text"][:60]) if got else
              f"nothing under '{sess}' — she spoke into a session nobody is listening to")

        if got:
            check("...carrying the REASON the operator will see on hover",
                  bool(got[0].get("reason")), got[0]["reason"])
            check("...and the raw margin, so an unexpected message can be audited",
                  isinstance(got[0].get("margin"), float), str(got[0].get("margin")))

        # nothing should be sitting under "default" — that is the bug this gate exists for
        stray = get("/v1/kairos/outbox?session=default")["messages"]
        check("nothing was misfiled under 'default'", not stray,
              f"{len(stray)} message(s) went to the wrong session key")
    finally:
        post("/v1/tuning/reset", {"key": "kairos.enabled"})
        post("/v1/tuning/reset", {"key": "kairos.cooldown_s"})

    total = len(PASS) + len(FAIL)
    print(f"\nG-KAIROS-CONSOLE: {'PASS' if not FAIL else 'FAIL'} ({len(PASS)}/{total})")
    return 0 if not FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())
