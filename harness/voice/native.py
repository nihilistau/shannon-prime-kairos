"""native.py — Gemma-4-12B-Unified's NATIVE encoder-free audio path (ADR-KAI4).

The model is ENCODER-FREE: 640 raw audio samples (40ms @16k) ARE the audio
feature; model.embed_audio.embedding_projection [3840,640] maps each frame into
the LM residual space; inject those via inject_frames at audio token 258881.
No mel, no CTC, no training — this is what Gemma was trained to interpret as sound.

Preprocessing (processor_config.json Gemma4UnifiedAudioFeatureExtractor):
    sampling_rate 16000, audio_samples_per_token 640, feature_size 640,
    padding right, padding_value 0.0. => non-overlapping 640-sample frames,
    last frame zero-padded; each frame -> W @ frame.
"""
from __future__ import annotations

import os

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VOICE_DIR = os.environ.get("SP_VOICE_DIR", os.path.join(_ROOT, "var", "voice"))
PROJ_NPZ = os.path.join(VOICE_DIR, "embed_audio.npz")
SAMPLES_PER_TOKEN = 640
SR = 16000
AUDIO_TOKEN = 258881
MAX_TOKENS = 750
EPS = 1e-6                  # Gemma4RMSNorm eps (config rms_norm_eps)

_W: np.ndarray | None = None


def available() -> bool:
    return os.path.isfile(PROJ_NPZ)


def _weight() -> np.ndarray:
    global _W
    if _W is None:
        _W = np.load(PROJ_NPZ)["weight"].astype(np.float32)   # [E=3840, 640]
    return _W


def status() -> dict:
    if not available():
        return {"ok": False, "error": f"missing {PROJ_NPZ} (run tools/extract_audio_projection.py)"}
    w = _weight()
    return {"ok": True, "path": "native", "E": int(w.shape[0]),
            "samples_per_token": int(w.shape[1]), "audio_token": AUDIO_TOKEN}


def encode(pcm: np.ndarray, scale: float | None = None) -> np.ndarray:
    """f32 mono 16k [-1,1] -> native audio embeddings [n_tok, E=3840].

    scale: optional multiplier on the projected embeddings. Gemma scales token
    embeddings by sqrt(E); whether audio embeddings need it is verified live via
    SP_AUDIO_SCALE (default 1.0 = raw projection output)."""
    x = np.asarray(pcm, dtype=np.float32)
    # trim leading/trailing silence — don't inject dead air (and keeps the frame
    # count / payload down). Energy-gate with a small pad.
    if len(x) > SAMPLES_PER_TOKEN * 2:
        win = 320
        m = len(x) // win
        e = np.sqrt((x[: m * win].reshape(m, win) ** 2).mean(axis=1) + 1e-9)
        thr = max(e.mean() * 0.2, e.max() * 0.05)
        v = np.where(e > thr)[0]
        if len(v):
            a = max(0, v[0] * win - 1600)
            b = min(len(x), (v[-1] + 1) * win + 1600)
            x = x[a:b]
    n = int(np.ceil(len(x) / SAMPLES_PER_TOKEN))
    n = min(n, MAX_TOKENS)
    pad = n * SAMPLES_PER_TOKEN
    if len(x) < pad:
        x = np.pad(x, (0, pad - len(x)))
    frames = x[:pad].reshape(n, SAMPLES_PER_TOKEN).astype(np.float32)   # [n, 640]
    W = _weight()                                            # [E, 640] projection
    # embed_audio = RMSNorm(no-scale) -> Linear (Gemma4UnifiedMultimodalEmbedder).
    # Gemma4RMSNorm._norm: x * (mean(x^2)+eps)^-0.5, computed in f32, NO learnable
    # weight (embedding_pre_projection_norm has with_scale=False). Per-frame over
    # the 640-sample axis. This is THE step that was missing — without it the raw
    # frames land at the wrong magnitude and read as garbage.
    ms = np.mean(frames * frames, axis=1, keepdims=True) + EPS
    normed = frames * np.power(ms, -0.5)                     # [n, 640] unit-RMS
    emb = normed @ W.T                                       # [n, E] soft audio tokens
    if scale is None:
        scale = float(os.environ.get("SP_AUDIO_SCALE", "1.0"))
    if scale != 1.0:
        emb = emb * scale
    return emb.astype(np.float32)
