"""G-HARNESS-HOOK-E2E -- the full live loop: the daemon writes the current conversation each
turn (SP_CURRENT_CONVO), and the scheduler's consolidation reads THAT file and tiers it."""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_TMP = tempfile.mkdtemp(prefix="sp_hook_")
os.environ["SP_RECALL_REGISTRY"] = os.path.join(_TMP, "reg.jsonl"); open(os.environ["SP_RECALL_REGISTRY"], "w").close()
os.environ["SP_CONV_OKF_ROOT"] = os.path.join(_TMP, "conv")
os.environ["SP_DAEMON_URL"] = "http://127.0.0.1:59999"  # remember() append-only (fast); model calls use :3000

from harness.control.agency import consolidate_current

DAEMON_FILE = r"D:\F\shannon-prime-repos\shannon-prime-system-engine\_current_conversation.json"
print("reading daemon-written file:", DAEMON_FILE)
res = consolidate_current(DAEMON_FILE)
facts = [f for f, _ in res["facts"]] if res else []
addr = res["conversation_addr"] if res else None
print("facts (mid-term):", facts)
print("conversation addr (long-term):", addr)
ok = bool(res) and bool(facts) and bool(addr)
print("G-HARNESS-HOOK-E2E:", "PASS" if ok else "FAIL")
