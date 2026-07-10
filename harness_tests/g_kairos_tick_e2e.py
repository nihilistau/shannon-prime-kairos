"""G-HARNESS-KAIROS-TICK-E2E -- the agency round fires on a heartbeat tick.

run_agency_scheduler runs one tick against a seeded-redundant registry and the model
autonomously curates its memory WITHOUT a user turn -- the KAIROS auto-round realized.
Requires the daemon up on :3000.

    python tests/g_kairos_tick_e2e.py
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TESTREG = os.path.join(tempfile.gettempdir(), "sp_kairos_test.jsonl")
os.environ["SP_RECALL_REGISTRY"] = TESTREG
os.environ["SP_DAEMON_URL"] = "http://127.0.0.1:59999"  # remember() append-only; forget local
SEED = ["The user has a dog.", "The user has a dog named Rex.", "The user's name is Knack."]
with open(TESTREG, "w", encoding="utf-8") as _f:
    for i, t in enumerate(SEED):
        _f.write(json.dumps({"name": f"s{i}", "dir": "", "npos": 0, "topic": "", "text": t}) + "\n")

from harness.control.agency import run_agency_scheduler
from harness.skills.memory import list_memories


def main() -> int:
    print("=== BEFORE (no user turn -- the heartbeat will act on its own) ===")
    print(list_memories())
    before = len(list_memories().splitlines())

    fired = {"n": 0}
    ticks = {"n": 0}

    def on_tool(name, args, result):
        fired["n"] += 1
        print(f"   >> {name}({args}) -> {result!r}")

    def on_round(i, text):
        ticks["n"] += 1
        print(f"  [tick {i}] {' '.join(text.split())[:140]}")

    print("\n=== KAIROS TICK (interval 2s, 1 round, idle-gate off for determinism) ===")
    n = run_agency_scheduler(interval=2.0, rounds=1, idle_gate=False, on_round=on_round, on_tool=on_tool)

    print("\n=== AFTER ===")
    after_txt = list_memories()
    print(after_txt)
    after = len(after_txt.splitlines())
    low = after_txt.lower()

    tick_fired = n == 1 and ticks["n"] >= 1
    curated = after < before and ("has a dog named rex" in low) and \
        (sum("dog" in ln.lower() for ln in after_txt.splitlines()) == 1) and ("knack" in low)
    ok = tick_fired and curated
    print(f"\nticks_executed={n} tool_calls={fired['n']} facts {before}->{after}")
    print(f"G-HARNESS-KAIROS-TICK-E2E: {'PASS' if ok else 'PARTIAL/FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
