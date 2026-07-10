"""G-PK2-TASKLOOP-E2E — the live agentic coding loop (§T2-E1) on the served 12B.

Seeds a workspace with a buggy module + a test that fails, gives the organism the goal
"make the tests pass", and asserts run_task drives edit_file/run_tests to a real green.
Requires the daemon up on :3000.

    python tests/g_pk2_taskloop_e2e.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ws = tempfile.mkdtemp(prefix="pk2taskE2E_")
os.environ["HARNESS_WORKSPACE"] = ws
os.environ["SP_TASK_ROOT"] = tempfile.mkdtemp(prefix="pk2taskstate_")

# Seeded bug: add() subtracts. A pytest asserts add(2,3)==5. The organism must fix add().
with open(os.path.join(ws, "calc.py"), "w", encoding="utf-8") as f:
    f.write("def add(a, b):\n    return a - b\n")
with open(os.path.join(ws, "test_calc.py"), "w", encoding="utf-8") as f:
    f.write("from calc import add\n\ndef test_add():\n    assert add(2, 3) == 5\n")

from harness.control.task_loop import run_task


def main() -> int:
    print(f"workspace: {ws}")
    print("goal: make the failing test pass (add() has a seeded bug)\n")

    def on_tool(name, args, result):
        print(f"   >> {name}({args.get('args')}, {args.get('kwargs')}) -> {result[:120]!r}")

    def on_step(state):
        s = state.steps[-1]
        print(f"[step {s.n}] {state.status}: {s.action.strip()[:100]}")

    import subprocess as _sp
    def _verify():
        r = _sp.run([sys.executable, "-m", "pytest", "-q", ws],
                    capture_output=True, text=True, timeout=60)
        return r.returncode == 0

    state = run_task(
        "The test_calc.py test is failing because add() in calc.py has a bug. "
        "Fix calc.py so the test passes, then run the tests to confirm.",
        max_steps=6, budget_s=300.0, verify=_verify, on_tool=on_tool, on_step=on_step)

    # Ground truth: read the file the model edited + run pytest ourselves.
    src = open(os.path.join(ws, "calc.py"), encoding="utf-8").read()
    import subprocess
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", ws],
                       capture_output=True, text=True, timeout=120)
    tests_green = r.returncode == 0
    fixed = "a + b" in src or "a+b" in src

    print(f"\ncalc.py now: {src!r}")
    print(f"status={state.status} steps={len(state.steps)} fixed={fixed} tests_green={tests_green}")
    ok = tests_green and fixed
    print(f"G-PK2-TASKLOOP-E2E: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
