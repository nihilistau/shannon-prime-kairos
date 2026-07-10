"""G-PF-TAGS (PF-B3) — self-modify via tags: the model emits [MOOD]/[VOICE]/[TRAIT] in its reply;
a post-call interceptor persists them into the persona state (write_state) and strips them from the
reply, so the change survives to the next turn."""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness.personality import interceptor as I
from harness.personality.persona_file import parse_persona
from harness.inference.stream_processor import _STRIP as SP_STRIP

GATE = Path(tempfile.gettempdir()) / "_pf_tags_gate"
PERSONA = GATE / "persona.md"

BASE = ("# Shannon-Prime\n\nYou are Shannon-Prime.\n\n"
        "## Personality state\nvoice: dry\nmood: neutral\ntraits: curious, formal\n")
REPLY = ("Sure thing. [MOOD:playful] Let me [VOICE:whisper] help — [TRAIT:+mischievous] "
         "[TRAIT:-formal] here you go.")


def state_of():
    _, st = parse_persona(PERSONA.read_text(encoding="utf-8"))
    return st


def main() -> int:
    if GATE.exists():
        shutil.rmtree(GATE)
    GATE.mkdir(parents=True)
    PERSONA.write_text(BASE, encoding="utf-8")

    clean, result = I.apply_personality_tags(REPLY, str(PERSONA))
    st = state_of()
    traits = [t.strip() for t in st.get("traits", "").split(",") if t.strip()]

    mood_ok = st.get("mood") == "playful"
    voice_ok = st.get("voice") == "whisper"
    trait_add = "mischievous" in [t.lower() for t in traits]
    trait_rm = "formal" not in [t.lower() for t in traits]
    trait_keep = "curious" in [t.lower() for t in traits]     # untouched trait preserved
    stripped = "[" not in clean and "MOOD" not in clean and "TRAIT" not in clean
    print(f"persisted state: {st}")
    print(f"clean reply: {clean!r}")
    print(f"mood={mood_ok} voice={voice_ok} trait_add={trait_add} trait_rm={trait_rm} keep={trait_keep} stripped={stripped}")

    # interceptor wrapper: mock ctx (any object with a .reply attr) -> post_call strips + persists
    class Ctx:
        reply = REPLY
    PERSONA.write_text(BASE, encoding="utf-8")  # reset for the interceptor path
    os.environ["SP_PERSONA_FILE"] = str(PERSONA)
    interc = I.make_interceptor()
    ctx = Ctx()
    interc.post_call(ctx)
    interc_ok = "[" not in ctx.reply and state_of().get("mood") == "playful"
    print(f"interceptor: priority={interc.priority} name={interc.name} reply_stripped+persisted={interc_ok}")

    # StreamProcessor now strips [TRAIT] on the chat-delta path too
    sp_ok = SP_STRIP.sub("", "hi [TRAIT:+bold] there") == "hi  there"

    ok = mood_ok and voice_ok and trait_add and trait_rm and trait_keep and stripped and interc_ok and sp_ok
    print(f"RESULT pf-tags: {'PASS' if ok else 'FAIL'} "
          f"(tags persisted to state + stripped from reply + interceptor + StreamProcessor strips TRAIT)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
