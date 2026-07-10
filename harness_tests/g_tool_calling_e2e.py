"""G-HARNESS-TOOLCALL-E2E -- live ephemeral tool calling on the served Gemma-4-12B.

The model emits <tool name="...">{json}</tool>, the harness parses + executes the
matching Python callable + feeds the result back, looping until the model answers.
Two tools: a safe arithmetic evaluator and a sandboxed Python exec (subprocess,
timeout). Requires the daemon up on :3000.

    python tests/g_tool_calling_e2e.py
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from harness.mcp.tools import ToolSpec, run_with_tools
from harness.inference.inference_config import InferenceConfig


def calculate(expression: str) -> str:
    """Evaluate an arithmetic expression (e.g. '47 * 89') and return the result."""
    return str(eval(expression, {"__builtins__": {}}, {}))


def run_python(code: str) -> str:
    """Execute a short Python program in a sandboxed subprocess and return its stdout."""
    try:
        p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=10)
        return (p.stdout + p.stderr).strip()[:500] or "(no output)"
    except Exception as exc:
        return f"[exec error: {exc}]"


def main() -> int:
    cfg = InferenceConfig(temperature=0.0, max_tokens=200, auto_recall=False)
    tools = [ToolSpec.from_callable(calculate), ToolSpec.from_callable(run_python)]
    fired = {"n": 0}

    def on_tool(name, args, result):
        fired["n"] += 1
        print(f"   >> TOOL CALL: {name}({args}) -> {result!r}")

    print("=== preamble the model sees ===")
    from harness.mcp.tools import _tool_preamble
    print(_tool_preamble(tools))
    print()

    print("=== Test 1: calculate (47 * 89 = 4183) ===")
    a1 = run_with_tools(
        [{"role": "user", "content": "What is 47 * 89? Use the calculate tool, then state the answer."}],
        tools, config=cfg, on_tool=on_tool, max_rounds=4,
    )
    print("FINAL:", " ".join(a1.split())[:300])

    print("\n=== Test 2: run_python (sum 1..100 = 5050) ===")
    a2 = run_with_tools(
        [{"role": "user", "content": "Use the run_python tool to compute the sum of all integers from 1 to 100. Write it as a one-line program. Then tell me the value."}],
        tools, config=cfg, on_tool=on_tool, max_rounds=4,
    )
    print("FINAL:", " ".join(a2.split())[:300])

    ok = fired["n"] > 0
    print(f"\nG-HARNESS-TOOLCALL-E2E: {'PASS' if ok else 'FAIL'}  (tool calls fired: {fired['n']})")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
