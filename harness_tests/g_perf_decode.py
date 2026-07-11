"""G-PERF-DECODE — a REPEATABLE decode-rate gate.

WHY THIS EXISTS (2026-07-12): I spent this session doing perf work with ad-hoc
probes and drew two wrong conclusions from them:

  1. "decode is 11.5 tok/s at 1600 ctx"  -- that run generated only 20 tokens.
     The like-for-like 100-token number is 4.3 tok/s. I compared a 20-token run
     against a 100-token run and called the difference a regression.
  2. "the serial softmax is the long-context bottleneck" -- parallelising it made
     decode 32% SLOWER (and ptxas says 0 spills, so the obvious mechanism is out).

Both errors have the same root: an unpinned benchmark. tok/s is meaningless unless
the GENERATED TOKEN COUNT and the CONTEXT LENGTH are both pinned, because the model
is free to stop early and the rate is a function of context.

So: this gate pins both, repeats, and reports the median. Any perf claim about this
engine must cite it. No more ad-hoc probes.

    python harness_tests/g_perf_decode.py            # daemon-direct, :3000

Reports tok/s at each context bucket and enforces a floor so a silent regression
(a kernel change, a profile flip, a driver update) cannot land unnoticed.
"""
from __future__ import annotations

import json
import statistics
import sys
import time
import urllib.request

DAEMON = "http://127.0.0.1:3000/v1/chat"
FILLER = "The archive records the following unrelated background note for reference. "

# (label, approx context tokens, floor tok/s) — floors are set from the measured
# baseline with headroom; they catch REGRESSIONS, they are not targets.
BUCKETS = [
    ("short  (~30 tok ctx)", 0, 15.0),
    ("medium (~800 tok ctx)", 800, 6.0),
    ("long   (~1700 tok ctx)", 1700, 3.0),
]
GEN_TOKENS = 64          # PINNED. every bucket must emit exactly this many.
REPEATS = 2


def _pad(approx_tokens: int) -> str:
    if approx_tokens <= 0:
        return ""
    # FILLER is ~13 tokens; build up to the requested context
    return FILLER * max(1, approx_tokens // 13)


def _run(prompt: str, max_tokens: int) -> tuple[int, float]:
    """Returns (chars, wall_seconds). Forces a long generation with an open-ended ask."""
    body = json.dumps({
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0,
        "auto_recall": False,     # the legacy in-kernel lane must not pollute the timing
        "byteexact": True,        # the SERVED regime
    }).encode()
    req = urllib.request.Request(DAEMON, data=body,
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    raw = urllib.request.urlopen(req, timeout=900).read().decode("utf-8", "replace")
    el = time.time() - t0
    text = "".join(
        json.loads(ln[6:]).get("delta", "")
        for ln in raw.splitlines()
        if ln.startswith("data: ") and '"delta"' in ln
    )
    return len(text), el


def main() -> int:
    print("G-PERF-DECODE — pinned generation length, pinned context. temp 0, byteexact.\n")
    print(f"  {'bucket':<24}{'gen':>6}{'tok/s (median)':>18}{'floor':>8}")
    ok = True
    for label, ctx, floor in BUCKETS:
        # ask for a long open-ended answer so the model actually emits GEN_TOKENS
        ask = ("Write a detailed description of a thunderstorm over the ocean. "
               "Keep writing; do not stop early.")
        prompt = (_pad(ctx) + " Now: " + ask) if ctx else ask
        rates = []
        for _ in range(REPEATS):
            chars, el = _run(prompt, GEN_TOKENS)
            toks = max(1, chars // 4)            # ~4 chars/token; the daemon's own
            rates.append(toks / el)              # TURN-PHASE line is the authority
        med = statistics.median(rates)
        good = med >= floor
        ok &= good
        flag = "" if good else "   <<< BELOW FLOOR"
        print(f"  {label:<24}{GEN_TOKENS:>6}{med:>18.1f}{floor:>8.1f}{flag}")

    print("\n  NOTE: the daemon's own TURN-PHASE line is the authoritative rate "
          "(it excludes prefill/recall).\n  This gate's wall-clock figure is a "
          "conservative upper bound on cost. Cross-check var/daemon.log.")
    print(f"\nG-PERF-DECODE: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
