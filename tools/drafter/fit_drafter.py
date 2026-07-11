"""P5 DRAFTER v0 — EAGLE-lite hidden→next-hidden head (the KAI-5 voicehead recipe
pointed back at the language stream).

Model: PCA-whiten(768) → MLP(768→2048→3840) predicting h[t+1] from h[t]
(the KAI-5 v2 shape that took Mimi val-cos 0.38→0.637 in one evening).
Loss: 1 - cosine(ĥ, h_next). Val: held-out cosine + (when the LM head matrix
is available) top-1 agreement through the frozen head = the OFFLINE acceptance
proxy for gates/G-DRAFTER-H2H.md.

Run:  python tools/drafter/fit_drafter.py            (trains on var/drafter/pairs_*.npz)
Out:  var/drafter/drafter_v0.pt + a printed val report for the receipt.
"""
from __future__ import annotations

import glob
import os

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(ROOT, "var", "drafter")


def main() -> int:
    import torch
    import torch.nn as nn
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    shards = sorted(glob.glob(os.path.join(DATA, "pairs_*.npz")))
    if not shards:
        print("[fit] no shards — run datagen first")
        return 1
    hi, hn = [], []
    for s in shards:
        z = np.load(s)
        hi.append(z["h_in"]); hn.append(z["h_next"])
    X = np.concatenate(hi); Y = np.concatenate(hn)
    n = X.shape[0]
    print(f"[fit] {n} pairs, E={X.shape[1]}")
    idx = np.random.RandomState(7).permutation(n)
    cut = int(n * 0.92)
    tr, va = idx[:cut], idx[cut:]

    # PCA-whiten input (the KAI-5 v2 trick: the hidden has huge anisotropy)
    mu = X[tr].mean(0, keepdims=True)
    Xc = X[tr] - mu
    cov_k = 768
    U, S, _ = np.linalg.svd(Xc[np.random.RandomState(3).permutation(len(tr))[:8000]], full_matrices=False)
    P = (_[:cov_k] / np.sqrt(S[:cov_k, None] ** 2 / len(tr) + 1e-6))  # [k, E] whitening rows
    def whiten(a): return (a - mu) @ P.T

    Xw_tr = torch.tensor(whiten(X[tr]), dtype=torch.float32)
    Xw_va = torch.tensor(whiten(X[va]), dtype=torch.float32)
    Y_tr = torch.tensor(Y[tr], dtype=torch.float32)
    Y_va = torch.tensor(Y[va], dtype=torch.float32)

    mlp = nn.Sequential(nn.Linear(cov_k, 2048), nn.GELU(), nn.Linear(2048, X.shape[1])).to(dev)
    opt = torch.optim.AdamW(mlp.parameters(), lr=2e-4, weight_decay=1e-4)
    cos = nn.CosineSimilarity(dim=-1)
    bs = 512
    best = -1.0
    for ep in range(30):
        mlp.train()
        perm = torch.randperm(len(Xw_tr))
        for i in range(0, len(perm), bs):
            j = perm[i:i + bs]
            xb, yb = Xw_tr[j].to(dev), Y_tr[j].to(dev)
            loss = (1 - cos(mlp(xb), yb)).mean()
            opt.zero_grad(); loss.backward(); opt.step()
        mlp.eval()
        with torch.no_grad():
            vc = cos(mlp(Xw_va.to(dev)), Y_va.to(dev)).mean().item()
        print(f"[fit] epoch {ep:02d} val_cos={vc:.4f}")
        if vc > best:
            best = vc
            import torch as _t
            _t.save({"mlp": mlp.state_dict(), "mu": mu, "P": P, "val_cos": vc},
                    os.path.join(DATA, "drafter_v0.pt"))
    print(f"[fit] BEST val_cos={best:.4f} -> var/drafter/drafter_v0.pt")
    print("[fit] next: acceptance proxy through the frozen LM head, then the")
    print("      on-metal H2H via SP_EAGLE_ACCEPT (gates/G-DRAFTER-H2H.md).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
