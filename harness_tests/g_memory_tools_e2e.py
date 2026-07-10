"""G-HARNESS-MEMTOOLS-E2E -- the served model manages its own memory via tools.

list_memories / remember / forget exposed as ephemeral tools over the daemon's
persistent registry. Two phases: a DIRECT curation cycle (no model) proving the
tools, then a MODEL-driven call proving the served 12B invokes a memory tool.
Uses an ISOLATED test registry so the live daemon's store is undisturbed.

    python tests/g_memory_tools_e2e.py     (daemon up on :3000)
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Isolated registry (set BEFORE the tools read it at call time).
TESTREG = os.path.join(tempfile.gettempdir(), "sp_memtools_test.jsonl")
os.environ["SP_RECALL_REGISTRY"] = TESTREG
with open(TESTREG, "w", encoding="utf-8") as _f:
    _f.write(json.dumps({"name": "t0", "dir": "", "npos": 0, "topic": "", "text": "The user's name is Knack."}) + "\n")
    _f.write(json.dumps({"name": "t1", "dir": "", "npos": 0, "topic": "", "text": "Shannon-Prime runs on an RTX 2060 graphics card."}) + "\n")

from harness.skills.memory import list_memories, remember, forget, MEMORY_TOOLS
from harness.mcp.tools import ToolSpec, run_with_tools
from harness.inference.inference_config import InferenceConfig


def main() -> int:
    print("=== DIRECT: introspect -> store -> curate ===")
    os.environ["SP_DAEMON_URL"] = "http://127.0.0.1:59999"  # unreachable => remember append-only (fast)
    print("[list]\n" + list_memories())
    print("[remember] ->", remember("The user's favorite color is teal."))
    print("[list]\n" + list_memories())
    print("[forget 'graphics card'] ->", forget("graphics card"))
    print("[list]\n" + list_memories())

    print("\n=== MODEL: the served 12B calls a memory tool ===")
    cfg = InferenceConfig(temperature=0.0, max_tokens=160, auto_recall=False)
    tools = [ToolSpec.from_callable(fn) for fn in MEMORY_TOOLS]
    fired = {"n": 0}

    def on_tool(name, args, result):
        fired["n"] += 1
        print(f"   >> {name}({args}) -> {result!r}")

    ans = run_with_tools(
        [{"role": "user", "content": "What facts are in your memory right now? Use the list_memories tool, then list them back to me."}],
        tools, config=cfg, on_tool=on_tool, max_rounds=3,
    )
    print("FINAL:", " ".join(ans.split())[:300])

    ok = fired["n"] > 0
    print(f"\nG-HARNESS-MEMTOOLS-E2E: {'PASS' if ok else 'FAIL'} (memory tool calls: {fired['n']})")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
