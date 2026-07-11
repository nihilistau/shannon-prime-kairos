"""EMBEDDING PARITY — is the TRANSCODED embedding row for a token the same vector
as the original bf16 weight?

Why: the served model misreads digits ("2+2" -> "2+4=6"), and digit tokens live
HIGH in the vocab (236770-236832 of 262144). `row * 3840 * 4` = 3.6e9 overflows
int32 — a classic place for a transcode/upload to fetch the WRONG ROW for high
ids while low-id (common word) rows stay perfect. That would make the model see
a different token than we sent, which is exactly the symptom.

Compares, per token id:
    sp-model  token_embd.weight (OK_Q8 codes) * token_embd.weight.scale (per-row)
    vs
    safetensors model.language_model.embed_tokens.weight[id]  (bf16)
by cosine. A correct transcode gives ~0.99+. A row mix-up gives ~0.0-0.3.
"""
from __future__ import annotations

import json
import struct

import numpy as np

SP = r"D:\F\shannon-prime-repos\models\gemma4-12b-b1-reason.sp-model"
ST = r"D:\Files\Models\Gemma4\gemma-4-12b-bucket\model.safetensors"
EMB = "model.language_model.embed_tokens.weight"

# digits (high ids) + controls (low/mid ids)
TOKENS = {
    "'0'": 236771, "'1'": 236770, "'4'": 236812, "'7'": 236832, "'9'": 236819,
    "' '": 236743,
    "low id 100": 100, "low id 1000": 1000, "mid id 50000": 50000,
    "high id 200000": 200000, "top id 262000": 262000,
}


def sp_tensor(path, name):
    with open(path, "rb") as f:
        h = f.read(512)
        tc = struct.unpack_from("<I", h, 316)[0]
        toff = struct.unpack_from("<Q", h, 320)[0]
        doff = struct.unpack_from("<Q", h, 328)[0]
        f.seek(toff)
        for _ in range(tc):
            e = f.read(256)
            n = e[:80].split(b"\0")[0].decode("utf-8", "replace")
            if n == name:
                dt = struct.unpack_from("<I", e, 80)[0]
                dims = [d for d in struct.unpack_from("<8Q", e, 88) if d]
                off = struct.unpack_from("<Q", e, 152)[0]
                size = struct.unpack_from("<Q", e, 160)[0]
                return dt, dims, doff + off, size
    raise KeyError(name)


def main() -> int:
    dt_c, dims_c, off_c, size_c = sp_tensor(SP, "token_embd.weight")
    dt_s, dims_s, off_s, size_s = sp_tensor(SP, "token_embd.weight.scale")
    print(f"sp token_embd: dtype={dt_c} dims={dims_c} bytes={size_c/1e6:.0f}M")
    print(f"sp scale     : dtype={dt_s} dims={dims_s} bytes={size_s/1e6:.1f}M")
    V, E = 262144, 3840
    codes = np.memmap(SP, dtype=np.int8, mode="r", offset=off_c, shape=(V, E))
    scales = np.memmap(SP, dtype=np.float32, mode="r", offset=off_s, shape=(V,))

    with open(ST, "rb") as f:
        n = struct.unpack("<Q", f.read(8))[0]
        hdr = json.loads(f.read(n))
        meta = hdr[EMB]
        base = 8 + n + meta["data_offsets"][0]
        Vh, Eh = meta["shape"]
        print(f"hf  embed    : shape={meta['shape']} dtype={meta['dtype']}\n")

        print(f"{'token':16} {'id':>7}  {'cos(sp_dequant, hf)':>20}  {'|sp|':>8} {'|hf|':>8}")
        bad = 0
        for label, tid in TOKENS.items():
            f.seek(base + tid * Eh * 2)           # bf16 = 2 bytes
            u16 = np.frombuffer(f.read(Eh * 2), dtype="<u2").astype(np.uint32) << 16
            hf = u16.view(np.float32).astype(np.float64)
            sp = codes[tid].astype(np.float64) * float(scales[tid])
            c = float(sp @ hf / (np.linalg.norm(sp) * np.linalg.norm(hf) + 1e-9))
            flag = "" if c > 0.95 else "   <<< MISMATCH"
            bad += (c <= 0.95)
            print(f"{label:16} {tid:7d}  {c:20.4f}  {np.linalg.norm(sp):8.2f} {np.linalg.norm(hf):8.2f}{flag}")

    print(f"\nVERDICT: {'transcode OK for all probed rows' if bad == 0 else f'{bad} ROW(S) WRONG — the engine sees a different vector than the real weight'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
