"""/v1/voice — the P0 voice turn (ADR-KAI4).

Browser sends one VAD-segmented utterance (PCM16 mono 16k, base64) + session_id.
We: guard-VAD → log-mel → GNA ear → [k×E] frames → daemon /v1/chat with
inject_frames (audio placeholder 258881) → stream the reply deltas back (the
console speaks them via its v0 TTS). The canonical session transcript records
the voice turn so the conversation stays coherent across modalities.

P0 honesty notes:
  * inject_frames turns bypass persist-KV in the daemon (B5 seam exclusion) —
    a voice turn costs a fresh prefill; persist∘inject composition is a P1 item.
  * The ear's legible vocabulary is the trained V_sub — P0 gates PLUMBING
    (G-VOICE-0); free speech arrives with the P1 vocab scale-up.
"""
from __future__ import annotations

import base64
import json
import os
from typing import Any, Dict, Iterator

import numpy as np

from harness.voice import dsp, ear

VOICE_PH = 258881          # the gemma-4 audio placeholder (KAI-3 constant)
VAD_RMS = float(os.environ.get("SP_VOICE_VAD_RMS", "0.010"))
MAX_SECONDS = 30


def voice_status() -> Dict[str, Any]:
    return {"ear": ear.status(), "vad_rms": VAD_RMS, "inject_ph": VOICE_PH}


def voice_turn(body: Dict[str, Any], transcript: list) -> Iterator[bytes]:
    """SSE generator: {'voice':...} header event, then daemon deltas, then [DONE]."""
    def ev(obj: Dict[str, Any]) -> bytes:
        return ("data: " + json.dumps(obj) + "\n\n").encode()

    try:
        pcm = dsp.pcm16_to_f32(base64.b64decode(body.get("audio_b64", "")))
    except Exception as exc:
        yield ev({"error": f"bad audio_b64: {exc}"})
        yield b"data: [DONE]\n\n"
        return
    if pcm.size == 0 or pcm.size > MAX_SECONDS * dsp.SR:
        yield ev({"error": f"utterance empty or >{MAX_SECONDS}s"})
        yield b"data: [DONE]\n\n"
        return

    energy = dsp.rms_energy(pcm)
    if energy.size == 0 or float(energy.max()) < VAD_RMS:
        yield ev({"voice": {"skip": "silence", "rms": float(energy.max() if energy.size else 0)}})
        yield b"data: [DONE]\n\n"
        return

    mel = dsp.logmel(pcm)
    try:
        frames = ear.hear(mel)
    except ear.EarUnavailable as exc:
        yield ev({"error": f"ear unavailable: {exc}"})
        yield b"data: [DONE]\n\n"
        return

    st = ear.status()
    yield ev({"voice": {"frames": int(frames.shape[0]), "device": st.get("device"),
                        "seconds": round(pcm.size / dsp.SR, 2)}})
    if frames.shape[0] == 0:
        yield ev({"delta": "(I heard sound but nothing I could make out yet — my "
                           "spoken vocabulary is still small. P1 fixes that.)"})
        yield b"data: [DONE]\n\n"
        return

    # P1.5 graceful framing: the ear is still learning REAL-mic speech (trained on
    # synthetic voices), so injected tokens are often partial. Tell the model to
    # respond to what it CAN make out and ASK rather than confabulate — this stops
    # the "invent a whole backstory" failure mode on unclear audio.
    n_fr = int(frames.shape[0])
    guide = ("The user just SPOKE to you; their words were transcribed to audio "
             "frames but the transcription is imperfect and may be partial. Reply "
             "naturally and briefly to what you can make out. If it is unclear or "
             "too short to tell, say you didn't quite catch it and ask them to "
             "repeat — do NOT invent facts or a backstory.")
    turn = list(transcript)
    turn.append({"role": "system", "content": guide})
    turn.append({"role": "user", "content": f"[voice utterance, {n_fr} audio frames]"})
    transcript.append({"role": "user", "content": f"[voice utterance, {n_fr} audio frames]"})

    from harness.inference.client import get_client
    client = get_client()
    req = {
        "messages": turn,
        "inject_frames": [f.tolist() for f in frames],
        "inject_ph": VOICE_PH,
        # P1.5: double the ceiling — voice replies were truncating mid-sentence.
        "max_tokens": int(body.get("max_tokens", 256)),
        "temperature": float(body.get("temperature", 0.6)),
        "repetition_penalty": 1.3,
        "eot_bias": 4.0,
    }
    reply_parts: list = []
    try:
        for delta in client.chat_stream_raw(req) if hasattr(client, "chat_stream_raw") \
                else _raw_stream(client, req):
            reply_parts.append(delta)
            yield ev({"delta": _clean(delta)})
    except Exception as exc:
        yield ev({"delta": f"[voice turn error: {exc}]"})
    final = _clean("".join(reply_parts)).strip()
    if final:
        transcript.append({"role": "assistant", "content": final})
    yield b"data: [DONE]\n\n"


_CTRL = None


def _clean(s: str) -> str:
    """Strip control-token artifacts that leak on the injected-frame path
    (<0x0D> CR bytes, stray fences, [audio] placeholders)."""
    global _CTRL
    if _CTRL is None:
        import re
        _CTRL = re.compile(r"<0x0[0-9A-Fa-f]>|```+|\[audio\]|<\|?audio\|?>")
    return _CTRL.sub("", s)


def _raw_stream(client, req: Dict[str, Any]) -> Iterator[str]:
    """POST the raw /v1/chat body (inject_frames isn't in InferenceConfig) and
    yield deltas — thin urllib fallback over the daemon's SSE."""
    import urllib.request
    url = getattr(client, "base_url", None) or os.environ.get(
        "SP_DAEMON_URL", "http://127.0.0.1:3000")
    r = urllib.request.Request(url.rstrip("/") + "/v1/chat",
                               data=json.dumps(req).encode(),
                               headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=600) as resp:
        for raw in resp:
            s = raw.decode("utf-8", "replace").strip()
            if not s.startswith("data:"):
                continue
            p = s[5:].strip()
            if p == "[DONE]":
                return
            try:
                o = json.loads(p)
            except Exception:
                continue
            if o.get("delta"):
                yield o["delta"]
