"""distill_pairs.py — build (h, z) training pairs for the Voice-Head (ADR-KAI5 §6).

Byte-exactness is the unlock: Shannon's forward is deterministic, so h_t is a stable
regression target and pairs need NO human labels (self-distillation):

    text --> [served 12B, READ TAP at layer L] --> h_t   [T, 3840]   (deterministic)
    text --> [voxtral-rs TTS] --> wav 16k/24k --> [Mimi encode] --> z_t  [T, 512] @12.5Hz
    time-align (12B token rate vs 12.5Hz) --> pairs.npz {h, z}

Three hooks must be wired for REAL pairs (all read-only / offline; none touch the
served daemon's forward):
  (A) HIDDEN TAP  — a read-only dump of the 12B residual at layer L for a prompt.
                    Candidate: debug /v1/hidden route, or an L1 forward that dumps h.
  (B) TTS         — invoke voxtral-mini-realtime-rs `speak --device discrete`.
  (C) MIMI ENCODE — moshi/mimi: wav -> 512-d continuous latent @12.5Hz (pre-RVQ).

Until (A)-(C) are wired, `--synthetic` fabricates dimensionally-correct pairs so the
downstream fit/decode plumbing is testable end-to-end today.

Usage:
    python distill_pairs.py --texts lines.txt --out pairs.npz      # real (needs hooks)
    python distill_pairs.py --synthetic --n 3000 --out pairs.npz   # plumbing test
"""
from __future__ import annotations

import argparse
import numpy as np

D_H = 3840      # 12B residual width (E)
D_Z = 512       # Mimi continuous latent width
HZ = 12.5       # Mimi frame rate


# ---- REAL hooks (TODO: wire in P0/P1) --------------------------------------
def tap_hidden(text: str, layer: int) -> np.ndarray:
    """(A) Return the 12B per-position hidden [T, D_H] for `text` at `layer`.
    READ-ONLY tap; must not alter the forward. Wire to /v1/hidden or an L1 dump."""
    raise NotImplementedError("HIDDEN TAP not wired — see README 'one real dependency'")


def tts_wav(text: str) -> np.ndarray:
    """(B) voxtral-rs TTS -> mono waveform. Wire to the rust `speak` binary."""
    raise NotImplementedError("TTS hook not wired — voxtral-mini-realtime-rs speak")


_MIMI = None


def _mimi():
    """Load Mimi once (eager mode — Triton/torch.compile unavailable on Windows)."""
    global _MIMI
    if _MIMI is None:
        import os
        os.environ.setdefault("NO_TORCH_COMPILE", "1")
        import torch
        torch._dynamo.config.suppress_errors = True
        from huggingface_hub import hf_hub_download
        from moshi.models import loaders
        w = hf_hub_download(loaders.DEFAULT_REPO, loaders.MIMI_NAME)
        m = loaders.get_mimi(w, device="cuda" if torch.cuda.is_available() else "cpu")
        m.set_num_codebooks(8)
        _MIMI = m
    return _MIMI


def mimi_encode(wav: np.ndarray, sr: int = 16000) -> np.ndarray:
    """(C) Mimi encoder -> [T, D_Z=512] continuous latent @12.5Hz (pre-quantization).
    PROVEN 2026-07-11: mimi._encode_to_unquantized_latent -> [1,512,T]. Resamples to 24k."""
    import torch
    m = _mimi()
    x = np.asarray(wav, dtype=np.float32)
    if sr != m.sample_rate:
        n2 = int(round(len(x) * m.sample_rate / sr))
        x = np.interp(np.linspace(0, len(x) - 1, n2), np.arange(len(x)), x).astype(np.float32)
    dev = next(m.parameters()).device
    xt = torch.tensor(x)[None, None].to(dev)
    with torch.no_grad():
        z = m._encode_to_unquantized_latent(xt)      # [1, 512, T]
    return z.squeeze(0).transpose(0, 1).cpu().numpy()  # [T, 512]


def align(h: np.ndarray, z: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Resample the token-rate h to the 12.5Hz z grid by linear interpolation on time."""
    Th, Tz = len(h), len(z)
    if Th == Tz:
        return h, z
    idx = np.linspace(0, Th - 1, Tz)
    lo = np.floor(idx).astype(int); hi = np.minimum(lo + 1, Th - 1); frac = (idx - lo)[:, None]
    h_rs = h[lo] * (1 - frac) + h[hi] * frac
    return h_rs.astype(np.float32), z.astype(np.float32)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--texts")
    ap.add_argument("--out", default="pairs.npz")
    ap.add_argument("--layer", type=int, default=-1, help="12B tap layer (-1 = final pre-logit)")
    ap.add_argument("--synthetic", action="store_true")
    ap.add_argument("--n", type=int, default=3000)
    a = ap.parse_args()

    if a.synthetic:
        rng = np.random.default_rng(0)
        # a plausible (correlated) h->z so fit_voicehead has signal to learn
        H = rng.normal(0, 1, (a.n, D_H)).astype(np.float32)
        Wt = (rng.normal(0, 1, (D_H, D_Z)) / np.sqrt(D_H)).astype(np.float32)
        Z = (H @ Wt + 0.05 * rng.normal(0, 1, (a.n, D_Z))).astype(np.float32)
        np.savez(a.out, h=H, z=Z)
        print(f"[synthetic] wrote {a.out}  h{H.shape} z{Z.shape}")
        return

    lines = [l.strip() for l in open(a.texts, encoding="utf-8") if l.strip()]
    Hs, Zs = [], []
    for i, t in enumerate(lines):
        h = tap_hidden(t, a.layer)          # (A)
        z = mimi_encode(tts_wav(t))         # (B)+(C)
        h, z = align(h, z)
        Hs.append(h); Zs.append(z)
        if i % 50 == 0:
            print(f"  {i}/{len(lines)}")
    H = np.concatenate(Hs); Z = np.concatenate(Zs)
    np.savez(a.out, h=H, z=Z)
    print(f"wrote {a.out}  h{H.shape} z{Z.shape}")


if __name__ == "__main__":
    main()
