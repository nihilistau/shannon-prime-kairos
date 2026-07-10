"""G-HARNESS-CONVMEM-E2E -- tiered conversation memory + capabilities on MEM-OKF.

Seeds the capabilities corpus, consolidates a conversation (extract facts -> mid-term
registry; store full + summary -> long-term, sha-linked), recalls the gist, digs into
the full transcript, and verifies MEM-OKF integrity. Requires the daemon up on :3000.

    python tests/g_conversation_memory_e2e.py
"""
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_TMP = tempfile.mkdtemp(prefix="sp_convmem_")
os.environ["SP_CONV_OKF_ROOT"] = os.path.join(_TMP, "conv")
os.environ["SP_CAPS_OKF_ROOT"] = os.path.join(_TMP, "caps")
os.environ["SP_RECALL_REGISTRY"] = os.path.join(_TMP, "registry.jsonl")
os.environ["SP_DAEMON_URL"] = "http://127.0.0.1:59999"  # remember() append-only (fast); model calls use :3000
open(os.environ["SP_RECALL_REGISTRY"], "w").close()

from harness.skills import conversation_memory as cm


def main() -> int:
    print("=== CAPABILITIES corpus ===")
    addrs = cm.seed_capabilities()
    print(f"seeded {len(addrs)} capability objects")
    print("recall_capability('python') ->", cm.recall_capability("python"))
    print("init_primer (head) ->", " | ".join(cm.init_primer().splitlines()[:2]))

    print("\n=== CONVERSATION consolidation (short -> mid + long) ===")
    convo = [
        {"role": "system", "content": "(system seed)"},
        {"role": "user", "content": "My favorite animal is the octopus."},
        {"role": "assistant", "content": "The octopus, noted."},
        {"role": "user", "content": "I also really like jazz music."},
        {"role": "assistant", "content": "Jazz, got it."},
    ]
    res = cm.consolidate_conversation(convo)
    print("extracted facts (mid-term):")
    for f, r in res["facts"]:
        print(f"   - {f}   [{r[:40]}]")
    addr = res["conversation_addr"]
    print("conversation stored at addr:", addr)

    print("\n=== RECALL the gist, then DIG into the full ===")
    gist = cm.recall_conversations("octopus")
    print("recall_conversations('octopus') ->", gist)
    full = cm.read_conversation(addr)
    print("read_conversation(full) ->", " ".join(full.split())[:160])

    print("\n=== MEM-OKF integrity ===")
    v = subprocess.run(
        [sys.executable, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools", "okf_mem.py"),
         "verify", "--root", os.environ["SP_CONV_OKF_ROOT"]],
        capture_output=True, text=True)
    print(v.stdout.strip().splitlines()[-1] if v.stdout.strip() else "(no verify output)")

    ok = (len(addrs) > 0 and bool(addr) and "octopus" in gist.lower()
          and "octopus" in full.lower() and "GREEN" in v.stdout)
    print(f"\nG-HARNESS-CONVMEM-E2E: {'PASS' if ok else 'PARTIAL/FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
