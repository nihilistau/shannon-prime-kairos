"""distill_real.py — build REAL (h, Mimi-z) pairs (ADR-KAI5 P0).

For each sentence: POST it to the served 12B (SP_HIDDEN_DUMP writes the per-position
post-out_norm hidden to _hd_dump.bin) -> h[n,3840]; TTS wav -> Mimi 512-d latent
z[T,512]; align h(n)->T; accumulate. Saves pairs.npz.

The daemon must be running with SP_HIDDEN_DUMP=<this dir>/_hd_dump.bin and be otherwise
idle (the dump file is process-global; one request at a time).
"""
import os, sys, glob, wave, json, time, urllib.request
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from distill_pairs import mimi_encode, align  # proven Mimi encode + resample

HERE = os.path.dirname(os.path.abspath(__file__))
DUMP = os.path.join(HERE, "_hd_dump.bin")
E = 3840
DAEMON = "http://127.0.0.1:3000/v1/chat"


def load_wav(p):
    f = wave.open(p); raw = f.readframes(f.getnframes()); sr = f.getframerate(); f.close()
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0, sr


def get_hidden(text):
    """POST the text (prefill dumps hidden), then read _hd_dump.bin -> [n, E]."""
    if os.path.exists(DUMP):
        os.remove(DUMP)
    body = json.dumps({"messages": [{"role": "user", "content": text}], "max_tokens": 1}).encode()
    req = urllib.request.Request(DAEMON, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        for line in r:  # read until [DONE]; don't wait for the keepalive stream to close
            if b"[DONE]" in line:
                break
    time.sleep(0.2)
    raw = np.fromfile(DUMP, dtype=np.float32)
    n = raw.size // E
    return raw[: n * E].reshape(n, E)


def main():
    sents = [l.strip() for l in open(os.path.join(HERE, "sentences.txt"), encoding="utf-8") if l.strip()]
    wavs = sorted(glob.glob(os.path.join(HERE, "wavs", "*.wav")))
    assert len(sents) == len(wavs), f"{len(sents)} sents vs {len(wavs)} wavs"
    Hs, Zs = [], []
    for i, (text, wp) in enumerate(zip(sents, wavs)):
        pcm, sr = load_wav(wp)
        z = mimi_encode(pcm, sr)                 # [T, 512]
        h = get_hidden(text)                     # [n, 3840]
        h_rs, z = align(h, z)                    # both -> [T, *]
        Hs.append(h_rs); Zs.append(z)
        if i % 5 == 0:
            print(f"  {i}/{len(sents)}  h{h.shape} z{z.shape}", flush=True)
    H = np.concatenate(Hs).astype(np.float32); Z = np.concatenate(Zs).astype(np.float32)
    out = os.path.join(HERE, "pairs_real.npz")
    np.savez(out, h=H, z=Z)
    print(f"WROTE {out}  H{H.shape} Z{Z.shape}", flush=True)


if __name__ == "__main__":
    main()
