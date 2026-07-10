"""G-HARNESS-CONSOLIDATE: the scheduler's consolidation step reads the current-conversation
document and tiers it (facts -> mid, transcript -> long). Isolated stores so the served
registry is undisturbed; the remember()/MEM-OKF mechanism is the same one used live."""
import json, os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_TMP = tempfile.mkdtemp(prefix="sp_consol_")
os.environ["SP_RECALL_REGISTRY"] = os.path.join(_TMP, "reg.jsonl"); open(os.environ["SP_RECALL_REGISTRY"], "w").close()
os.environ["SP_CONV_OKF_ROOT"] = os.path.join(_TMP, "conv")
os.environ["SP_DAEMON_URL"] = "http://127.0.0.1:59999"  # remember() append-only (fast); model calls use :3000

convo = [
    {"role": "system", "content": "(sys)"},
    {"role": "user", "content": "My favorite animal is the octopus."},
    {"role": "assistant", "content": "Noted."},
    {"role": "user", "content": "I also really like jazz music."},
    {"role": "assistant", "content": "Got it."},
]
CF = os.path.join(_TMP, "current_conversation.json")
json.dump(convo, open(CF, "w", encoding="utf-8"))

from harness.control.agency import consolidate_current
from harness.skills.conversation_memory import recall_conversations, read_conversation

res = consolidate_current(CF)
facts = [f for f, _ in res["facts"]]
addr = res["conversation_addr"]
print("facts (mid-term):", facts)
print("conversation addr (long-term):", addr)
gist = recall_conversations("octopus")
print("recall gist:", gist)
full = read_conversation(addr)
ok = bool(facts) and bool(addr) and "octopus" in gist.lower() and "octopus" in full.lower()
print("G-HARNESS-CONSOLIDATE:", "PASS" if ok else "PARTIAL/FAIL")
