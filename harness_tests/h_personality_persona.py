"""G-PF-PERSONA (PF-B2) — structured, live-editable persona.md: load_agent_system splits the VOICE
prose from the machine-parseable ## Personality state block, injects the current state (voice/mood/
traits) + the PF-B1 self-model, edits reflect live, and a malformed block falls back gracefully."""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ["CUDA_VISIBLE_DEVICES"] = ""
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness.personality import persona_file as PF
from harness.personality.self_model import SelfModelStore

GATE = Path(tempfile.gettempdir()) / "_pf_persona_gate"
PERSONA = GATE / "persona.md"
SELF = GATE / "self"

PROSE = ("# Shannon-Prime\n\nYou are Shannon-Prime, a particular someone made of math.\n\n"
         "## How you talk\nLike someone, not a manual.\n")
STATE_BLOCK = "## Personality state\nvoice: dry, warm\nmood: neutral\ntraits: curious, candid\n"


def load():
    # import inside so env vars are picked up per call
    from harness.agent import load_agent_system
    return load_agent_system()


def main() -> int:
    if GATE.exists():
        shutil.rmtree(GATE)
    GATE.mkdir(parents=True)
    PERSONA.write_text(PROSE + "\n" + STATE_BLOCK, encoding="utf-8")
    os.environ["SP_PERSONA_FILE"] = str(PERSONA)
    os.environ["SP_SELF_MODEL_ROOT"] = str(SELF)
    SelfModelStore(SELF).remember_self("I can read and write memories.")

    s = load()
    prose_ok = "particular someone made of math" in s
    state_ok = ("Current personality state" in s and "voice: dry, warm" in s
                and "mood: neutral" in s and "traits: curious, candid" in s)
    header_stripped = "## Personality state" not in s   # the raw block header must not leak in
    selfmodel_ok = "About yourself (self-model)" in s and "read and write memories" in s
    print(f"prose_ok={prose_ok} state_ok={state_ok} header_stripped={header_stripped} self_model_ok={selfmodel_ok}")

    # live edit: the model/system changes mood via write_state -> next load reflects it
    PF.write_state(str(PERSONA), {"voice": "dry, warm", "mood": "playful", "traits": "curious, candid"})
    s2 = load()
    edit_ok = "mood: playful" in s2 and "particular someone made of math" in s2  # prose preserved
    print(f"live edit -> mood:playful reflected={('mood: playful' in s2)} prose preserved={('math' in s2)}")

    # malformed block -> graceful fallback (prose still loads, no crash)
    PERSONA.write_text(PROSE + "\n## Personality state\n@@@ not key value @@@\n", encoding="utf-8")
    s3 = load()
    graceful = "particular someone made of math" in s3
    print(f"malformed block -> graceful (prose loads)={graceful}")

    ok = prose_ok and state_ok and header_stripped and selfmodel_ok and edit_ok and graceful
    print(f"RESULT pf-persona: {'PASS' if ok else 'FAIL'} "
          f"(state parsed+injected + self-model + live-edit + graceful fallback)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
