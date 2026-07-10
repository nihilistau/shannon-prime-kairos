"""fit_voicehead.py — fit the audio-OUT LatentBridge adapter B_out: h[3840] -> z[512].

ADR-KAI5 §6. The Voice-Head maps Shannon's hidden state to an audio decoder's
continuous latent (Mimi 512-d @12.5Hz). Recipe = TELE-10b (proven for gemma->qwen):
warm-start a linear map, then add a zero-init residual-MLP, low lr, so the MLP only
CORRECTS the linear (never destabilises it). Loss here is plain MSE on the target
latent as a PoC stand-in for CALM's consistency/flow objective (swap in when a real
Mimi VAE + consistency sampler is wired).

Pure numpy (no torch dep for the PoC): closed-form ridge for the linear warm-start,
then a small GD loop for the residual-MLP. Deterministic.

Usage:
    python fit_voicehead.py --pairs pairs.npz --out voicehead.npz
    python fit_voicehead.py --selftest          # fabricate a known map, prove plumbing
"""
from __future__ import annotations

import argparse
import numpy as np


def _gelu(x):
    return 0.5 * x * (1.0 + np.tanh(0.7978845608 * (x + 0.044715 * x**3)))


def fit_linear_ridge(H, Z, lam=1.0):
    """Closed-form z-scored ridge (the TELE-1 affine that cleared cross-family)."""
    mu_h, sd_h = H.mean(0), H.std(0) + 1e-6
    mu_z, sd_z = Z.mean(0), Z.std(0) + 1e-6
    Hn = (H - mu_h) / sd_h
    Zn = (Z - mu_z) / sd_z
    d = Hn.shape[1]
    W = np.linalg.solve(Hn.T @ Hn + lam * np.eye(d), Hn.T @ Zn)  # [d_h, d_z]
    return {"W": W, "mu_h": mu_h, "sd_h": sd_h, "mu_z": mu_z, "sd_z": sd_z}


def apply_linear(lin, H):
    Hn = (H - lin["mu_h"]) / lin["sd_h"]
    Zn = Hn @ lin["W"]
    return Zn * lin["sd_z"] + lin["mu_z"]


def fit_residual_mlp(H, Z, lin, hidden=512, epochs=300, lr=3e-5, seed=0):
    """Zero-init residual MLP on top of the frozen linear warm-start (TELE-10b).
    z_hat = linear(h) + MLP(h);  MLP starts at 0 so we begin AT the linear solution."""
    rng = np.random.default_rng(seed)
    base = apply_linear(lin, H)                      # frozen linear prediction
    resid = Z - base                                 # what the MLP must learn
    d_in, d_out = H.shape[1], Z.shape[1]
    Hn = (H - lin["mu_h"]) / lin["sd_h"]
    W1 = rng.normal(0, 1e-3, (d_in, hidden)); b1 = np.zeros(hidden)
    W2 = np.zeros((hidden, d_out)); b2 = np.zeros(d_out)   # zero-init => residual 0 at start
    n = H.shape[0]
    for ep in range(epochs):
        A = _gelu(Hn @ W1 + b1)                      # [n,hidden]
        pred = A @ W2 + b2
        err = pred - resid                           # [n,d_out]
        g_W2 = A.T @ err / n; g_b2 = err.mean(0)
        gA = err @ W2.T
        gpre = gA * (Hn @ W1 + b1 > 0)               # relu-ish surrogate grad (stable PoC)
        g_W1 = Hn.T @ gpre / n; g_b1 = gpre.mean(0)
        W2 -= lr * g_W2; b2 -= lr * g_b2
        W1 -= lr * g_W1; b1 -= lr * g_b1
    return {"W1": W1, "b1": b1, "W2": W2, "b2": b2, "hidden": hidden}


def apply_head(lin, mlp, H):
    base = apply_linear(lin, H)
    Hn = (H - lin["mu_h"]) / lin["sd_h"]
    A = _gelu(Hn @ mlp["W1"] + mlp["b1"])
    return base + A @ mlp["W2"] + mlp["b2"]


def report(name, Z, Zh):
    err = np.linalg.norm(Z - Zh, axis=1)
    den = np.linalg.norm(Z, axis=1) + 1e-9
    cos = (Z * Zh).sum(1) / (np.linalg.norm(Z, axis=1) * np.linalg.norm(Zh, axis=1) + 1e-9)
    print(f"  [{name}] relL2 {np.mean(err/den):.4f}  cos {cos.mean():.4f}")
    return cos.mean()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs")
    ap.add_argument("--out", default="voicehead.npz")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--epochs", type=int, default=300)
    a = ap.parse_args()

    if a.selftest:
        # fabricate a known nonlinear h->z map; prove the head recovers it (plumbing gate)
        rng = np.random.default_rng(0)
        T, d_h, d_z = 4000, 256, 64          # small dims for a fast self-test
        H = rng.normal(0, 1, (T, d_h)).astype(np.float32)
        Wt = rng.normal(0, 1, (d_h, d_z)) / np.sqrt(d_h)
        Z = (H @ Wt + 0.2 * _gelu(H @ rng.normal(0, 1, (d_h, d_z)) / np.sqrt(d_h))).astype(np.float32)
        Z += 0.01 * rng.normal(0, 1, Z.shape)
    else:
        if not a.pairs:
            raise SystemExit("--pairs pairs.npz required (or use --selftest)")
        d = np.load(a.pairs)
        H, Z = d["h"].astype(np.float32), d["z"].astype(np.float32)

    ntr = int(0.9 * len(H))
    Htr, Ztr, Hte, Zte = H[:ntr], Z[:ntr], H[ntr:], Z[ntr:]
    print(f"fit_voicehead: {H.shape[0]} pairs  h{H.shape[1]} -> z{Z.shape[1]}")
    lin = fit_linear_ridge(Htr, Ztr)
    print("linear warm-start:"); report("train", Ztr, apply_linear(lin, Htr)); c0 = report("held", Zte, apply_linear(lin, Hte))
    mlp = fit_residual_mlp(Htr, Ztr, lin, epochs=a.epochs)
    print("+ residual-MLP:"); report("train", Ztr, apply_head(lin, mlp, Htr)); c1 = report("held", Zte, apply_head(lin, mlp, Hte))
    np.savez(a.out, W=lin["W"], mu_h=lin["mu_h"], sd_h=lin["sd_h"], mu_z=lin["mu_z"], sd_z=lin["sd_z"],
             W1=mlp["W1"], b1=mlp["b1"], W2=mlp["W2"], b2=mlp["b2"])
    print(f"wrote {a.out}  (held cos: linear {c0:.4f} -> +MLP {c1:.4f})")


if __name__ == "__main__":
    main()
