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
REAL_REPEAT = 8   # each real recording counted 8x (1 clean + 7 lightly-augmented)


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


def trim_silence(x: np.ndarray, pad: int = 1600) -> np.ndarray:
    """Trim leading/trailing silence (real recordings have long dead air that
    bloated Tmax 3.5x and is poor CTC data). Keep a small pad each side."""
    win = 320
    n = len(x) // win
    if n < 2:
        return x
    e = np.sqrt((x[: n * win].reshape(n, win) ** 2).mean(axis=1) + 1e-9)
    thr = max(e.mean() * 0.2, e.max() * 0.05)
    voiced = np.where(e > thr)[0]
    if len(voiced) == 0:
        return x
    a = max(0, voiced[0] * win - pad)
    b = min(len(x), (voiced[-1] + 1) * win + pad)
    return x[a:b]


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
        # MODERATE, realistic quiet-room mic (heavy aug underfit at 0.38): light
        # reverb, subtle mic-EQ, 20-40 dB SNR noise, gentle gain.
        if rng.random() < 0.5:
            rt = float(rng.uniform(0.03, 0.12))
            L = max(2, int(rt * 16000))
            imp = (rng.normal(0, 1, L) * np.exp(-np.arange(L) / (rt * 16000 / 3))).astype(np.float32)
            imp[0] = 3.0                                    # strong direct path (dry-ish)
            x = np.convolve(x, imp / (np.abs(imp).sum() + 1e-6))[: len(x)].astype(np.float32)
        tilt = float(rng.uniform(-0.25, 0.25))              # mild mic coloration
        if abs(tilt) > 0.05:
            x = x + tilt * np.diff(x, prepend=x[:1]).astype(np.float32)
        rms = float(np.sqrt((x ** 2).mean()) + 1e-8)
        snr = float(rng.uniform(20, 40))
        nstd = rms / (10 ** (snr / 20))
        x = x + rng.normal(0, nstd, size=x.shape).astype(np.float32)
        x = x * float(rng.uniform(0.7, 1.3))
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

    # ── REAL microphone samples (ADR-KAI4 P1.6): fold in operator recordings,
    #    heavily UPWEIGHTED (repeated) since they are the TRUE target distribution.
    real_dir = os.path.join(OUT, "real")
    real_manifest = os.path.join(real_dir, "manifest.jsonl")
    real_n = 0
    if os.path.isfile(real_manifest):
        import sys as _sys
        _sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from tools.voice_corpus import tok_batch  # type: ignore
        rows = [json.loads(l) for l in open(real_manifest, encoding="utf-8") if l.strip()]
        vset = {int(t): i for i, t in enumerate(vsub)}
        texts = list({r["text"] for r in rows})
        toks = tok_batch(texts)
        for r in rows:
            gids = toks.get(r["text"])
            if not gids or any(t not in vset for t in gids):
                continue
            ids = [vset[t] for t in gids]
            wp = os.path.join(real_dir, r["wav"])
            if not os.path.isfile(wp):
                continue
            base = trim_silence(read_wav16(wp))    # cut dead air (Tmax + data quality)
            for c in range(REAL_REPEAT):        # upweight real samples
                x = augment(base, rng, real=(c > 0))   # 1 clean + light aug copies
                mel = logmel(x)
                if mel.shape[0] < len(ids) + 1:
                    continue
                feats.append(mel); targs.append(np.array(ids, dtype=np.int64))
                flens.append(mel.shape[0]); tlens.append(len(ids))
                sent_ids.append(1_000_000 + hash(r["text"]) % 900_000)  # keep real in TRAIN
                real_n += 1
    print(f"real samples folded in: {real_n}")

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

    # held-out eval: ~10% of SAPI SENTENCES only (ids < 1e6). Real recordings
    # (ids >= 1e6) are PRECIOUS and always TRAIN — never held out.
    sapi_uniq = np.unique(sent_ids[sent_ids < 1_000_000])
    rng2 = np.random.default_rng(1)
    ev_sent = set(rng2.choice(sapi_uniq, max(1, len(sapi_uniq) // 10), replace=False).tolist())
    ev = np.array([s in ev_sent for s in sent_ids])
    tr = ~ev

    def pack(mask):
        return X[mask], Y[mask], FL[mask], TL[mask]

    trX, trY, trFL, trTL = pack(tr)
    evX, evY, evFL, evTL = pack(ev)
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
