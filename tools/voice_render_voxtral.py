"""voice_render_voxtral.py — natural-voice corpus render via OUR voxtral TTS (P1.6).

voxtral has no batch mode and reloads the model per call (~28s), but GENERATION is
RTF ~6.6x FASTER than realtime. So we render MANY sentences per call (one long wav)
and segment it back to per-sentence wavs by silence. Runs on the 2060 (--device
discrete) — a DAEMON-DOWN bake. Output naming matches voice_frames (s{idx}_v{N}_r2).

Usage (daemon down): python tools/voice_render_voxtral.py [--batch 40] [--voices ...]
                     [--max_sentences N]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import wave

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "var", "voice")
VOX = r"D:\F\shannon-prime-repos\voxtral-mini-realtime-rs\target\release\voxtral.exe"
GGUF = r"C:\Projects\voxtral-mini-realtime-rs\models\voxtral-tts-q4-gguf\voxtral-tts-q4.gguf"
VDIR = r"C:\Projects\voxtral-mini-realtime-rs\models\voxtral-tts-q4-gguf\voice_embedding"
VOXCWD = r"D:\F\shannon-prime-repos\voxtral-mini-realtime-rs"


def read_wav(path: str) -> tuple[np.ndarray, int]:
    with wave.open(path, "rb") as w:
        sr, n, ch, sw = w.getframerate(), w.getnframes(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(n)
    x = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    return x, sr


def write_wav16(path: str, x: np.ndarray, sr: int) -> None:
    if sr != 16000:
        t = np.linspace(0, len(x) - 1, int(round(len(x) * 16000 / sr)))
        x = np.interp(t, np.arange(len(x)), x).astype(np.float32)
    pcm = np.clip(x, -1, 1)
    pcm = (pcm * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes(pcm.tobytes())


def segment(x: np.ndarray, sr: int, n_want: int) -> list[np.ndarray]:
    """Split into n_want segments at the largest silence gaps (energy valleys)."""
    win = int(0.02 * sr)
    n = len(x) // win
    e = np.sqrt((x[: n * win].reshape(n, win) ** 2).mean(axis=1) + 1e-9)
    thr = max(e.mean() * 0.25, e.max() * 0.06)
    silent = e < thr
    # find silence runs, rank by length, cut at the centers of the top (n_want-1)
    runs = []
    i = 0
    while i < n:
        if silent[i]:
            j = i
            while j < n and silent[j]:
                j += 1
            runs.append((i, j))
            i = j
        else:
            i += 1
    # keep only interior runs (not leading/trailing), longest first
    interior = [(a, b) for a, b in runs if a > 2 and b < n - 2]
    interior.sort(key=lambda r: r[1] - r[0], reverse=True)
    cuts = sorted((a + b) // 2 * win for a, b in interior[: max(0, n_want - 1)])
    bounds = [0] + cuts + [len(x)]
    segs = [x[bounds[k]: bounds[k + 1]] for k in range(len(bounds) - 1)]
    # trim leading/trailing silence per segment
    out = []
    for s in segs:
        if len(s) < int(0.15 * sr):
            out.append(s)
            continue
        ee = np.abs(s)
        nz = np.where(ee > thr * 0.5)[0]
        out.append(s[max(0, nz[0] - win): nz[-1] + win] if len(nz) else s)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=int, default=40)
    ap.add_argument("--voices", default="casual_female,casual_male,neutral_female")
    ap.add_argument("--max_sentences", type=int, default=1893)
    ap.add_argument("--euler", type=int, default=3)
    ap.add_argument("--per_sentence", action="store_true",
                    help="one call per sentence — RELIABLE labels (batch+segment misaligns); "
                         "slow (~28s model-load/call) so run as a daemon-down background bake")
    a = ap.parse_args()
    voices = a.voices.split(",")
    wd = os.path.join(OUT, "wav")
    os.makedirs(wd, exist_ok=True)
    tmp = os.path.join(OUT, "_voxtmp.wav")

    sents = [json.loads(l)["text"] for l in open(os.path.join(OUT, "corpus.jsonl"), encoding="utf-8")]
    sents = sents[: a.max_sentences]
    total_ok = 0

    if a.per_sentence:
        for vi, voice in enumerate(voices):
            vtag = 20 + vi
            for i, s in enumerate(sents):
                out = os.path.join(wd, f"s{i:04d}_v{vtag}_r2.wav")
                if os.path.isfile(out):
                    total_ok += 1
                    continue
                try:
                    subprocess.run([VOX, "speak", "--gguf", GGUF, "--voices-dir", VDIR,
                                    "--voice", voice, "--euler-steps", str(a.euler),
                                    "--device", "discrete", "--text", s, "--output", tmp],
                                   cwd=VOXCWD, capture_output=True, timeout=300)
                except Exception as exc:
                    print(f"[vox] {voice} s{i}: {exc}", flush=True)
                    continue
                if os.path.isfile(tmp):
                    x, sr = read_wav(tmp)
                    write_wav16(out, x, sr)
                    total_ok += 1
                if i % 25 == 0:
                    print(f"[vox] {voice} s{i}/{len(sents)} ({total_ok} total)", flush=True)
        print(f"VOX_RENDER_DONE {total_ok} per-sentence wavs (per_sentence mode)", flush=True)
        return 0
    for vi, voice in enumerate(voices):
        vtag = 20 + vi
        for b0 in range(0, len(sents), a.batch):
            batch = sents[b0: b0 + a.batch]
            # already done?
            if all(os.path.isfile(os.path.join(wd, f"s{b0 + k:04d}_v{vtag}_r2.wav"))
                   for k in range(len(batch))):
                continue
            # join with clear pauses (" . ") so segmentation finds boundaries
            text = " . ".join(s.rstrip(".!?") for s in batch) + " ."
            try:
                subprocess.run([VOX, "speak", "--gguf", GGUF, "--voices-dir", VDIR,
                                "--voice", voice, "--euler-steps", str(a.euler),
                                "--device", "discrete", "--text", text, "--output", tmp],
                               cwd=VOXCWD, capture_output=True, timeout=600)
            except Exception as exc:
                print(f"[vox] {voice} b{b0}: {exc}", flush=True)
                continue
            if not os.path.isfile(tmp):
                print(f"[vox] {voice} b{b0}: no output", flush=True)
                continue
            x, sr = read_wav(tmp)
            segs = segment(x, sr, len(batch))
            if len(segs) != len(batch):
                print(f"[vox] {voice} b{b0}: got {len(segs)} segs for {len(batch)} sents "
                      f"(skip mismatched)", flush=True)
                continue
            for k, s in enumerate(segs):
                write_wav16(os.path.join(wd, f"s{b0 + k:04d}_v{vtag}_r2.wav"), s, sr)
                total_ok += 1
            print(f"[vox] {voice} b{b0}-{b0 + len(batch)} ok ({total_ok} total)", flush=True)
    print(f"VOX_RENDER_DONE {total_ok} per-sentence wavs", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
