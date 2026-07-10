"""G-VOICE-0 (offline leg) — the live ear path reproduces the gated KAI-3 export.

For each of the 8 gated eval events: run OUR pipeline (harness.voice.ear: POT i16
IR + softmax(τ)·W_sub) on the event's training-time log-mel features, and compare
against the KAI2 packet that scored 7/8 on the metal (FP32-torch export).

PASS: ≥6/8 events with (a) CTC frame count within ±2 of the packet's k AND
(b) mean best-match cosine ≥ 0.97 between our frames and the packet's.
(The packet lane is FP32; ours is the POT i16 IR — the i16 gate held 0.877==FP32
token recovery, so high-but-not-perfect cosine is the honest expectation.)
"""
import os
import struct
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KAI3 = r"D:\F\shannon-prime-repos\_xbar\p2b\kai3"


def read_kai2(path: str) -> np.ndarray:
    with open(path, "rb") as f:
        magic = f.read(4)
        assert magic == b"KAI2", magic
        k, h = struct.unpack("<II", f.read(8))
        return np.frombuffer(f.read(k * h * 4), dtype="<f4").reshape(k, h)


def main() -> int:
    from harness.voice import ear

    st = ear.status()
    print("ear:", st)
    if not st.get("ok"):
        print("RESULT g-voice0-parity: FAIL (ear unavailable)")
        return 1

    z = np.load(os.path.join(KAI3, "audio_frames.npz"), allow_pickle=True)
    ex, flen, expect = z["eval_X"], z["eval_flen"], z["eval_expect"]
    import glob
    packets = sorted(glob.glob(os.path.join(KAI3, "kai3_audio_packets", "aud_*.bin")))
    ok = 0
    for i in range(len(ex)):
        ours = ear.hear(ex[i][: int(flen[i])])
        pk = read_kai2(packets[i])
        k_ok = abs(ours.shape[0] - pk.shape[0]) <= 2
        if ours.shape[0] == 0 or pk.shape[0] == 0:
            cos = 0.0
        else:
            a = ours / (np.linalg.norm(ours, axis=1, keepdims=True) + 1e-9)
            b = pk / (np.linalg.norm(pk, axis=1, keepdims=True) + 1e-9)
            sim = a @ b.T                      # [k_ours, k_pk]
            cos = float(sim.max(axis=1).mean())  # best-match per our frame
        passed = k_ok and cos >= 0.97
        ok += passed
        print(f"[{i} {expect[i]}] ours k={ours.shape[0]} pkt k={pk.shape[0]} "
              f"cos={cos:.4f} -> {'OK' if passed else 'MISS'}")
    verdict = ok >= 6
    print(f"RESULT g-voice0-parity: {'PASS' if verdict else 'FAIL'} ({ok}/8, device={st.get('device')})")
    return 0 if verdict else 1


if __name__ == "__main__":
    raise SystemExit(main())
