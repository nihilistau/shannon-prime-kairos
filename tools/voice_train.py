"""voice_train.py — P1 CTC ear trainer (ADR-KAI4 P1). Self-contained, CPU-default.

Trains the GNA-conservative Conv1d CTC encoder (identical arch to the gated KAI-3
projector) on var/voice/voice_frames.npz. No safetensors mmap (that blew the
pagefile on the 12B) — training is pure audio->token-logits; W_sub is only needed
at export, handled by voice_export_wsub.py + the ear. Saves voice_ctc.pt.

Run (CPU, keeps the 2060 serving):
    set CUDA_VISIBLE_DEVICES= && python tools/voice_train.py --epochs 300
"""
from __future__ import annotations

import argparse
import os

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "var", "voice")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", default=os.path.join(OUT, "voice_frames.npz"))
    ap.add_argument("--epochs", type=int, default=300)
    ap.add_argument("--lr", type=float, default=2e-3)
    ap.add_argument("--batch_size", type=int, default=64)
    ap.add_argument("--hidden", type=int, default=256)   # GNA out-ch <=256
    ap.add_argument("--gpu", action="store_true", help="use CUDA (only when the daemon is down)")
    ap.add_argument("--out", default=os.path.join(OUT, "voice_ctc.pt"))
    a = ap.parse_args()

    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    # CPU by DESIGN: the 2060 is Gemma's — a tiny 3-conv CTC net trains fine on CPU
    # in ~1 min, and a cuda-init here contends with the serving daemon (observed
    # stall). Pass --gpu to override when the daemon is down.
    dev = "cuda" if (a.gpu and torch.cuda.is_available()) else "cpu"

    d = np.load(a.frames, allow_pickle=True)
    vsub = d["vsub_ids"]
    V = len(vsub)
    n_mels = int(d["n_mels"])
    BLANK = V
    tX = torch.tensor(d["train_X"], device=dev)
    tY = torch.tensor(d["train_Y"], device=dev)
    tFL = torch.tensor(d["train_flen"], device=dev)
    tTL = torch.tensor(d["train_tlen"], device=dev)
    eX = torch.tensor(d["eval_X"], device=dev)
    eY = torch.tensor(d["eval_Y"], device=dev)
    eFL = torch.tensor(d["eval_flen"], device=dev)
    eTL = torch.tensor(d["eval_tlen"], device=dev)
    exp = d["eval_expect"] if "eval_expect" in d else None
    print(f"[voice-ctc] V={V} n_mels={n_mels} train={tX.shape[0]} eval={eX.shape[0]} "
          f"Tmax={tX.shape[1]} dev={dev}", flush=True)

    class Enc(nn.Module):
        def __init__(s):
            super().__init__()
            h = a.hidden
            s.net = nn.Sequential(
                nn.Conv1d(n_mels, h, 3, padding=1), nn.ReLU(),
                nn.Conv1d(h, h, 3, padding=1), nn.ReLU(),
                nn.Conv1d(h, h, 3, padding=1), nn.ReLU())
            s.head = nn.Conv1d(h, V + 1, 1)

        def forward(s, x):                      # [B,T,mel] -> [B,T,V+1]
            return s.head(s.net(x.transpose(1, 2))).transpose(1, 2)

    net = Enc().to(dev)
    opt = torch.optim.Adam(net.parameters(), lr=a.lr)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=max(1, a.epochs), eta_min=1e-5)

    def ctc(X, Y, FL, TL):
        logp = F.log_softmax(net(X), -1).transpose(0, 1)   # [T,B,V+1]
        tgt = torch.cat([Y[i, : TL[i]] for i in range(Y.shape[0])])
        return F.ctc_loss(logp, tgt, FL, TL, blank=BLANK, zero_infinity=True)

    def collapse(seq):
        col, prev = [], -1
        for s in seq:
            if s != prev and s != BLANK:
                col.append(s)
            prev = s
        return col

    def eval_acc(verbose=False):
        net.eval()
        with torch.no_grad():
            pred = net(eX).argmax(-1)
            ok = tot = exact = 0
            for i in range(eX.shape[0]):
                col = collapse(pred[i, : eFL[i]].tolist())
                tg = eY[i, : eTL[i]].tolist()
                ok += sum(1 for j in range(min(len(col), len(tg))) if col[j] == tg[j])
                tot += len(tg)
                exact += int(col == tg)
                if verbose and i < 8 and exp is not None:
                    print(f"    '{exp[i]}' tgt={tg} pred={col}", flush=True)
        return ok / max(tot, 1), exact / eX.shape[0]

    N = tX.shape[0]
    bs = a.batch_size
    best = -1.0
    best_state = None
    for ep in range(a.epochs):
        net.train()
        perm = torch.randperm(N, device=dev)
        acc = 0.0
        for s in range(0, N, bs):
            idx = perm[s: s + bs]
            opt.zero_grad()
            loss = ctc(tX[idx], tY[idx], tFL[idx], tTL[idx])
            loss.backward()
            opt.step()
            acc += float(loss)
        sched.step()
        if ep % 20 == 0 or ep == a.epochs - 1:
            tok_acc, exact = eval_acc(verbose=(ep == a.epochs - 1))
            if tok_acc > best:
                best = tok_acc
                best_state = {k: v.detach().clone() for k, v in net.state_dict().items()}
            print(f"[voice-ctc] ep {ep:3d} ctc={acc / max(1, (N + bs - 1) // bs):.4f} "
                  f"tok_acc={tok_acc:.3f} exact={exact:.3f} best={best:.3f}", flush=True)

    if best_state:
        net.load_state_dict(best_state)
    # acoustic-robustness read: token acc on TRAIN sentences (seen text, the SAPI
    # voice/rate/noise variety) — the "recognizes what it's heard the words of"
    # metric, complementary to the harder held-out-by-sentence generalization.
    net.eval()
    with torch.no_grad():
        pr = net(tX).argmax(-1)
        ok = tot = 0
        for i in range(tX.shape[0]):
            col = collapse(pr[i, : tFL[i]].tolist())
            tg = tY[i, : tTL[i]].tolist()
            ok += sum(1 for j in range(min(len(col), len(tg))) if col[j] == tg[j])
            tot += len(tg)
        train_acc = ok / max(tot, 1)
    torch.save({"state": net.state_dict(), "vsub": vsub, "H": 3840, "n_mels": n_mels,
                "export_tau": 0.2, "best": best, "hidden": a.hidden}, a.out)
    print(f"[voice-ctc] BEST held-out(by-sentence) tok acc={best:.3f} "
          f"acoustic(seen-text) tok acc={train_acc:.3f} -> {a.out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
