"""extract_audio_projection.py — pull Gemma-4-12B-Unified's native audio projection.

Gemma 4 12B UNIFIED is ENCODER-FREE: 640 raw audio samples (40ms @16k) ARE the
audio feature; model.embed_audio.embedding_projection [3840,640] maps them into
the LM residual space (inject_frames + audio token 258881). No encoder, no mel,
no CTC, no training. This extracts that one weight (bf16 -> f32) to
var/voice/embed_audio.npz for the native front-end.
"""
from __future__ import annotations

import json
import os
import struct

import numpy as np

MODEL = r"D:\Files\Models\Gemma4\gemma-4-12b-bucket\model.safetensors"
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "var", "voice", "embed_audio.npz")
NAME = "model.embed_audio.embedding_projection.weight"


def main() -> int:
    with open(MODEL, "rb") as f:
        (hlen,) = struct.unpack("<Q", f.read(8))
        header = json.loads(f.read(hlen))
        meta = header[NAME]
        dtype, shape = meta["dtype"], meta["shape"]
        off0, off1 = meta["data_offsets"]
        base = 8 + hlen + off0
        nbytes = off1 - off0
        f.seek(base)
        raw = f.read(nbytes)
    print(f"{NAME} dtype={dtype} shape={shape} bytes={nbytes}")
    if dtype == "BF16":
        u16 = np.frombuffer(raw, dtype="<u2").astype(np.uint32) << 16
        w = u16.view(np.float32).reshape(shape)
    elif dtype == "F16":
        w = np.frombuffer(raw, dtype="<f2").astype(np.float32).reshape(shape)
    else:
        w = np.frombuffer(raw, dtype="<f4").reshape(shape)
    # Also grab the BOA (256000) / EOA (258883) / audio_token (258881) embed rows so
    # the audio frames can be wrapped in the native <begin_audio>…<end_audio> markers.
    with open(MODEL, "rb") as f:
        (hlen,) = struct.unpack("<Q", f.read(8))
        header = json.loads(f.read(hlen))
        em = header["model.language_model.embed_tokens.weight"]
        e_off0, _ = em["data_offsets"]
        e_base = 8 + hlen + e_off0
        E = em["shape"][1]
        rows = {}
        for name, tid in (("boa", 256000), ("eoa", 258883), ("audio", 258881)):
            f.seek(e_base + tid * E * 2)                 # bf16 = 2 bytes
            u16 = np.frombuffer(f.read(E * 2), dtype="<u2").astype(np.uint32) << 16
            rows[name] = u16.view(np.float32).astype(np.float32)
    scale = float(np.sqrt(E))                            # Gemma input normalizer
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    np.savez(OUT, weight=w.astype(np.float32),
             boa=(rows["boa"] * scale).astype(np.float32),
             eoa=(rows["eoa"] * scale).astype(np.float32),
             audio_tok=(rows["audio"] * scale).astype(np.float32),
             embed_scale=np.float32(scale))
    print(f"wrote {OUT}  weight {w.shape}  |W|mean|abs|={np.abs(w).mean():.5f}  "
          f"boa/eoa L2 ~{np.linalg.norm(rows['boa']*scale):.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
