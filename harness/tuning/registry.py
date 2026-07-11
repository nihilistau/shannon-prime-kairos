"""TUNABLES — one declarative registry for every knob, so the UI never needs new code.

The operator's ask: "expose these things to the UI so that I can easily tune them later
if i need to. eg max_chain and eot_margin etc and anything else like that that has been
added or we will be adding."

The last clause is the design constraint. A hand-built settings page rots the moment a
knob is added — and this system's whole failure mode, four times over today, is a
capability that exists but is not REACHABLE. So: knobs are DECLARED here, once, and the
operator UI renders whatever it finds. Add a Knob to this list and it appears in the
panel, with its bounds, its help text, and its provenance. No UI edit. No endpoint edit.

PROVENANCE MATTERS. Every knob says where its default came from — measured, or chosen.
A number that was calibrated against the live model (kairos.continue_margin) is a very
different animal from one somebody felt was about right, and the operator deserves to see
which is which before he drags a slider.

Values live in var/tuning.json (operator overrides only; an unset knob keeps its default),
and are read live — no restart.
"""
from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STORE = os.path.join(ROOT, "var", "tuning.json")

_LOCK = threading.RLock()
_CACHE: Optional[dict] = None


@dataclass
class Knob:
    key: str                     # "kairos.continue_margin"
    group: str                   # UI section
    label: str
    type: str                    # "float" | "int" | "bool" | "enum"
    default: Any
    help: str
    min: Optional[float] = None
    max: Optional[float] = None
    step: Optional[float] = None
    choices: list = field(default_factory=list)
    # WHERE the default came from. "measured" = calibrated against the live model and
    # backed by a receipt; "chosen" = a judgement call. The UI shows this.
    provenance: str = "chosen"
    receipt: str = ""            # the gate/receipt that justifies a measured default
    danger: str = ""             # shown as a warning when the operator moves it


KNOBS: list[Knob] = [
    # ── KAIROS: when she speaks unprompted ────────────────────────────────────────
    Knob("kairos.enabled", "Kairos — speaking unprompted", "Enabled", "bool", False,
         "Master switch. Off = she only ever speaks when spoken to (today's behaviour)."),
    Knob("kairos.continue_margin", "Kairos — speaking unprompted",
         "Continue margin (logits)", "float", -11.75,
         "How reluctantly she must have stopped before she picks the thread back up. "
         "This is the RAW stop-vs-continue logit gap from the forward itself: turns she "
         "FINISHES sit around +2.8; turns GUILLOTINED mid-sentence sit around -14.1. "
         "Raise it toward 0 and she talks more (and starts talking over finished "
         "thoughts). Lower it and she is quieter.",
         min=-20.0, max=5.0, step=0.25,
         provenance="measured",
         receipt="tools/kairos/calibrate.py — 0/6 finished turns interrupted, 5/6 genuine "
                 "cut-offs resumed. Re-run after ANY change to eot_bias, sampler, or model.",
         danger="Above about -8 she will begin interrupting turns she had already finished."),
    Knob("kairos.max_chain", "Kairos — speaking unprompted", "Max unprompted in a row", "int", 1,
         "How many times she may speak unprompted before she MUST wait for you. 1 = she "
         "can continue a cut-off thought once, then it is your turn. This is the main "
         "guard against her talking forever.",
         min=1, max=3, step=1,
         danger="Above 1 she can monologue. Raise this only if you want that."),
    Knob("kairos.cooldown_s", "Kairos — speaking unprompted", "Cooldown (s)", "float", 45.0,
         "After speaking unprompted, she stays quiet at least this long.",
         min=0.0, max=600.0, step=5.0),
    Knob("kairos.max_per_hour", "Kairos — speaking unprompted", "Hard cap per hour", "int", 6,
         "Absolute ceiling on unprompted messages per hour, whatever else says.",
         min=0, max=60, step=1),
    Knob("kairos.checkin_idle_s", "Kairos — speaking unprompted", "Check-in after idle (s)",
         "float", 240.0,
         "How long the room must be quiet before she may say something unprompted "
         "out of the blue (as opposed to finishing a cut-off thought).",
         min=30.0, max=3600.0, step=30.0),
    Knob("kairos.checkin_chance", "Kairos — speaking unprompted", "Check-in chance", "float", 0.35,
         "Even once it has gone quiet, she usually still says nothing. 0 = never check in.",
         min=0.0, max=1.0, step=0.05),

    # ── DECODE: the knobs that bit us ─────────────────────────────────────────────
    Knob("decode.eot_bias", "Decode", "End-of-turn bias", "float", 4.0,
         "A nudge on the stop token so she actually ends her turn instead of running on. "
         "This is what makes 'cut off' turns cut off — kairos.continue_margin is measured "
         "AGAINST it, so if you change this, RE-RUN THE CALIBRATION.",
         min=0.0, max=12.0, step=0.5,
         danger="Changing this invalidates the kairos continue_margin calibration."),
    Knob("decode.no_repeat_ngram", "Decode", "No-repeat n-gram", "int", 0,
         "Bans re-emitting any N-token sequence already in context. MUST STAY 0. At 3 it "
         "banned her from quoting a number back to you — she wanted '7' with a logit "
         "margin of 9.0 and the sampler masked it, so '4471' came out '4417'. It garbled "
         "every tool number, memory and persona detail in the system.",
         min=0, max=6, step=1,
         provenance="measured",
         receipt="gates/G-VERBATIM-digits-broken.md — 0/6 -> 6/6 when set to 0.",
         danger="ANY value >= 2 breaks verbatim quoting. serve.py refuses to launch with it."),

    # ── MEMORY ────────────────────────────────────────────────────────────────────
    Knob("memory.admit_personal_only", "Memory", "Only remember facts about someone", "bool", True,
         "A memory is ABOUT SOMEONE. With this off, any grammatical declarative gets "
         "captured — which is how 375 of 487 rows became ASR test corpus ('The kind nurse "
         "painted the tall building as the sun went down') and then surfaced mid-answer as "
         "'recalled memories'.",
         provenance="measured",
         receipt="gates/G-ADMISSION — 6/6.",
         danger="Off = the firehose is back on."),
    Knob("memory.l5_tau", "Memory", "Recall threshold (tau)", "float", 0.30,
         "How strong a match a memory needs before she brings it up. Lower = she recalls "
         "more, and more loosely.",
         min=0.0, max=1.0, step=0.02),
]


# ──── store ───────────────────────────────────────────────────────────────────
def _load() -> dict:
    global _CACHE
    with _LOCK:
        if _CACHE is None:
            try:
                with open(STORE, encoding="utf-8") as f:
                    _CACHE = json.load(f)
            except Exception:
                _CACHE = {}
        return dict(_CACHE)


def _clamp(k: Knob, v: Any) -> Any:
    if k.type == "bool":
        return bool(v)
    if k.type == "int":
        v = int(round(float(v)))
    elif k.type == "float":
        v = float(v)
    else:
        return v
    if k.min is not None:
        v = max(k.min if k.type == "float" else int(k.min), v)
    if k.max is not None:
        v = min(k.max if k.type == "float" else int(k.max), v)
    return v


def by_key() -> dict[str, Knob]:
    return {k.key: k for k in KNOBS}


def get(key: str, fallback: Any = None) -> Any:
    """Live value: the operator's override if set, else the declared default."""
    kn = by_key().get(key)
    vals = _load()
    if key in vals and kn:
        return _clamp(kn, vals[key])
    if kn:
        return kn.default
    return fallback


def set_many(updates: dict) -> dict:
    """Apply operator overrides. Unknown keys are refused (a typo must not silently
    become a setting that nothing reads — that is how knobs go dead)."""
    global _CACHE
    known = by_key()
    bad = [k for k in updates if k not in known]
    if bad:
        raise ValueError(f"unknown knob(s): {', '.join(sorted(bad))}")
    with _LOCK:
        cur = _load()
        for k, v in updates.items():
            cur[k] = _clamp(known[k], v)
        os.makedirs(os.path.dirname(STORE), exist_ok=True)
        tmp = STORE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cur, f, indent=2, sort_keys=True)
        os.replace(tmp, STORE)
        _CACHE = cur
    return cur


def reset(key: str) -> None:
    global _CACHE
    with _LOCK:
        cur = _load()
        cur.pop(key, None)
        with open(STORE, "w", encoding="utf-8") as f:
            json.dump(cur, f, indent=2, sort_keys=True)
        _CACHE = cur


def schema() -> dict:
    """Everything the UI needs to render itself — knobs, live values, provenance."""
    vals = _load()
    out = []
    for k in KNOBS:
        d = asdict(k)
        d["value"] = get(k.key)
        d["overridden"] = k.key in vals
        out.append(d)
    groups = []
    for k in out:
        if k["group"] not in groups:
            groups.append(k["group"])
    return {"groups": groups, "knobs": out, "store": STORE}

