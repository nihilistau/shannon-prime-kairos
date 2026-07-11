"""P5 drafter — OFFLINE ACCEPTANCE PROXY through the frozen LM head.

For each held-out pair (h[t], h[t+1]): the drafter predicts ĥ[t+1]; the draft
token = argmax(W·ĥ) where W = the 12B's tied embedding (model.language_model.
embed_tokens.weight, BF16 safetensors — gemma's final logit softcap is
monotonic so argmax is invariant). The REFERENCE token = argmax(W·h_true) —
by construction the token the real model emits from that state. TOP-1
AGREEMENT between the two = the offline acceptance proxy.

Gate bar (gates/G-KAIROS-P5-launch.md): >= 25% top-1 -> proceed to the
on-metal SP_EAGLE_ACCEPT H2H.

CPU-only (the daemon keeps the GPU): vocab-chunked matmul over the 262k head,
running argmax. ~1-2 min for ~1.1k val vectors.
"""
from __future__ import annotations

import glob
import json
import os
import struct

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(ROOT, "var", "drafter")
ST = r"D:\Files\Models\Gemma4\gemma-4-12b-bucket\model.safetensors"
EMB = "model.language_model.embed_tokens.weight"
VCHUNK = 16384


def load_val_predictions():
    import torch
    import torch.nn as nn
    ck = torch.load(os.path.join(DATA, "drafter_v0.pt"), map_location="cpu", weights_only=False)
    mu, P = ck["mu"], ck["P"]
    shards = sorted(glob.glob(os.path.join(DATA, "pairs_*.npz")))
    hi, hn = [], []
    for s in shards:
        z = np.load(s)
        hi.append(z["h_in"]); hn.append(z["h_next"])
    X = np.concatenate(hi); Y = np.concatenate(hn)
    n = X.shape[0]
    idx = np.random.RandomState(7).permutation(n)      # THE fit_drafter split
    va = idx[int(n * 0.92):]
    mlp = nn.Sequential(nn.Linear(P.shape[0], 2048), nn.GELU(), nn.Linear(2048, X.shape[1]))
    mlp.load_state_dict(ck["mlp"]); mlp.eval()
    with torch.no_grad():
        pred = mlp(torch.tensor((X[va] - mu) @ P.T, dtype=torch.float32)).numpy()
    return pred.astype(np.float32), Y[va].astype(np.float32)


def head_argmax(H: np.ndarray):
    """argmax over the full vocab of W @ h for each column of H [E, N]."""
    with open(ST, "rb") as f:
        (hlen,) = struct.unpack("<Q", f.read(8))
        header = json.loads(f.read(hlen))
        meta = header[EMB]
        V, E = meta["shape"]
        base = 8 + hlen + meta["data_offsets"][0]
        best_v = np.full(H.shape[1], -1, dtype=np.int64)
        best_s = np.full(H.shape[1], -np.inf, dtype=np.float32)
        for v0 in range(0, V, VCHUNK):
            rows = min(VCHUNK, V - v0)
            f.seek(base + v0 * E * 2)
            u16 = np.frombuffer(f.read(rows * E * 2), dtype="<u2").astype(np.uint32) << 16
            W = u16.view(np.float32).reshape(rows, E)   # bf16 -> f32
            S = W @ H                                    # [rows, N]
            am = S.argmax(0)
            mx = S[am, np.arange(S.shape[1])]
            upd = mx > best_s
            best_s[upd] = mx[upd]
            best_v[upd] = v0 + am[upd]
    return best_v


def main() -> int:
    pred, true = load_val_predictions()
    print(f"[proxy] val vectors: {len(pred)}; head = {EMB} (bf16, chunked argmax)")
    ref = head_argmax(true.T)
    drf = head_argmax(pred.T)
    agree = float((ref == drf).mean())
    print(f"[proxy] TOP-1 AGREEMENT (draft vs reference through the frozen head): "
          f"{agree * 100:.1f}%  ({int((ref == drf).sum())}/{len(ref)})")
    bar = 0.25
    verdict = "PASS" if agree >= bar else "FAIL"
    print(f"[proxy] G-DRAFTER acceptance proxy: {verdict} (bar {bar * 100:.0f}%) — "
          f"{'proceed to SP_EAGLE_ACCEPT on-metal' if verdict == 'PASS' else 'head needs more data/params before the on-metal run'}")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
