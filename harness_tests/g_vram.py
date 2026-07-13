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

So it gets a gate, and the gate asserts the ONE thing no exception will ever tell us:

    SHARED (host) GPU MEMORY MUST BE ZERO.

Measured, not asserted. If this fails, the daemon is running on a GPU pretending to be a GPU.

    python harness_tests/g_vram.py
"""
import json
import subprocess
import sys
import time
import urllib.request

DAEMON = "http://127.0.0.1:3000/v1/chat"
MARGIN_MB = 512          # must match profiles/agent.toml [kv].autofit_margin_mb
SPILL_TOLERANCE_MB = 64  # the desktop compositor jitters; a real spill is HUNDREDS of MiB


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

    # 1. THE ONE THAT MATTERS. Nothing may live in host memory.
    check("no host spill at idle", 0 <= sh <= SPILL_TOLERANCE_MB,
          f"{sh} MiB shared (tolerance {SPILL_TOLERANCE_MB})")

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
        check("no host spill after the KV grows", 0 <= sh2 <= SPILL_TOLERANCE_MB,
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
