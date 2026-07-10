"""G-HARNESS-AGENCY-E2E -- the model autonomously maintains its own memory.

Seed an isolated registry with a REDUNDANT pair, run one agency round, and watch
the served 12B decide for itself to forget the redundant fact -- composing tool
calling + memory tools into self-curation. Requires the daemon up on :3000.

    python tests/g_agency_loop_e2e.py
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TESTREG = os.path.join(tempfile.gettempdir(), "sp_agency_test.jsonl")
os.environ["SP_RECALL_REGISTRY"] = TESTREG
os.environ["SP_DAEMON_URL"] = "http://127.0.0.1:59999"  # remember() append-only (fast); forget is local
SEED = [
    "The user has a dog.",
    "The user has a dog named Rex.",
    "The user's name is Knack.",
]
with open(TESTREG, "w", encoding="utf-8") as _f:
    for i, t in enumerate(SEED):
        _f.write(json.dumps({"name": f"s{i}", "dir": "", "npos": 0, "topic": "", "text": t}) + "\n")

from harness.control.agency import agency_round
from harness.skills.memory import list_memories


def _facts():
    return [ln for ln in list_memories().splitlines()]


def main() -> int:
    print("=== BEFORE (redundant: 'has a dog' subsumed by 'has a dog named Rex') ===")
    print(list_memories())
    before = len(_facts())

    fired = {"n": 0}

    def on_tool(name, args, result):
        fired["n"] += 1
        print(f"   >> {name}({args}) -> {result!r}")

    print("\n=== AGENCY ROUND (the model reviews + curates) ===")
    closing = agency_round(on_tool=on_tool)
    print("MODEL:", " ".join(closing.split())[:240])

    print("\n=== AFTER ===")
    after_txt = list_memories()
    print(after_txt)
    after = len([ln for ln in after_txt.splitlines()])

    low = after_txt.lower()
    # PASS: the model acted (a tool fired) AND the redundant vague fact is gone while the
    # specific one + the unrelated fact remain.
    redundant_gone = ("has a dog named rex" in low) and (sum("dog" in ln.lower() for ln in after_txt.splitlines()) == 1)
    knack_kept = "knack" in low
    ok = fired["n"] > 0 and after < before and redundant_gone and knack_kept
    print(f"\nfacts {before} -> {after}; redundant_gone={redundant_gone} knack_kept={knack_kept}")
    print(f"G-HARNESS-AGENCY-E2E: {'PASS' if ok else 'PARTIAL/FAIL'} (tool calls: {fired['n']})")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
