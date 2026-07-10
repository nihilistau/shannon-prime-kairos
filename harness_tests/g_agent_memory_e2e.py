"""G-HARNESS-AGENT-MEMORY-E2E -- the model CALLS its memory tools in a conversation.

The unification fix: route the chat through agent_chat (run_with_tools), so the model
manages its own memory by emitting Gemma ```tool_code calls (remember/count/forget) -- its
choice, in the chat -- instead of the daemon's heuristic SP_FORGET/SP_DECIDE. Daemon up on :3000.
"""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TR = os.path.join(tempfile.gettempdir(), "sp_agent_reg.jsonl")
open(TR, "w").close()  # start empty
os.environ["SP_RECALL_REGISTRY"] = TR
os.environ["SP_DAEMON_URL"] = "http://127.0.0.1:59999"  # remember() append-only (fast, no mint)

from harness.agent import agent_chat, memory_tools
from harness.skills.memory import list_memories

tools = memory_tools()
history = []
all_fired = []

def turn(u):
    history.append({"role": "user", "content": u})
    fired = []
    def on_tool(n, a, r):
        fired.append(n); all_fired.append(n)
        print(f"   >> {n}({a}) -> {repr(r)[:80]}", flush=True)
    r = agent_chat(history, tools=tools, on_tool=on_tool)
    history.append({"role": "assistant", "content": r})
    print(f"USER: {u}\n  AI: {' '.join(r.split())[:160]}\n   (tools called: {fired})\n", flush=True)

turn("Please remember that my favorite color is teal.")
turn("How many facts do you have in your memory right now?")
turn("Actually, my favorite color is green now.")

print("=== FINAL MEMORY (registry) ===")
print(list_memories())
ok = "remember" in all_fired and "count_memories" in all_fired
print(f"\nG-HARNESS-AGENT-MEMORY-E2E: {'PASS' if ok else 'PARTIAL/FAIL'}  (tools called: {all_fired})")
