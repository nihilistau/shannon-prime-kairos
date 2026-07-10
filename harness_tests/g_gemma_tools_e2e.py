"""G-HARNESS-GEMMA-TOOLS-E2E -- Gemma-native (```tool_code```) tool calling + the new tools
(filesystem, shell, web, count_memories) on the live served 12B. Daemon up on :3000."""
import os, sys, tempfile, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# count_memories needs a registry; point at a small test one so the count is deterministic.
TR = os.path.join(tempfile.gettempdir(), "sp_gemmatools_reg.jsonl")
with open(TR, "w", encoding="utf-8") as f:
    for t in ["The user's name is Knack.", "Shannon-Prime runs locally."]:
        f.write(json.dumps({"name": "x", "dir": "", "npos": 0, "topic": "", "text": t}) + "\n")
os.environ["SP_RECALL_REGISTRY"] = TR

from harness.mcp.tools import ToolSpec, run_with_tools, _tool_preamble
from harness.skills.system_tools import list_dir, run_shell, web_search
from harness.skills.memory import count_memories
from harness.inference.inference_config import InferenceConfig

cfg = InferenceConfig(temperature=0.0, max_tokens=220, auto_recall=False)
tools = [ToolSpec.from_callable(t) for t in [list_dir, run_shell, web_search, count_memories]]

print("=== Gemma tool preamble (what the model sees) ===")
print(_tool_preamble(tools)[:700])

fired = {"n": 0}
def on_tool(name, a, r):
    fired["n"] += 1
    print(f"   >> TOOL {name}({a}) -> {repr(r)[:140]}", flush=True)

tests = [
    "How many facts do you have in your memory right now? Use the count_memories tool, then tell me the number.",
    "List the files in the current working directory using the list_dir tool, then name two of them.",
]
for q in tests:
    print("=" * 64); print("Q:", q)
    ans = run_with_tools([{"role": "user", "content": q}], tools, config=cfg, on_tool=on_tool, max_rounds=3)
    print("FINAL:", " ".join(ans.split())[:240], flush=True)

print(f"\nG-HARNESS-GEMMA-TOOLS-E2E: {'PASS' if fired['n'] > 0 else 'FAIL'} (tool calls fired: {fired['n']})")
