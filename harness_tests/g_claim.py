"""G-CLAIM — an inference is not testimony, a slot is not a subject, and a tombstone is dead
on EVERY path.

Three bugs, one gate, because they are the same bug wearing three coats: A RULE THAT WAS TRUE
IN ONE PLACE AND NOT IN THE PLACE THAT RAN.

  1. THE SLOT COLLISION.  attribute_key() keyed on the words before the copula, so every
     "Knack is X" fact landed in ONE slot and superseded the last. Two things he SAID, on
     unrelated topics:
         stored: Knack is terrified of open water
         stored: Knack is a cat person (superseded: 'Knack is terrified of open water')
     The cat ate the water. And reflection only ever writes in that shape, so every conclusion
     she ever drew about him destroyed the one before it: she could hold exactly ONE belief
     about who he is at a time. Properties accumulate. Only ATTRIBUTES ("my GPU is ...") are
     slots with values.

  2. THE BYPASSED LIFECYCLE.  search_memories_ranked_rows() never filtered tombstones; it left
     that to its callers. recall() remembered. spine.recall_decider() — the AUTOMATIC recall,
     the one that runs EVERY TURN — did not. So the entire supersede system was live only when
     she chose to call the tool, and the path that actually feeds her context was injecting
     superseded facts ABOVE the truth.

  3. TESTIMONY OUTRANKS INFERENCE.  She may be wrong about him. She may not say it OVER him.
     Enforced at the recall seam, not by a write-time verdict — because I cannot detect semantic
     contradiction with string operations, and a verdict I cannot defend is a lie with a
     timestamp on it.

Every assertion below is on the REAL code path (spine.recall_decider), never on a helper called
by hand. A gate that calls the guarded function directly proves only that the guard compiles.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["SP_DAEMON_URL"] = "http://127.0.0.1:9"      # discard port: never needs a GPU
_fd, _reg = tempfile.mkstemp(suffix=".jsonl")
os.close(_fd)
os.environ["SP_RECALL_REGISTRY"] = _reg

from harness.skills import memory as M                  # noqa: E402
from harness.skills import lifecycle as lc              # noqa: E402
from harness.control.spine import recall_decider, TurnView  # noqa: E402

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok   %s" % name)
    else:
        FAIL += 1
        print("  FAIL %s   %s" % (name, detail))


def injected(q, min_overlap=0.34):
    """WHAT ACTUALLY REACHES HER CONTEXT. The real decider, not a hand-called helper."""
    out = []
    for d in recall_decider(min_overlap=min_overlap)._fn(
            TurnView(phase="pre", user_text=q)):
        out += d.payload.get("facts", [])
    return out


def reset():
    open(_reg, "w").close()


# ── 1. A PROPERTY IS NOT AN ATTRIBUTE ─────────────────────────────────────────────────
print("\n1. properties accumulate; attributes supersede")
reset()
M.remember("Knack is terrified of open water", source="user turn")
M.remember("Knack is a cat person", source="user turn")
M.remember("Knack is deeply curious about how things work", source="user turn")
live = [r["text"] for r in M._load() if not r.get("lifecycle")]
check("three unrelated things he said all survive", len(live) == 3, live)
check("the water fact was not eaten by the cat",
      "Knack is terrified of open water" in live, live)

reset()
M.remember("My GPU is an RTX 2060", source="user turn")
M.remember("My GPU is an RTX 3090", source="user turn")
rows = M._load()
live = [r["text"] for r in rows if not r.get("lifecycle")]
check("but an ATTRIBUTE still has one value (3090 supersedes 2060)",
      live == ["My GPU is an RTX 3090"], live)
check("and the old value is TOMBSTONED, not deleted",
      any(r.get("lifecycle") and r["text"] == "My GPU is an RTX 2060" for r in rows),
      [r["text"] for r in rows])
check("attribute_key: a possessed thing IS a slot",
      lc.attribute_key("My GPU is an RTX 3090", "user") == "user::gpu")
check("attribute_key: a bare subject is NOT a slot",
      lc.attribute_key("Knack is a cat person", "user") is None)
check("attribute_key: two properties do not collide",
      lc.attribute_key("Knack is a cat person", "user")
      == lc.attribute_key("Knack is terrified of open water", "user") is None)


# ── 2. A TOMBSTONE IS DEAD ON THE PATH THAT RUNS ──────────────────────────────────────
print("\n2. the tombstone is dead on the AUTOMATIC path, not just the polite one")
reset()
M.remember("My GPU is an RTX 2060", source="user turn")
M.remember("My GPU is an RTX 3090", source="user turn")
got = injected("what GPU do I have?")
check("the superseded card is NOT injected into her context",
      "My GPU is an RTX 2060" not in got, got)
check("the live card IS", "My GPU is an RTX 3090" in got, got)
check("the recall() TOOL agrees with the automatic path",
      "3090" in M.recall("what GPU do I have") and "2060" not in M.recall("what GPU do I have"))
check("the seam filters, so no caller can forget",
      all(not e.get("lifecycle")
          for _s, e in M.search_memories_ranked_rows("GPU", k=9, min_overlap=0.1)))
check("...but the audit lane may still ASK for the dead",
      any(e.get("lifecycle")
          for _s, e in M.search_memories_ranked_rows("GPU", k=9, min_overlap=0.1,
                                                     include_retired=True)))


# ── 3. SHE MAY BE WRONG ABOUT HIM. SHE MAY NOT SAY IT OVER HIM. ───────────────────────
print("\n3. testimony outranks inference — at the mouth, not at the disk")
reset()
M.remember("Knack is terrified of open water", source="user turn")
M.remember("Knack is comfortable in open water", source="reflection")
M.remember("Knack is deeply curious about how things work", source="reflection")

rows = M._load()
check("the inference is STORED (nothing is ever destroyed)",
      any(r["text"] == "Knack is comfortable in open water" for r in rows))
check("it is stored LIVE and INFERRED — not convicted, not tombstoned",
      any(r["text"] == "Knack is comfortable in open water"
          and not r.get("lifecycle") and r.get("status") == lc.STATUS_INFERRED
          for r in rows),
      [(r.get("status"), r.get("lifecycle")) for r in rows])
check("his testimony is OBSERVED",
      any(r["text"] == "Knack is terrified of open water"
          and r.get("status") == lc.STATUS_OBSERVED for r in rows))

got = injected("how do I feel about open water?", min_overlap=0.25)
check("HE speaks about the water", "Knack is terrified of open water" in got, got)
check("SHE DOES NOT ARGUE WITH HIM ABOUT IT",
      "Knack is comfortable in open water" not in got, got)

got = injected("is Knack curious about how things work?", min_overlap=0.25)
check("but on a subject he never spoke to, her inference DOES speak",
      "Knack is deeply curious about how things work" in got, got)

check("an inference may never retire an observation",
      lc.find_superseded("Knack is comfortable in open water", "user", rows,
                         status=lc.STATUS_INFERRED) == [])
check("an observation MAY correct an inference",
      [r["text"] for r in lc.find_superseded("My GPU is an RTX 4090", "user",
                                             [{"text": "My GPU is an RTX 3090",
                                               "speaker": "user",
                                               "status": lc.STATUS_INFERRED}],
                                             status=lc.STATUS_OBSERVED)]
      == ["My GPU is an RTX 3090"])

check("topic_of strips the grammar and the name",
      lc.topic_of("Knack is terrified of open water") == frozenset({"terrified", "open", "water"}),
      lc.topic_of("Knack is terrified of open water"))
check("two claims about the same thing share a topic",
      len(lc.topic_of("Knack is terrified of open water")
          & lc.topic_of("Knack is comfortable in open water")) >= 2)
check("two claims about different things do not",
      len(lc.topic_of("Knack is a cat person")
          & lc.topic_of("Knack is terrified of open water")) == 0)


# ── 4. THE DEAD HELPER STAYS DEAD ─────────────────────────────────────────────────────
print("\n4. the undefendable verdict is gone and does not come back")
check("find_contradicted() no longer exists (it could not do what its name said)",
      not hasattr(lc, "find_contradicted"))
check("nothing writes DISPUTED from a string comparison",
      all(r.get("status") != lc.STATUS_DISPUTED for r in M._load()))

os.unlink(_reg)
print("\nG-CLAIM  %d/%d" % (PASS, PASS + FAIL))
sys.exit(1 if FAIL else 0)
