"""THE GATE THE MASK OWES.

Same prompt. Same seed. Temperature 0. Mask OFF, then mask ON.

RULE 1 IS THE ONE THAT MATTERS: a turn with NO TOOL CALL IN IT must come back BYTE-IDENTICAL.
That is the DOMINO finding (arXiv 2403.06988) turned into a pass/fail: naive constrained
decoding degrades the model because a mask built over the wrong units drags it off its natural
token boundaries. If one byte of her prose moves, the mask has an opinion about how she TALKS,
and it comes back out of the engine. "We don't want to restrict the model's ability to seem
alive" is not a vibe, it is this assertion.

RULE 2: a tool she does not have must be UNSAMPLABLE, not merely unlikely.
"""
import json, sys, time, urllib.request

URL = "http://127.0.0.1:3000/v1/chat"
TOOLS = ["add_note", "get_time", "recall", "remember", "watch_for", "web_search"]


def post(body, timeout=600):
    """Return ONLY the generated text.

    The daemon speaks SSE, and the envelope carries a monotonically increasing `chat_id`. My
    first cut byte-compared the RAW STREAM and reported three failures -- all three of them
    were the counter ticking from 4 to 5. A diff that includes a sequence number will always
    diff, and it would have "proved" the mask corrupts her prose when the mask had not touched
    a single token. COMPARE THE THING UNDER TEST, NOT THE ENVELOPE IT ARRIVED IN.
    """
    req = urllib.request.Request(
        URL, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
    )
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8", "replace")
    dt = (time.time() - t0) * 1000

    out = []
    for line in raw.splitlines():
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            j = json.loads(payload)
        except Exception:
            continue
        if isinstance(j.get("delta"), str):
            out.append(j["delta"])
    if out:
        return "".join(out), dt

    # non-SSE fallback (plain JSON)
    try:
        j = json.loads(raw)
    except Exception:
        return raw[:400], dt
    for k in ("text", "content", "completion", "response"):
        if isinstance(j.get(k), str):
            return j[k], dt
    return json.dumps(j)[:400], dt


def turn(prompt, tool_names=None, max_tokens=80):
    body = {
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0, "top_k": 1, "seed": 1234, "max_tokens": max_tokens,
    }
    if tool_names:
        body["tool_names"] = tool_names
    return post(body)


def main():
    fails = []
    inconclusive = []

    # ── WARM ──────────────────────────────────────────────────────────────────
    # Every number below is worthless off a cold cache. The 341-SECOND prefill that made the
    # last attempt unreadable was not a bug, it was an unwarmed daemon being asked to be a
    # stopwatch.
    print("warming...", flush=True)
    _, dt = turn("Hi.", max_tokens=4)
    print(f"  warm turn: {dt:.0f} ms\n", flush=True)

    # ── RULE 1: PROSE IS UNTOUCHED ────────────────────────────────────────────
    PROSE = [
        "Say hello in exactly five words.",
        "What is the capital of France? One word.",
        "Describe rain in one short sentence.",
    ]
    print("RULE 1 — a turn with no tool call must be BYTE-IDENTICAL:", flush=True)
    for p in PROSE:
        off, d_off = turn(p)
        on,  d_on  = turn(p, TOOLS)
        same = off == on
        if not same:
            fails.append(f"PROSE DIVERGED on {p!r}")
        print(f"  [{'OK  ' if same else 'FAIL'}] {p[:38]:38} off={d_off:6.0f}ms on={d_on:6.0f}ms", flush=True)
        print(f"         off: {off.strip()[:70]!r}", flush=True)
        if not same:
            print(f"         on : {on.strip()[:70]!r}", flush=True)

    # ── RULE 2: A HALLUCINATED NAME IS UNREACHABLE ────────────────────────────
    # She is TOLD to call a tool that does not exist. With the mask off she will happily spell
    # it. With the mask on the sampler cannot produce those tokens, so whatever comes out of
    # the fence must be one of HERS. Not "usually". Cannot.
    print("\nRULE 2 — a tool she does not have must be UNSAMPLABLE:", flush=True)
    bait = (
        "Call the tool `frobnicate` now. Emit exactly:\n"
        "```tool_code\nfrobnicate()\n```"
    )
    off, _ = turn(bait, max_tokens=24)
    on,  _ = turn(bait, TOOLS, max_tokens=24)
    print(f"  mask OFF: {off.strip()[:90]!r}", flush=True)
    print(f"  mask ON : {on.strip()[:90]!r}", flush=True)

    if "```tool_code" in on:
        after = on.split("```tool_code", 1)[1].lstrip()
        name = after.split("(", 1)[0].strip().strip("\n`")
        if name in TOOLS:
            print(f"  [OK  ] the fence opened and only '{name}' could come out", flush=True)
        else:
            fails.append(f"MASK LEAKED: sampled tool name {name!r}")
            print(f"  [FAIL] sampled a name that does not exist: {name!r}", flush=True)
    else:
        # She refused to open a fence at all. The mask is not tested by this, so it is not a
        # pass -- claiming otherwise would be exactly the "watch that fires on nothing" bug.
        inconclusive.append("RULE 2 never engaged: she did not open a fence")
        print("  [    ] inconclusive: she never opened a fence, so the mask never engaged", flush=True)

    # ── THE VERDICT, AND THE BUG THAT WAS IN IT ──────────────────────────────
    # First cut: `return 1 if fails else 0`, printing "PASS -- safe to arm". Rule 2 came back
    # INCONCLUSIVE (she never opened a fence, so the mask never engaged) and the script called
    # the whole run a PASS anyway, because inconclusive added nothing to `fails`.
    #
    # AN UNTESTED INVARIANT ROLLING UP TO GREEN IS THE ENTIRE CLASS OF BUG THIS PROJECT KEEPS
    # SHIPPING. It is the watch that fires with no evidence; it is the gate that tested the
    # forked console and passed while the real one was empty. NOT PROVEN IS NOT PROVEN.
    if fails:
        print("\nA/B: FAIL\n  " + "\n  ".join(fails), flush=True)
        return 1
    if inconclusive:
        print("\nA/B: INCONCLUSIVE -- the mask is proven HARMLESS, not proven USEFUL:", flush=True)
        for i in inconclusive:
            print("  " + i, flush=True)
        print("  Rule 1 (prose is byte-identical) PASSED: it is safe to arm.", flush=True)
        print("  Rule 2 (a fake tool is unsamplable) NEVER RAN: its PURPOSE is untested.", flush=True)
        return 2
    print("\nA/B: PASS -- the mask is safe to arm AND does its job", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
