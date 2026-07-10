"""voice_wake.py — G-VOICE-WAKE: the "Hey Shannon" always-on trip head (ADR-KAI4 P1).

A TINY GNA-legal binary classifier on the same log-mel front (Conv1d stack ->
global mean-pool -> 2 logits). Label = does the utterance contain "shannon".
Runs continuously on ~1s windows so the mic can sleep the reasoning stack and
wake on the phrase (the deprecated-GNA power win). Trained on the same SAPI
corpus wavs. Reports held-out trip recall + false-trip rate.

Run (CPU): python tools/voice_wake.py   (writes var/voice/wake.pt + wake.onnx/.xml)
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
import wave

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from harness.voice.dsp import logmel, N_MELS  # noqa: E402

OUT = os.path.join(ROOT, "var", "voice")


def read_wav16(path: str) -> np.ndarray:
    with wave.open(path, "rb") as w:
        raw = w.readframes(w.getnframes())
    return np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--hidden", type=int, default=64)
    ap.add_argument("--win", type=int, default=48)   # ~1s window of 40ms frames
    a = ap.parse_args()
    import torch
    import torch.nn as nn

    corpus = [json.loads(l) for l in open(os.path.join(OUT, "corpus.jsonl"), encoding="utf-8")]
    is_wake = [("shannon" in c["text"]) for c in corpus]
    wavs = sorted(glob.glob(os.path.join(OUT, "wav", "s*.wav")))
    X, Y = [], []
    for w in wavs:
        m = re.match(r"s(\d+)_", os.path.basename(w))
        sid = int(m.group(1))
        if sid >= len(corpus):
            continue
        mel = logmel(read_wav16(w))
        # fixed ~1s window (pad/trim) so the head is streaming-shaped
        if mel.shape[0] < a.win:
            mel = np.pad(mel, ((0, a.win - mel.shape[0]), (0, 0)))
        else:
            mel = mel[: a.win]
        X.append(mel)
        Y.append(1 if is_wake[sid] else 0)
    X = np.stack(X).astype(np.float32)
    Y = np.array(Y, np.int64)
    pos = int(Y.sum())
    print(f"[wake] N={len(Y)} wake={pos} non-wake={len(Y) - pos}")

    rng = np.random.default_rng(0)
    idx = rng.permutation(len(Y))
    n_ev = len(Y) // 10
    ev, tr = idx[:n_ev], idx[n_ev:]
    dev = "cpu"
    tX = torch.tensor(X[tr], device=dev)
    tY = torch.tensor(Y[tr], device=dev)
    eX = torch.tensor(X[ev], device=dev)
    eY = torch.tensor(Y[ev], device=dev)

    class Wake(nn.Module):
        def __init__(s):
            super().__init__()
            h = a.hidden
            s.net = nn.Sequential(
                nn.Conv1d(N_MELS, h, 3, padding=1), nn.ReLU(),
                nn.Conv1d(h, h, 3, padding=1), nn.ReLU())
            s.head = nn.Conv1d(h, 2, 1)

        def forward(s, x):                       # [B,T,mel] -> [B,2] (mean over time)
            z = s.head(s.net(x.transpose(1, 2)))  # [B,2,T]
            return z.mean(dim=2)

    net = Wake().to(dev)
    opt = torch.optim.Adam(net.parameters(), lr=2e-3, weight_decay=1e-4)
    # class-balanced weight (wake is the minority)
    wpos = (len(tY) - int(tY.sum())) / max(int(tY.sum()), 1)
    lossf = nn.CrossEntropyLoss(weight=torch.tensor([1.0, float(wpos)], device=dev))
    best = -1.0
    best_state = None
    for ep in range(a.epochs):
        net.train()
        perm = torch.randperm(len(tY))
        for s in range(0, len(tY), 128):
            b = perm[s: s + 128]
            opt.zero_grad()
            loss = lossf(net(tX[b]), tY[b])
            loss.backward()
            opt.step()
        net.eval()
        with torch.no_grad():
            pr = net(eX).argmax(1)
            tp = int(((pr == 1) & (eY == 1)).sum())
            fp = int(((pr == 1) & (eY == 0)).sum())
            npos = int((eY == 1).sum())
            nneg = int((eY == 0).sum())
            recall = tp / max(npos, 1)
            far = fp / max(nneg, 1)
            score = recall - far
            if score > best:
                best = score
                best_state = {k: v.detach().clone() for k, v in net.state_dict().items()}
        if ep % 10 == 0 or ep == a.epochs - 1:
            print(f"[wake] ep {ep:3d} recall={recall:.3f} false_trip={far:.3f}")

    net.load_state_dict(best_state)
    net.eval()
    with torch.no_grad():
        pr = net(eX).argmax(1)
        tp = int(((pr == 1) & (eY == 1)).sum())
        fp = int(((pr == 1) & (eY == 0)).sum())
        recall = tp / max(int((eY == 1).sum()), 1)
        far = fp / max(int((eY == 0).sum()), 1)
    print(f"[wake] BEST recall={recall:.3f} false_trip={far:.3f}")
    torch.save({"state": net.state_dict(), "win": a.win, "hidden": a.hidden}, os.path.join(OUT, "wake.pt"))
    torch.onnx.export(net, torch.zeros(1, a.win, N_MELS), os.path.join(OUT, "wake.onnx"),
                      input_names=["mel"], output_names=["logits"], opset_version=13)
    import openvino as ov
    ov.save_model(ov.convert_model(os.path.join(OUT, "wake.onnx")),
                  os.path.join(OUT, "wake.xml"), compress_to_fp16=False)
    print(f"[wake] saved wake.pt + wake.xml (recall {recall:.3f}, FAR {far:.3f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
