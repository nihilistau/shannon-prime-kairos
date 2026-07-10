"""decode_voicehead.py — apply the fitted Voice-Head and (optionally) decode to audio.

ADR-KAI5 §5.2. h[T,3840] --> B_out --> z_hat[T,512] --> [Mimi decoder] --> wav.
If moshi/mimi isn't importable, writes z_hat.npy for external decoding — the head
itself (the LatentBridge adapter) is the PoC deliverable; the decoder is swappable
(Mimi | voxtral-rs flow | Pocket-TTS).

Usage:
    python decode_voicehead.py --head voicehead.npz --h h_seq.npy --out out.wav
"""
from __future__ import annotations

import argparse
import numpy as np

from fit_voicehead import apply_head  # reuse the exact forward


def load_head(path):
    d = np.load(path)
    lin = {k: d[k] for k in ("W", "mu_h", "sd_h", "mu_z", "sd_z")}
    mlp = {"W1": d["W1"], "b1": d["b1"], "W2": d["W2"], "b2": d["b2"], "hidden": d["W1"].shape[1]}
    return lin, mlp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--head", required=True)
    ap.add_argument("--h", required=True, help="npy [T, 3840] hidden sequence")
    ap.add_argument("--out", default="out.wav")
    a = ap.parse_args()

    lin, mlp = load_head(a.head)
    H = np.load(a.h).astype(np.float32)
    z_hat = apply_head(lin, mlp, H)                      # [T, 512] continuous audio latent
    print(f"z_hat {z_hat.shape}  L2/frame mean {np.linalg.norm(z_hat, axis=1).mean():.2f}")

    try:
        # Mimi decoder path (moshi package). Continuous latent -> RVQ-free reconstruction
        # requires the decoder-from-latent entry; if only token-decode is exposed, quantize
        # z_hat through Mimi's VQ first (still no LLM tokens — codec-internal).
        import torch  # noqa
        from moshi.models import loaders  # type: ignore
        mimi = loaders.get_mimi(loaders.MIMI_NAME)  # pseudo; adapt to installed API
        wav = mimi.decode_latent(torch.tensor(z_hat)[None])  # decoder-from-latent
        import soundfile as sf
        sf.write(a.out, np.asarray(wav).squeeze(), 24000)
        print(f"wrote {a.out}")
    except Exception as e:
        np.save(a.out + ".z_hat.npy", z_hat)
        print(f"[mimi decode unavailable: {e}] wrote {a.out}.z_hat.npy for external decode")


if __name__ == "__main__":
    main()
