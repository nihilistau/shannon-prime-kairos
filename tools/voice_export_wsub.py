"""One-time W_sub export for the LATENT VOICE ear (ADR-KAI4 P0). Torch-free.

Builds var/voice/wsub.npz = {wsub [V,E] f32, vsub_ids [V] i64, tau} from:
  * vsub_ids  — _xbar/p2b/kai3/audio_frames.npz (written by the KAI-3 trainer)
  * embed rows — the gemma-4-12b safetensors bucket (read with numpy alone:
                 safetensors = 8-byte header-len + JSON header + raw buffer;
                 bf16 rows are widened to f32 via the uint16<<16 trick)
  * scale      — ×√H (H = hidden), the trainer's on-manifold scaling
  * tau        — 0.2 (the KAI-3 export sharpening)

Usage:  python tools/voice_export_wsub.py
        [--bucket D:/Files/Models/Gemma4/gemma-4-12b-bucket]
        [--frames D:/F/shannon-prime-repos/_xbar/p2b/kai3/audio_frames.npz]
Also copies the POT GNA IR into var/voice/.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import struct
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "var", "voice")
KAI3 = r"D:\F\shannon-prime-repos\_xbar\p2b\kai3"


def read_safetensors_rows(path: str, tensor_name: str, rows: np.ndarray) -> np.ndarray:
    """Read specific ROWS of a 2-D tensor from a .safetensors file, numpy-only."""
    with open(path, "rb") as f:
        (hlen,) = struct.unpack("<Q", f.read(8))
        header = json.loads(f.read(hlen))
        if tensor_name not in header:
            raise KeyError(tensor_name)
        meta = header[tensor_name]
        dtype, shape = meta["dtype"], meta["shape"]
        off0, _ = meta["data_offsets"]
        base = 8 + hlen + off0
        n_rows, width = shape
        itemsize = {"BF16": 2, "F16": 2, "F32": 4}[dtype]
        out = np.empty((len(rows), width), dtype=np.float32)
        for i, r in enumerate(sorted(range(len(rows)), key=lambda k: int(rows[k]))):
            rid = int(rows[r])
            f.seek(base + rid * width * itemsize)
            raw = f.read(width * itemsize)
            if dtype == "BF16":
                u16 = np.frombuffer(raw, dtype="<u2").astype(np.uint32) << 16
                out[r] = u16.view(np.float32) if u16.dtype == np.float32 else \
                    np.frombuffer(u16.astype("<u4").tobytes(), dtype="<f4")
            elif dtype == "F16":
                out[r] = np.frombuffer(raw, dtype="<f2").astype(np.float32)
            else:
                out[r] = np.frombuffer(raw, dtype="<f4")
        return out


def find_embed_shard(bucket: str) -> tuple[str, str]:
    """Locate embed_tokens.weight in a (possibly sharded) safetensors bucket."""
    idx = os.path.join(bucket, "model.safetensors.index.json")
    if os.path.isfile(idx):
        m = json.load(open(idx))["weight_map"]
        for name, shard in m.items():
            if name.endswith("embed_tokens.weight"):
                return os.path.join(bucket, shard), name
    for st in glob.glob(os.path.join(bucket, "*.safetensors")):
        with open(st, "rb") as f:
            (hlen,) = struct.unpack("<Q", f.read(8))
            header = json.loads(f.read(hlen))
        for name in header:
            if name.endswith("embed_tokens.weight"):
                return st, name
    raise FileNotFoundError(f"embed_tokens.weight not found under {bucket}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bucket", default=r"D:\Files\Models\Gemma4\gemma-4-12b-bucket")
    ap.add_argument("--frames", default=os.path.join(KAI3, "audio_frames.npz"))
    ap.add_argument("--tau", type=float, default=0.2)
    a = ap.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)
    z = np.load(a.frames)
    vsub = z["vsub_ids"].astype(np.int64)
    print(f"vsub_ids: {len(vsub)} tokens from {a.frames}")

    shard, name = find_embed_shard(a.bucket)
    print(f"embed shard: {shard} :: {name}")
    rows = read_safetensors_rows(shard, name, vsub)
    H = rows.shape[1]
    wsub = rows * np.sqrt(np.float32(H))
    print(f"wsub: [{wsub.shape[0]}, {H}] (x sqrt({H}) scaled)")

    np.savez(os.path.join(OUT_DIR, "wsub.npz"), wsub=wsub.astype(np.float32),
             vsub_ids=vsub, tau=np.float32(a.tau))
    print(f"wrote {os.path.join(OUT_DIR, 'wsub.npz')}")

    for fn in ("audio_ctc_pot_gna.xml", "audio_ctc_pot_gna.bin",
               "audio_ctc_pot_gna.mapping"):
        src = os.path.join(KAI3, "ov_work", "pot", fn)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(OUT_DIR, fn))
            print(f"copied {fn}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
