"""G-PK2-MEMOKF-V2 (offline) — the MEM-OKF v2 provenance lane (§M1) + near-dup extraction
guard (§M2) + registry hygiene (§M3), all without the daemon.

    python tests/g_pk2_memokf_v2_offline.py
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REG = os.path.join(tempfile.gettempdir(), "sp_pk2_memv2.jsonl")
os.environ["SP_RECALL_REGISTRY"] = REG
os.environ["SP_DAEMON_URL"] = "http://127.0.0.1:59999"  # unreachable -> remember() append-only, fast
open(REG, "w").close()

from harness.skills.memory import (remember, provenance, verify_registry,
                                   compact_registry, list_memories, count_memories)


def check(name, ok):
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    return ok


def main() -> int:
    res = []

    # §M1 provenance: store with a source, then recall WHERE it came from.
    remember("The user's name is Knack.", source="operator")
    remember("The user's favorite color is teal.", source="user turn")
    pr = provenance("what is my name")
    res.append(check("provenance recites source", "operator" in pr and "Knack" in pr))
    pr2 = provenance("favorite color")
    res.append(check("provenance recites the right fact", "teal" in pr2 and "user turn" in pr2))

    # §M2 near-dup guard: a paraphrase of an existing fact is NOT stored again.
    before = int(count_memories())
    r = remember("Knack is the user's name.")     # paraphrase of fact #1
    after = int(count_memories())
    res.append(check("near-dup paraphrase rejected", after == before and "paraphrase" in r.lower()))

    # A genuinely new fact IS stored.
    r2 = remember("The user lives in Australia.", source="user turn")
    res.append(check("new fact still stored", "stored" in r2 and int(count_memories()) == before + 1))

    # §M3 hygiene: inject a malformed line + an exact dup, verify flags them, compact fixes.
    with open(REG, "a", encoding="utf-8") as f:
        f.write("{not valid json\n")
        f.write(json.dumps({"text": "The user's name is Knack.", "dir": "", "npos": 0}) + "\n")  # exact dup
    v = verify_registry()
    res.append(check("verify flags malformed + dup", "malformed=1" in v and "NEEDS COMPACTION" in v))
    c = compact_registry()
    v2 = verify_registry()
    res.append(check("compact removes them", "OK" in v2 and "malformed=0" in v2 and "exact_dups=0" in v2))

    print("\nfinal memory:\n" + list_memories())
    ok = all(res)
    print(f"\nG-PK2-MEMOKF-V2 (offline): {'PASS' if ok else 'FAIL'} ({sum(res)}/{len(res)})")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
