"""G-PF-CURATE (PF-B5) — NIGHTSHIFT personality curation: extract the shifts the model expressed in
a transcript, prune duplicate/stale traits, and snapshot the personality into a content-addressed
memory-okf-personality tier. Personality becomes system-curatable + recoverable."""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness.personality import curator as C
from harness.personality.persona_file import parse_persona

GATE = Path(tempfile.gettempdir()) / "_pf_curate_gate"
PERSONA = GATE / "persona.md"
TIER = GATE / "personality"
# note the DUPLICATE "curious" + a "terse" the model will drop mid-conversation
BASE = ("# Shannon-Prime\n\nYou are Shannon-Prime.\n\n"
        "## Personality state\nvoice: dry\nmood: neutral\ntraits: curious, formal, curious, terse\n")

# a transcript where the model expressed personality shifts in its turns
MESSAGES = [
    {"role": "user", "content": "That was heavy. Can we slow down?"},
    {"role": "assistant", "content": "Of course. [MOOD:reflective] [VOICE:gentle] "
                                     "[TRAIT:+patient] [TRAIT:-terse] Take your time."},
    {"role": "user", "content": "Thanks."},
    {"role": "assistant", "content": "I'm here."},
]


def main() -> int:
    if GATE.exists():
        shutil.rmtree(GATE)
    GATE.mkdir(parents=True)
    PERSONA.write_text(BASE, encoding="utf-8")

    r = C.consolidate_personality(MESSAGES, persona_path=str(PERSONA), tier_root=str(TIER))
    _, state = parse_persona(PERSONA.read_text(encoding="utf-8"))
    traits = [t.strip().lower() for t in state.get("traits", "").split(",") if t.strip()]

    # extracted shifts from the transcript
    mood_ok = state.get("mood") == "reflective"
    voice_ok = state.get("voice") == "gentle"
    trait_add = "patient" in traits
    trait_rm = "terse" not in traits
    # pruned the duplicate "curious"
    dedup_ok = traits.count("curious") == 1 and r["pruned"] >= 1
    # snapshot written as an OKF concept in the personality tier
    snap = TIER / "full" / f"{r['snapshot_addr']}.md"
    snap_ok = snap.exists() and "mem_class: persona" in snap.read_text(encoding="utf-8") \
        and "mem_owner: self" in snap.read_text(encoding="utf-8")

    print(f"result: {r}")
    print(f"state: {state}  traits={traits}")
    print(f"mood={mood_ok} voice={voice_ok} trait_add={trait_add} trait_rm={trait_rm} "
          f"dedup={dedup_ok} snapshot={snap_ok}")
    ok = mood_ok and voice_ok and trait_add and trait_rm and dedup_ok and snap_ok
    print(f"RESULT pf-curate: {'PASS' if ok else 'FAIL'} "
          f"(extract shifts from transcript + prune duplicate traits + OKF snapshot)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
