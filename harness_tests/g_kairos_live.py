"""G-KAIROS-LIVE — does she actually speak up, on the real stack, and mostly not?

The policy is gated pure (g_kairos_policy) and the knobs are gated pure (g_tuning). This
is the one that says the whole chain is REACHABLE end to end:

    forward emits eot_margin -> SSE `kairos` event -> client -> scheduler -> delay
    -> continuation turn -> worth_saying() -> outbox -> the operator sees it

and, just as importantly, that on an ordinary turn NOTHING comes out.

Needs a warm stack on the `kairos` profile (SP_KAIROS=1).
"""
from __future__ import annotations

import json
import time
import urllib.request

GW = "http://127.0.0.1:8800"
PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" :: {detail}" if detail else ""))


def post(path, body):
    req = urllib.request.Request(GW + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=300).read().decode())


def get(path):
    return json.loads(urllib.request.urlopen(GW + path, timeout=30).read().decode())


def say(text, session, max_tokens=200, tools=True):
    """`tools=False` for the cut-off case. At a tiny max_tokens the AGENT path starts a
    TOOL CALL and runs out of budget inside it — the reply comes back as
    '(tool loop exhausted)', which is a broken tool round, not a guillotined sentence.
    The calibration was measured on prose, so the cut-off probe must be prose too."""
    body = {"messages": [{"role": "user", "content": text}],
            "max_tokens": max_tokens, "temperature": 0, "session": session}
    if not tools:
        body["tools"] = False
    return post("/v1/chat/completions", body)["choices"][0]["message"]["content"]


def outbox(session):
    return get(f"/v1/kairos/outbox?session={session}")


def main() -> int:
    print("G-KAIROS-LIVE - she speaks up when cut off, and is otherwise quiet.\n")
    sess = f"gk{int(time.time())%100000}"

    # arm kairos through the TUNING API — the same surface the operator's UI uses.
    # If the knob does not bite here, the panel is decoration.
    post("/v1/tuning", {"values": {"kairos.enabled": True, "kairos.cooldown_s": 0.0}})
    st = get("/v1/kairos/state")
    check("kairos armed through the operator's own tuning API", st.get("enabled") is True)

    # ── 1. an ORDINARY turn: she must stay quiet ────────────────────────────────
    say("What is the capital of France? One word.", sess, max_tokens=200)
    time.sleep(8)
    ob = outbox(sess)
    check("after a FINISHED turn she says nothing unprompted",
          len(ob["messages"]) == 0,
          f"{len(ob['messages'])} unprompted message(s) — she talked over a finished thought"
          if ob["messages"] else "silent")

    # ── 2. a turn GUILLOTINED mid-sentence: she should pick it back up ──────────
    reply = say("Describe a thunderstorm over the ocean in vivid detail, at length.",
                sess, max_tokens=40, tools=False)
    print(f"    (cut off at: {reply.strip()[-46:]!r})")
    got = []
    for _ in range(40):                      # delay + a continuation turn
        time.sleep(2)
        got = outbox(sess)["messages"]
        if got:
            break
    check("after being CUT OFF mid-thought she picks the thread back up", bool(got),
          repr(got[0]["text"][:70]) if got else "nothing — she never continued")
    if got:
        check("...and she says WHY (auditable)", bool(got[0].get("reason")), got[0]["reason"])
        check("...and it is not a greeting or a restatement",
              not got[0]["text"].lower().lstrip("*_ (").startswith(("hi", "hey", "hello", "sorry")),
              got[0]["text"][:50])

    # ── 3. she cannot chain: nothing more without him speaking ──────────────────
    time.sleep(10)
    again = outbox(sess)["messages"]
    check("she does NOT keep going (max_chain holds on the live stack)",
          len(again) == 0, f"{len(again)} further message(s) — she is monologuing")

    # restore
    post("/v1/tuning/reset", {"key": "kairos.enabled"})
    post("/v1/tuning/reset", {"key": "kairos.cooldown_s"})

    print(f"\nG-KAIROS-LIVE: {'PASS' if not FAIL else 'FAIL'} ({len(PASS)}/{len(PASS)+len(FAIL)})")
    return 0 if not FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())
