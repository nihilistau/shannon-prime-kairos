"""P5 drafter v1 — capacity/objective sweep over the SAME v0 pairs.

v0 (PCA768 -> 2048 -> E, cosine loss, 30 ep) gave val_cos 0.7257 and a 19.8%
top-1 acceptance proxy (bar 25%). This asks ONE question cheaply: is the head
CAPACITY-bound or DATA-bound? Same data, three heads:

  A  wider   : PCA1536 -> 4096 -> E
  B  deeper  : PCA1536 -> 4096 -> 4096 -> E (residual)
  C  B + cos+MSE mixed loss (direction AND magnitude — the head's argmax sees
     unnormalized logits, so scale matters)

Prints val_cos for each; the winner is saved as drafter_v1.pt for the proxy.
If none moves the needle, the head is DATA-bound and the answer is corpus, not
parameters (that verdict is itself the receipt).
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
    hi, hn = [], []
    for s in shards:
        z = np.load(s)
        hi.append(z["h_in"]); hn.append(z["h_next"])
    X = np.concatenate(hi).astype(np.float32); Y = np.concatenate(hn).astype(np.float32)
    n, E = X.shape
    idx = np.random.RandomState(7).permutation(n)   # THE canonical split
    cut = int(n * 0.92)
    tr, va = idx[:cut], idx[cut:]
    print(f"[v1] {n} pairs, E={E}, train={len(tr)} val={len(va)}, dev={dev}")

    K = 1536
    mu = X[tr].mean(0, keepdims=True)
    Xc = X[tr] - mu
    sub = np.random.RandomState(3).permutation(len(tr))[:12000]
    U, S, Vt = np.linalg.svd(Xc[sub], full_matrices=False)
    P = Vt[:K] / np.sqrt(S[:K, None] ** 2 / len(sub) + 1e-6)
    def wh(a): return torch.tensor((a - mu) @ P.T, dtype=torch.float32)

    Xtr, Xva = wh(X[tr]), wh(X[va])
    Ytr, Yva = torch.tensor(Y[tr]), torch.tensor(Y[va])
    cos = nn.CosineSimilarity(dim=-1)

    class Deep(nn.Module):
        def __init__(self, k, e):
            super().__init__()
            self.inp = nn.Linear(k, 4096)
            self.h1 = nn.Linear(4096, 4096)
            self.out = nn.Linear(4096, e)
            self.act = nn.GELU()
        def forward(self, x):
            z = self.act(self.inp(x))
            z = z + self.act(self.h1(z))     # residual block
            return self.out(z)

    runs = {
        "A wide":  (nn.Sequential(nn.Linear(K, 4096), nn.GELU(), nn.Linear(4096, E)), False),
        "B deep":  (Deep(K, E), False),
        "C deep+mse": (Deep(K, E), True),
    }
    best_name, best_cos, best_state = None, -1.0, None
    for name, (model, mixed) in runs.items():
        model = model.to(dev)
        opt = torch.optim.AdamW(model.parameters(), lr=3e-4, weight_decay=1e-4)
        sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=40)
        bs, top = 512, -1.0
        for ep in range(40):
            model.train()
            perm = torch.randperm(len(Xtr))
            for i in range(0, len(perm), bs):
                j = perm[i:i + bs]
                xb, yb = Xtr[j].to(dev), Ytr[j].to(dev)
                pred = model(xb)
                loss = (1 - cos(pred, yb)).mean()
                if mixed:
                    loss = loss + 0.1 * nn.functional.mse_loss(
                        pred / (pred.norm(dim=-1, keepdim=True) + 1e-6) * yb.norm(dim=-1, keepdim=True),
                        yb)
                opt.zero_grad(); loss.backward(); opt.step()
            sched.step()
            model.eval()
            with torch.no_grad():
                vc = cos(model(Xva.to(dev)), Yva.to(dev)).mean().item()
            top = max(top, vc)
            if vc > best_cos:
                best_cos, best_name = vc, name
                best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
        print(f"[v1] {name:12} best val_cos = {top:.4f}")

    import torch as _t
    _t.save({"state": best_state, "which": best_name, "mu": mu, "P": P,
             "K": K, "E": E, "val_cos": best_cos},
            os.path.join(DATA, "drafter_v1.pt"))
    print(f"[v1] WINNER: {best_name} val_cos={best_cos:.4f} -> drafter_v1.pt  (v0 was 0.7257)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
