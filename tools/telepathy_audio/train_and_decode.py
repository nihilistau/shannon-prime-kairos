"""train_and_decode.py — Voice-Head v2 (PCA-whiten + torch MLP) end-to-end.

pairs_real.npz -> PCA-whiten h (fights the 3840->512 overfit) -> torch MLP (dropout +
weight decay, cosine+MSE loss, GPU) -> predict standardized Mimi latent. Then a HELD-OUT
sentence: live 12B hidden -> head -> z_hat -> Mimi decode -> wav.
"""
import os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("NO_TORCH_COMPILE", "1")
import torch, torch.nn as nn
torch._dynamo.config.suppress_errors = True
from distill_real import get_hidden
from huggingface_hub import hf_hub_download
from moshi.models import loaders

HERE = os.path.dirname(os.path.abspath(__file__))
dev = "cuda"


def main():
    d = np.load(os.path.join(HERE, "pairs_real.npz"))
    H = torch.tensor(d["h"], dtype=torch.float32); Z = torch.tensor(d["z"], dtype=torch.float32)
    N = H.shape[0]; print(f"pairs {N}  h{tuple(H.shape)} z{tuple(Z.shape)}", flush=True)

    # ── PCA-whiten h to K dims (on a random 90% train split) ──
    K = 384
    perm = torch.randperm(N); ntr = int(0.9 * N)
    tr, va = perm[:ntr], perm[ntr:]
    hmu = H[tr].mean(0)
    Hc = H - hmu
    U, S, V = torch.linalg.svd(Hc[tr], full_matrices=False)   # V:[3840,3840]
    comp = V[:K]                                              # [K,3840]
    whit = comp / (S[:K, None] / np.sqrt(len(tr)) + 1e-4)     # whiten by singular values
    def proj(h): return (h - hmu) @ whit.T                    # [*,K]
    zmu, zsd = Z[tr].mean(0), Z[tr].std(0) + 1e-6
    def zn(z): return (z - zmu) / zsd
    Xtr, Ytr = proj(H[tr]).to(dev), zn(Z[tr]).to(dev)
    Xva, Yva = proj(H[va]).to(dev), zn(Z[va]).to(dev)

    net = nn.Sequential(
        nn.Linear(K, 1024), nn.GELU(), nn.Dropout(0.15),
        nn.Linear(1024, 1024), nn.GELU(), nn.Dropout(0.15),
        nn.Linear(1024, 512),
    ).to(dev)
    opt = torch.optim.AdamW(net.parameters(), lr=1e-3, weight_decay=1e-3)
    def cos(a, b): return (a*b).sum(1) / (a.norm(dim=1)*b.norm(dim=1)+1e-9)
    best = -1; bad = 0
    for ep in range(3000):
        net.train(); opt.zero_grad()
        p = net(Xtr)
        loss = ((p-Ytr)**2).mean() + (1 - cos(p, Ytr)).mean()
        loss.backward(); opt.step()
        if ep % 100 == 0:
            net.eval()
            with torch.no_grad():
                pv = net(Xva); vc = cos(pv, Yva).mean().item()
            print(f"  ep{ep} loss {loss.item():.3f} val_cos {vc:.3f}", flush=True)
            if vc > best: best = vc; bad = 0
            else:
                bad += 1
                if bad >= 6: print("early stop", flush=True); break
    print(f"BEST val_cos {best:.3f}", flush=True)

    # ── held-out sentence -> live 12B hidden -> head -> Mimi decode ──
    text = "Good morning, I hope you had a restful night."
    h = torch.tensor(get_hidden(text), dtype=torch.float32)
    net.eval()
    with torch.no_grad():
        zpred = net(proj(h).to(dev)).cpu() * zsd + zmu            # [n,512]
    print(f"held-out '{text[:28]}...' -> z_hat {tuple(zpred.shape)}", flush=True)

    mimi = loaders.get_mimi(hf_hub_download(loaders.DEFAULT_REPO, loaders.MIMI_NAME), device=dev)
    mimi.set_num_codebooks(8)
    zt = zpred.T[None].to(dev)                                    # [1,512,n]
    with torch.no_grad():
        codes = mimi.quantizer.encode(zt); wav = mimi.decode(codes)
    import soundfile as sf
    out = os.path.join(HERE, "voicehead_v2.wav")
    sf.write(out, wav.squeeze().cpu().numpy(), mimi.sample_rate)
    print(f"WROTE {out}", flush=True)


if __name__ == "__main__":
    main()
