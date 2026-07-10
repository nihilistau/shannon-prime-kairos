"""voice_frames.py — P1 wav corpus -> CTC frames npz (ADR-KAI4 P1).

Reads var/voice/{corpus.jsonl, vsub.npy, wav/*.wav}, builds the same npz shape
the KAI-3 trainer (audio_ctc_projector.py) consumes:
    train_X[N,Tmax,64] train_Y[N,Lmax] train_flen train_tlen
    eval_*  vsub_ids  n_mels  eval_expect
Log-mel is imported VERBATIM from harness.voice.dsp (trainer-matched). Light
per-utterance augmentation (speed jitter + gaussian noise) widens robustness on
top of the SAPI voice/rate variety. Eval = a held-out 10% split by sentence.
"""
from __future__ import annotations

import glob
import json
import os
import re
import wave

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys_path = os.path.join(ROOT)
import sys
sys.path.insert(0, sys_path)
from harness.voice.dsp import logmel, N_MELS  # noqa: E402

OUT = os.path.join(ROOT, "var", "voice")


def read_wav16(path: str) -> np.ndarray:
    with wave.open(path, "rb") as w:
        sr, n, ch, sw = w.getframerate(), w.getnframes(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(n)
    x = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    if sr != 16000:
        t = np.linspace(0, len(x) - 1, int(round(len(x) * 16000 / sr)))
        x = np.interp(t, np.arange(len(x)), x).astype(np.float32)
    return x


def augment(x: np.ndarray, rng: np.random.Generator, real: bool) -> np.ndarray:
    """P1.5 real-mic bridge: SAPI voices are clean/dry; real mic input has room
    reverb, coloration, background noise, and level variation. Simulate that in
    the WAVEFORM so the SAPI corpus better matches live capture. real=False keeps
    the light clean pass (one copy stays near-original)."""
    # speed jitter
    sp = float(rng.uniform(0.9, 1.1))
    if abs(sp - 1.0) > 1e-3:
        t = np.linspace(0, len(x) - 1, int(len(x) / sp))
        x = np.interp(t, np.arange(len(x)), x).astype(np.float32)
    if real:
        # reverb: convolve with a short exponential-decay impulse (RT60-ish)
        if rng.random() < 0.7:
            rt = float(rng.uniform(0.05, 0.25))
            L = max(2, int(rt * 16000))
            imp = (rng.normal(0, 1, L) * np.exp(-np.arange(L) / (rt * 16000 / 3))).astype(np.float32)
            imp[0] = 1.0
            x = np.convolve(x, imp / (np.abs(imp).sum() + 1e-6))[: len(x)].astype(np.float32)
        # EQ tilt (first-order shelf): color like a cheap mic
        tilt = float(rng.uniform(-0.5, 0.5))
        if abs(tilt) > 0.05:
            x = x + tilt * np.diff(x, prepend=x[:1]).astype(np.float32)
        # additive noise at a random SNR
        rms = float(np.sqrt((x ** 2).mean()) + 1e-8)
        snr = float(rng.uniform(8, 30))
        nstd = rms / (10 ** (snr / 20))
        x = x + rng.normal(0, nstd, size=x.shape).astype(np.float32)
        # gain
        x = x * float(rng.uniform(0.5, 1.4))
        x = np.clip(x, -1.0, 1.0)
    else:
        x = x + rng.normal(0, 0.003, size=x.shape).astype(np.float32)
    return x.astype(np.float32)


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--aug_copies", type=int, default=2,
                    help="extra REAL-mic-augmented copies per wav (0 = clean only)")
    a = ap.parse_args()

    vsub = np.load(os.path.join(OUT, "vsub.npy"))
    corpus = {i: json.loads(l) for i, l in enumerate(
        open(os.path.join(OUT, "corpus.jsonl"), encoding="utf-8"))}
    wavs = sorted(glob.glob(os.path.join(OUT, "wav", "s*.wav")))
    print(f"vsub={len(vsub)} corpus={len(corpus)} wavs={len(wavs)} aug_copies={a.aug_copies}")

    rng = np.random.default_rng(0)
    feats, targs, flens, tlens, sent_ids = [], [], [], [], []
    for w in wavs:
        m = re.match(r"s(\d+)_v\d+_r\d+", os.path.basename(w))
        if not m:
            continue
        sid = int(m.group(1))
        row = corpus.get(sid)
        if not row or not row["ids"]:
            continue
        base = read_wav16(w)
        # one clean-ish pass + N real-mic-augmented copies
        for c in range(1 + a.aug_copies):
            x = augment(base, rng, real=(c > 0))
            mel = logmel(x)
            if mel.shape[0] < len(row["ids"]) + 1:   # CTC needs T > target length
                continue
            feats.append(mel)
            targs.append(np.array(row["ids"], dtype=np.int64))
            flens.append(mel.shape[0])
            tlens.append(len(row["ids"]))
            sent_ids.append(sid)

    N = len(feats)
    Tmax = max(f.shape[0] for f in feats)
    Lmax = max(len(t) for t in targs)
    X = np.zeros((N, Tmax, N_MELS), np.float32)
    Y = np.zeros((N, Lmax), np.int64)
    for i in range(N):
        X[i, : feats[i].shape[0]] = feats[i]
        Y[i, : len(targs[i])] = targs[i]
    FL = np.array(flens, np.int64)
    TL = np.array(tlens, np.int64)
    sent_ids = np.array(sent_ids)

    # held-out eval: ~10% of SENTENCES (not utterances) so eval voices/sentences are unseen-ish
    uniq = np.unique(sent_ids)
    rng2 = np.random.default_rng(1)
    ev_sent = set(rng2.choice(uniq, max(1, len(uniq) // 10), replace=False).tolist())
    ev = np.array([s in ev_sent for s in sent_ids])
    tr = ~ev

    def pack(mask):
        return X[mask], Y[mask], FL[mask], TL[mask]

    trX, trY, trFL, trTL = pack(tr)
    evX, evY, evFL, evTL = pack(ev)
    # eval_expect = the sentence text (for readable logging)
    ev_texts = np.array([corpus[int(s)]["text"] for s in sent_ids[ev]], dtype=object)

    np.savez(os.path.join(OUT, "voice_frames.npz"),
             train_X=trX, train_Y=trY, train_flen=trFL, train_tlen=trTL,
             eval_X=evX, eval_Y=evY, eval_flen=evFL, eval_tlen=evTL,
             vsub_ids=vsub, n_mels=np.int64(N_MELS),
             eval_expect=ev_texts.astype("U64"))
    print(f"N={N} Tmax={Tmax} Lmax={Lmax} train={trX.shape[0]} eval={evX.shape[0]} "
          f"-> {os.path.join(OUT, 'voice_frames.npz')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
