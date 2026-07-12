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

    # ── 0. THE FILE A HUMAN ACTUALLY OPENS ──────────────────────────────────────
    # This gate used to read console/console.html — and PASS — while the console served at
    # :3000/ was console/index.html, a different file that polled nothing. Two consoles had
    # drifted apart: index.html had the voice pipeline, console.html had everything I had
    # built for two days, and the operator only ever saw index.html. The gate agreed with me
    # because I pointed it at my own copy.
    #
    # A gate that tests an artifact nobody runs is not a gate; it is a second opinion from
    # the same mistake. So: the gate now reads the SERVED file, and it FAILS if a second
    # console appears beside it — because the next fork will look exactly as reasonable as
    # the last one did.
    console_dir = os.path.join(ROOT, "console")
    served = os.path.join(console_dir, "index.html")     # what the daemon serves at :3000/

    # A CONSOLE is a page you TALK TO HER IN: a composer, a transcript, and a live stream.
    # Not merely a page that calls the chat endpoint — operator.html fires one request from
    # a button and is a panel, not a console, and the first cut of this check flagged it.
    # Panels (ops/tuning/dashboard/operator) are fine and expected; a second place to HOLD A
    # CONVERSATION is what drifts, because it is the one that grows features.
    forks = []
    for fn in os.listdir(console_dir):
        if not fn.endswith(".html") or fn == "index.html":
            continue
        txt = open(os.path.join(console_dir, fn), encoding="utf-8", errors="replace").read()
        if 'http-equiv="refresh"' in txt:
            continue                                   # a redirect stub is not a console
        if all(k in txt for k in ("chat-input", "send-btn", "appendMessage")):
            forks.append(fn)
    check("there is exactly ONE console", not forks,
          f"forks of the console that a human could open: {forks}" if forks else
          "index.html — the file the daemon serves")

    page = open(served, encoding="utf-8").read()

    # ── 1. it must actually poll the outbox ─────────────────────────────────────
    check("the SERVED console polls the kairos outbox",
          "/v1/kairos/outbox" in page,
          "the entire chain is unobservable without this")
    check("...and renders her unprompted turn into the transcript",
          "unprompted" in page and "appendMessage" in page)
    check("...and pushes it into history (or she forgets she spoke)",
          re.search(r"history\.push\(\s*\{\s*role:\s*'assistant',\s*content:\s*m\.text",
                    page) is not None,
          "shown-but-not-remembered leaves a hole in the next turn's context")
    check("...and it keeps the voice pipeline it already had",
          "/v1/voice" in page, "the fork had lost it")
    check("...and it shows the board",
          "/v1/notes" in page and "the board" in page)

    # ── EVERY CHAT PATH MUST TELL THE SCHEDULER THAT HE SPOKE ──────────────────
    # on_user_turn() lived only in the console path. On the OpenAI path the scheduler never
    # learned a human had said anything, so her CHAIN never reset (one unprompted message
    # and she was muted for good) and last_user_at stayed 0, so the room never counted as
    # quiet and reflection could not fire at all. Both failures are SILENT — nothing errors,
    # she just quietly stops being alive on that path. Sixth instance of the same bug in one
    # week, so it gets a gate rather than another comment.
    app = open(os.path.join(ROOT, "harness", "server", "app.py"), encoding="utf-8").read()
    n_paths = app.count("_kairos_after_turn(body, text)") + app.count("ks.on_reply(")
    n_told = app.count("on_user_turn(")
    check("every chat path tells the scheduler that HE SPOKE (chain reset + idle clock)",
          n_told >= 2, f"on_user_turn called at {n_told} site(s); "
                       f"a path that never resets the chain mutes her permanently")

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
