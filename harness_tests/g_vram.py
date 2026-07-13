"""G-VRAM — the daemon must not spill to host memory.

WHY THIS GATE EXISTS
────────────────────
Windows/WDDM does not fail an oversubscribed CUDA allocation. It silently backs it with
system RAM over PCIe and carries on. No OOM. No error. No log line. The daemon comes up
looking perfectly healthy and every token that touches a spilled page crawls across the bus.

That is the worst failure mode a system can have: THE ONE THAT NEVER FAILS, ONLY DEGRADES.
It cannot be caught by a crash, an exception, or a status code, so it is invisible to every
other gate we own — it presents to the operator as a mystery ("why is it fast at first and
painfully slow 6000 turns later?") and to me as a wild goose chase. I spent an hour blaming
a logit mask that was not even in the code path of the request that hung.

So it gets a gate. My first version of it asserted:

    SHARED (host) GPU MEMORY MUST BE ZERO.        <-- WRONG. It can never be zero.

The operator killed that in one line: "spill is always 200mb". He was pointing at something I
had looked straight past -- the number DID NOT MOVE. 76 MiB at pmax=2955. 76 MiB at pmax=11743.
Still 76 MiB at ring=2048/pmax=1024 WITH 1.3 GB OF VRAM SITTING FREE. Nothing spills when there
is that much room. That floor is the daemon's own PINNED HOST STAGING (h_logits, h_router, the
H2D/D2H scratch) -- host memory that is SUPPOSED to be host memory. Windows' "Shared Usage"
counter does not distinguish it from evicted VRAM. I did not either.

So the gate now asserts the two things that are actually true:

    1. HOST MEMORY ABOVE THE MEASURED PINNED FLOOR   (the spill is a DELTA, not a total)
    2. PREFILL ms/token                              (a CLOCK -- no counter, no interpretation)

(2) is the one to trust. Memory bookkeeping is a proxy I have now misread twice; time is not.
Measured on this card: healthy 60 ms/tok, spilled 133 ms/tok. The clock cannot be argued with.

    python harness_tests/g_vram.py
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

DAEMON = "http://127.0.0.1:3000/v1/chat"

# ── THE FLOOR THAT IS NOT A SPILL (2026-07-13, the operator caught this) ────────────
# I asserted "shared host memory must be ~0". IT CAN NEVER BE ZERO. The operator noticed the
# number never moved -- 76 MiB at pmax=2955, 76 MiB at pmax=11743, and STILL 76 MiB at
# ring=2048/pmax=1024 with 1.3 GB OF VRAM SITTING FREE. Nothing spills when there is that much
# room. That 76 MiB is the daemon's own PINNED HOST STAGING BUFFERS (h_logits, h_router, the
# H2D/D2H scratch) -- memory that is SUPPOSED to live in host RAM.
#
# Windows' "Shared Usage" counter lumps DELIBERATE host allocations in with EVICTED VRAM. I
# read one as the other, and built a gate that would have failed forever on a perfectly healthy
# daemon -- and, worse, would have pushed me to shrink his MODEL to chase a number that was
# never going to move. A GATE THAT MEASURES THE WRONG QUANTITY DOES NOT FAIL SAFE: it fails
# confidently, with a number, and sends you to work on the wrong thing.
#
# So the spill is the DELTA above the floor, and the floor is MEASURED, not assumed.
SPILL_FLOOR_MB = 96      # pinned host staging: legitimate, always present, not a spill

# AND THE REAL METRIC IS TIME, NOT MEMORY. A memory counter is a proxy; ms/token is the thing
# we actually care about, and it is immune to my misreading of Windows' bookkeeping. Measured
# on the 2060 with the b1-reason weights:
#     healthy (ring 1024, pmax 11743, 76 MiB):   60 ms/tok prefill, 151 s prewarm
#     spilled (ring 2048, pmax 20000, 218 MiB): 133 ms/tok prefill, 334 s prewarm
# 60 is the floor this card can do. Anything near 2x that means the working set is on the wrong
# side of the PCIe bus, whatever the memory counters claim.
PREFILL_MS_PER_TOK_MAX = 90.0
MARGIN_MB = 256          # must match profiles/agent.toml [kv].autofit_margin_mb


def _ps(cmd):
    r = subprocess.run(["powershell", "-NoProfile", "-Command", cmd],
                       capture_output=True, text=True, timeout=60)
    return r.stdout.strip()


def dedicated_mb():
    out = _ps("nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader,nounits")
    used, total = (int(x.strip()) for x in out.splitlines()[0].split(","))
    return used, total


def shared_mb():
    """The number that matters. Windows exposes it; CUDA never will.

    ATTRIBUTED TO sp-daemon, NOT SUMMED OVER THE MACHINE. My first cut of this summed every
    GPU process on the box and reported 175 MiB -- of which the daemon owned 76 and Chrome and
    Unity Hub owned the rest. It would have had me shrink the operator's MODEL to make room for
    a browser tab. A gate that measures the wrong process does not fail safe: it fails
    CONFIDENTLY, with a number, in the direction of the most expensive possible fix.
    """
    out = _ps(
        "$c=(Get-Counter '\\GPU Process Memory(*)\\Shared Usage' -EA SilentlyContinue).CounterSamples;"
        "$t=0; foreach($s in $c){ if($s.InstanceName -match 'pid_(\\d+)'){"
        "  $p=Get-Process -Id $matches[1] -EA SilentlyContinue;"
        "  if($p -and $p.ProcessName -eq 'sp-daemon'){ $t += $s.CookedValue } } };"
        "[math]::Round($t/1MB,0)"
    )
    try:
        return int(float(out or 0))
    except ValueError:
        return -1


def turn(prompt, max_tokens=24, timeout=180):
    body = {"messages": [{"role": "user", "content": prompt}],
            "temperature": 0.0, "max_tokens": max_tokens}
    req = urllib.request.Request(DAEMON, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        r.read()
    return (time.time() - t0) * 1000


def main():
    checks, fails = [], []

    def check(name, ok, detail):
        checks.append(ok)
        print(f"  [{'OK  ' if ok else 'FAIL'}] {name}: {detail}", flush=True)
        if not ok:
            fails.append(name)

    print("G-VRAM — the daemon must not be running on host memory\n", flush=True)

    used, total = dedicated_mb()
    sh = shared_mb()
    free = total - used
    print(f"  card: {used} / {total} MiB dedicated, {free} MiB free, {sh} MiB SHARED\n", flush=True)

    # 1. Host memory ABOVE THE PINNED FLOOR. Not "shared == 0" -- shared is never 0.
    check("no host spill above the pinned floor", 0 <= sh <= SPILL_FLOOR_MB,
          f"{sh} MiB shared (floor {SPILL_FLOOR_MB} = legitimate pinned staging)")

    # 1b. AND THE ONE THAT ACTUALLY MATTERS: ms/token. The memory counter is a proxy and I got
    #     it wrong; this is the ground truth. A spilled daemon prefills at ~133 ms/tok on this
    #     card, a healthy one at ~60. No counter, no bookkeeping, no interpretation -- a clock.
    try:
        log = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "var", "daemon.log")
        # THE BIGGEST PREFILL, NOT THE LAST ONE. My first cut took the last match and read
        # 39 ms/tok off a 16-token warm prefill -- and PASSED, on a daemon that was demonstrably
        # spilling at 133 ms/tok on the cold one. A short prefill rides in cache and tells you
        # nothing about whether the working set is on the wrong side of the bus. The COLD,
        # LARGE prefill is the only one that touches enough memory to expose the spill.
        rate, best_n = None, 0
        with open(log, "r", errors="replace") as f:
            for line in f:
                m = re.search(r"prefill (\d+) tok in \d+ ms \(([\d.]+) ms/tok\)", line)
                if m and int(m.group(1)) > best_n:
                    best_n, rate = int(m.group(1)), float(m.group(2))
        if rate is None:
            check("prefill is not paging over PCIe", False, "no prefill line in daemon.log yet")
        else:
            check("prefill is not paging over PCIe", rate <= PREFILL_MS_PER_TOK_MAX,
                  f"{rate:.0f} ms/tok over {best_n} tok (healthy ~60; spilled ~133)")
    except Exception as e:
        check("prefill is not paging over PCIe", False, f"{type(e).__name__}: {e}")

    # 2. Autofit's whole job: leave the margin it was told to leave. If free VRAM is under
    #    the margin, autofit did not clamp -- either it is off, or serve.py is not mapping it.
    check("autofit left its margin", free >= MARGIN_MB * 0.5,
          f"{free} MiB free vs {MARGIN_MB} MiB margin")

    # 3. A short turn must be SHORT. This is the symptom, and the symptom is the point: a
    #    spilled daemon answers this in minutes, not milliseconds. No exception is raised
    #    either way, which is exactly why it must be TIMED and not merely called.
    try:
        ms = turn("Say hello.", max_tokens=8)
        check("a short turn is short", ms < 20_000, f"{ms:.0f} ms (a spilled daemon: minutes)")
    except Exception as e:
        check("a short turn is short", False, f"turn did not return: {type(e).__name__}")

    # 4. And it must STAY unspilled once the KV has grown. The spill is not a boot condition,
    #    it is what happens when the cache eats the last free megabytes mid-conversation.
    try:
        turn("Count from one to forty, in words, slowly.", max_tokens=256)
        sh2 = shared_mb()
        check("no host spill after the KV grows", 0 <= sh2 <= SPILL_FLOOR_MB,
              f"{sh2} MiB shared after a 256-token turn")
    except Exception as e:
        check("no host spill after the KV grows", False, f"{type(e).__name__}")

    ok = not fails
    print(f"\nG-VRAM: {'PASS' if ok else 'FAIL'} ({sum(checks)}/{len(checks)})", flush=True)
    if not ok:
        print("  failed: " + ", ".join(fails), flush=True)
        print("  -> the daemon is paging over PCIe. Lower [kv].pmax or raise autofit_margin_mb.",
              flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
