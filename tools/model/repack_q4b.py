"""REPACK -> OK_Q4B. A fresh Q4 that is not the broken one.

WHY (measured today, not assumed):

  * Decode is MEMORY-BOUND on the weight read. Proof: the (broken) all-Q4 model decodes at
    32.6 tok/s where the served Q8 model does 22. Q4 is the speed lever we have been
    hunting all day — 1.5x, plus ~3.4 GB of VRAM back.

  * The existing all-Q4 models are BOTH gibberish. `gemma4-12b.sp-model` and
    `gemma4-12b-qat.sp-model` are different files with the same dtype profile (OK_Q4 x329)
    and both emit "etIlayeIlayeIlaye...". So this was never "the QAT weights are bad" —
    **the OK_Q4 code path itself is broken.**

  * And the proof of the fix is sitting inside the model we already serve:
        b1-reason (WORKS):  OK_Q8 x233 + OK_Q4B x96
    96 OK_Q4B tensors, in production, fine. OK_Q4B (per-32-block f16 scale) works;
    OK_Q4 (per-row scale) does not. So do not debug OK_Q4 — emit Q4B.

THE ONE TENSOR THAT MUST STAY Q8: token_embd.weight.
It is the TIED HEAD *and* the embed gather, and `k_embed_packed_one` dequantises 4-bit rows
as `code * row_scale/7` — the OK_Q4 convention, with a PER-ROW scale. A Q4B embedding has no
row_scale (its scales are per-32-block, in a .bscale sibling), so the gather would read NULL
and the model would produce exactly the gibberish we already have. It is also the tensor
G-VERBATIM leans on. So: Q4B everywhere, Q8 at the head. That costs ~1 GB and buys
correctness where correctness is decided.

VALUES come from the existing Q8 codes rather than the 22 GB bf16 safetensors. Q8 is within
~0.4% of bf16; the 4-bit step is ~3%, so the 4-bit error dominates and the double-quant is
in the noise — and it avoids the HF name-mapping entirely. (If a future run wants bf16
values, map blk.N.attn_q -> model.language_model.layers.N.self_attn.q_proj and stream it.)

RECIPE (byte-for-byte from sp_transcode.c add_q4b — the tool that built the working 96):
    codes : int4 in [-7,7], nibble-packed, LOW nibble = even column
    scale : s = maxabs/7 over each 32-column block, computed f32 and ROUNDED THROUGH f16;
            codes are then quantised against the STORED (f16-roundtripped) scale
    sibling ".bscale" : f16[rows * ceil(cols/32)]

    python tools/model/repack_q4b.py                 # dry run: prints the plan
    python tools/model/repack_q4b.py --write         # ~9.4 GB in, ~6.5 GB out

STATUS: the file WRITES and the header now passes every check the loader makes. It does
NOT yet load. One defect remains, and it is precisely located — see FINISH THIS below.

    the format defended itself THREE times, correctly, and each error named its own cause:
      1. "header CRC-32 mismatch"        -> crc32 over [0,360), stored @360. Fixed.
      2. "file_size != stat size"        -> file_size @336. Fixed.
      3. "sp_model_to_gemma4: bad weight token_embd.weight"   <- HERE

FINISH THIS (sp_model.h §4, the 256-byte tensor entry):

    char     name[80];        /*   0 */      uint64_t offset_in_data;  /* 152 */
    uint32_t dtype_id;        /*  80 */      uint64_t size_bytes;      /* 160 */
    uint32_t n_dims;          /*  84 */      uint32_t block_size;      /* 168 */
    uint64_t dims[8];         /*  88 */      uint32_t block_count;     /* 172 */
    uint8_t  blake3[32];      /* 176   per-tensor digest */
    uint64_t name_hash;       /* 208   xxh64(name); TABLE SORTED ASCENDING */

sp_model_find_tensor (sp_model_load.c:214) BINARY-SEARCHES the table on `name_hash`:
    "table sorted by name_hash asc"
This writer zero-fills bytes 176..256, so every name_hash is 0 and the table is unsorted —
the search cannot find token_embd.weight, and the bridge reports it as a "bad weight". The
tensor entry itself is byte-identical to the source (verified field by field); only the
LOOKUP is broken.

So:
  1. name_hash = xxh64(name, seed=0) at offset 208 for every entry.
  2. SORT the emitted table ascending by name_hash before writing it.
  3. Kept tensors: copy the SOURCE's raw 256-byte entry (preserves blake3 AND name_hash)
     and patch only offset_in_data — do not rebuild them from scratch.
  4. New tensors (Q4B codes + .bscale): compute name_hash; check whether blake3 is
     actually verified at load (sp_model_load.c:90 only sweeps Spinor block geometry, so
     probably not) before spending effort on the digest.
"""
from __future__ import annotations

import os
import struct
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from xxh64 import xxh64  # noqa: E402  — validated: reproduces all 996 name_hash in the source

SRC = r"D:\F\shannon-prime-repos\models\gemma4-12b-b1-reason.sp-model"
DST = r"D:\F\shannon-prime-repos\models\gemma4-12b-q4b.sp-model"

DT_F16, DT_Q8, DT_F32, DT_Q4B_CODES, DT_F16_BSCALE = 1, 10, 12, 13, 14
HDR = 512
ALIGN = 256

# The tied head + embed gather. MUST stay Q8 — see the module docstring.
KEEP_Q8 = {"token_embd.weight"}


def read_table(path):
    with open(path, "rb") as f:
        hdr = f.read(HDR)
        tc = struct.unpack_from("<I", hdr, 316)[0]
        toff = struct.unpack_from("<Q", hdr, 320)[0]
        doff = struct.unpack_from("<Q", hdr, 328)[0]
        f.seek(toff)
        ents = []
        for _ in range(tc):
            e = f.read(256)
            ents.append({
                "raw": bytearray(e),
                "name": e[:80].split(b"\0")[0].decode("utf-8", "replace"),
                "dt": struct.unpack_from("<I", e, 80)[0],
                "ndim": struct.unpack_from("<I", e, 84)[0],
                "dims": list(struct.unpack_from("<8Q", e, 88)),
                "off": struct.unpack_from("<Q", e, 152)[0],
                "size": struct.unpack_from("<Q", e, 160)[0],
                "esz": struct.unpack_from("<I", e, 168)[0],
                "nel": struct.unpack_from("<I", e, 172)[0],
            })
    return hdr, toff, doff, ents


def q4b_pack(rows: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """rows: f32 [R, C] -> (codes uint8 [R, ceil(C/2)], bscale f16 [R, nblk]).
    Mirrors add_q4b exactly, including the f16 round-trip of the scale BEFORE quantising."""
    R, C = rows.shape
    nblk = (C + 31) // 32
    pad = nblk * 32 - C
    w = np.pad(rows, ((0, 0), (0, pad))) if pad else rows
    blocks = w.reshape(R, nblk, 32)

    ma = np.abs(blocks).max(axis=2)                      # [R, nblk]
    s16 = (ma / 7.0).astype(np.float16)                  # ROUND THROUGH f16
    sf = s16.astype(np.float32)                          # the STORED scale
    inv = np.where(sf > 0, 1.0 / np.where(sf > 0, sf, 1.0), 0.0)

    k = np.rint(blocks * inv[:, :, None]).astype(np.int32)
    k = np.clip(k, -7, 7).reshape(R, nblk * 32)[:, :C]

    nib = (k & 0xF).astype(np.uint8)                     # two's-complement nibble
    if C % 2:
        nib = np.pad(nib, ((0, 0), (0, 1)))
    even, odd = nib[:, 0::2], nib[:, 1::2]               # LOW nibble = even column
    codes = (even | (odd << 4)).astype(np.uint8)
    return codes, s16


def main() -> int:
    write = "--write" in sys.argv
    hdr, toff, doff, ents = read_table(SRC)
    by_name = {e["name"]: e for e in ents}

    # which Q8 matmuls become Q4B
    conv = [e for e in ents
            if e["dt"] == DT_Q8 and e["name"] not in KEEP_Q8
            and (e["name"] + ".scale") in by_name]
    keep = [e for e in ents if e not in conv]
    drop = {e["name"] + ".scale" for e in conv}          # the f32 row-scale siblings die

    src_gb = os.path.getsize(SRC) / 1e9
    saved = sum(e["size"] + by_name[e["name"] + ".scale"]["size"] for e in conv)
    newsz = 0
    for e in conv:
        C, R = e["dims"][0], e["dims"][1] * (e["dims"][2] or 1)
        newsz += R * ((C + 1) // 2) + R * ((C + 31) // 32) * 2

    print(f"source : {os.path.basename(SRC)}  {src_gb:.1f} GB  {len(ents)} tensors")
    print(f"  Q8 matmuls -> Q4B : {len(conv)}")
    print(f"  kept as-is        : {len(keep) - len(drop)} (incl. {len(KEEP_Q8)} Q8 head, "
          f"{sum(1 for e in ents if e['dt'] == DT_Q4B_CODES)} already-Q4B)")
    print(f"  HEAD STAYS Q8     : {', '.join(sorted(KEEP_Q8))}")
    print(f"\nestimated output  : {(src_gb*1e9 - saved + newsz)/1e9:.1f} GB "
          f"(was {src_gb:.1f})")
    if not write:
        print("\n(dry run — pass --write)")
        return 0

    t0 = time.time()
    out_ents: list[dict] = []
    with open(SRC, "rb") as fi, open(DST, "wb") as fo:
        fo.write(b"\0" * HDR)
        table_bytes = 256 * len(ents)                    # tensor COUNT is unchanged:
        fo.write(b"\0" * table_bytes)                    # (codes+scale) -> (codes+bscale)
        # tensor_data_offset MUST be a multiple of 65536 (sp_model.h:103). 0x1000 is not.
        pad = (-fo.tell()) % 0x10000
        fo.write(b"\0" * pad)
        new_doff = fo.tell()

        def emit(name, dt, ndim, dims, payload, esz, nel, src_raw=None):
            """`src_raw` = the SOURCE's 256-byte entry. When a tensor is copied through
            unchanged we reuse its entry verbatim and patch only the offset, which keeps
            blake3 (@176) AND name_hash (@208) intact. Only genuinely NEW tensors (the Q4B
            codes and their .bscale) get an entry built from scratch — and those get their
            name_hash computed, because sp_model_find_tensor BINARY-SEARCHES on it."""
            cur = fo.tell()
            gap = (-(cur - new_doff)) % ALIGN
            if gap:
                fo.write(b"\0" * gap)
            off = fo.tell() - new_doff
            fo.write(payload)

            e = bytearray(src_raw) if src_raw is not None else bytearray(256)
            if src_raw is None:
                nb = name.encode()[:79]
                e[0:len(nb)] = nb
                struct.pack_into("<I", e, 80, dt)
                struct.pack_into("<I", e, 84, ndim)
                for i, d in enumerate(dims[:8]):
                    struct.pack_into("<Q", e, 88 + 8 * i, d)
                struct.pack_into("<I", e, 168, esz)
                struct.pack_into("<I", e, 172, nel)
                # blake3 @176 stays zero — sp_model_load.c:90 only sweeps Spinor block
                # geometry, so the per-tensor digest is not verified at load.
                struct.pack_into("<Q", e, 208, xxh64(name.encode()))   # THE SEARCH KEY
            struct.pack_into("<Q", e, 152, off)                        # always: new offset
            struct.pack_into("<Q", e, 160, len(payload))
            out_ents.append({"raw": e, "name": name,
                             "hash": struct.unpack_from("<Q", e, 208)[0]})

        done = 0
        for e in ents:
            if e["name"] in drop:
                continue                                  # its row-scale is superseded
            if e in conv:
                C = int(e["dims"][0])
                R = int(e["dims"][1]) * int(e["dims"][2] or 1)
                sc = by_name[e["name"] + ".scale"]
                fi.seek(doff + e["off"])
                codes8 = np.frombuffer(fi.read(e["size"]), dtype=np.int8).reshape(R, C)
                fi.seek(doff + sc["off"])
                rs = np.frombuffer(fi.read(sc["size"]), dtype=np.float32)[:R]
                # dequant Q8 -> f32 (the engine's convention: code * row_scale/127)
                w = codes8.astype(np.float32) * (rs[:, None] / 127.0)
                codes, bs = q4b_pack(w)
                emit(e["name"], DT_Q4B_CODES, e["ndim"], e["dims"],
                     codes.tobytes(), 1, R * ((C + 1) // 2))
                emit(e["name"] + ".bscale", DT_F16_BSCALE, 1,
                     [bs.size] + [0] * 7, bs.tobytes(), 2, bs.size)
                done += 1
                if done % 25 == 0:
                    print(f"  ... {done}/{len(conv)} repacked  ({time.time()-t0:.0f}s)")
            else:
                fi.seek(doff + e["off"])
                emit(e["name"], e["dt"], e["ndim"], e["dims"],
                     fi.read(e["size"]), e["esz"], e["nel"], src_raw=e["raw"])

        # header: copy the source's, fix the counts/offsets, RECOMPUTE THE CRC.
        # sp_model_load.c:143 checks crc32 over [0, 360) against the u32 at offset 360, and
        # every field we just changed (tensor count @316, table @320, data @328) is INSIDE
        # that window. Skip this and the daemon refuses the file outright:
        #     sp_model_load -> status=-10: header CRC-32 mismatch
        # (Which it did. The format defended itself, correctly.)
        # sp_model.h pins the whole header, and sp_model_load checks EVERY field:
        #     tensor_count @316 · tensor_table_offset @320 · tensor_data_offset @328
        #     (must be a multiple of 65536) · file_size @336 · header_crc32 @360 over [0,360)
        # I set the first three, forgot file_size, and the loader caught it:
        #     status=-10: file_size != stat size
        # The format defended itself twice (CRC, then size). Good format.
        import zlib
        total = fo.tell()
        h = bytearray(hdr)
        struct.pack_into("<I", h, 316, len(out_ents))
        struct.pack_into("<Q", h, 320, HDR)
        struct.pack_into("<Q", h, 328, new_doff)
        struct.pack_into("<Q", h, 336, total)                 # file_size @336
        struct.pack_into("<I", h, 360, zlib.crc32(bytes(h[:360])) & 0xFFFFFFFF)
        fo.seek(0)
        fo.write(h)

        # SORT THE TABLE BY name_hash ASCENDING. sp_model_find_tensor binary-searches it
        # (sp_model_load.c:217: "table sorted by name_hash asc"). An unsorted table is not
        # a slow table — it is a table where lookups silently fail, which is exactly how
        # the first attempt died ("bad weight token_embd.weight" — the entry was perfect,
        # the SEARCH could not reach it).
        out_ents.sort(key=lambda x: x["hash"])
        for i, oe in enumerate(out_ents):
            fo.seek(HDR + 256 * i)
            fo.write(oe["raw"])

    print(f"\nwrote {DST}")
    print(f"  {os.path.getsize(DST)/1e9:.1f} GB   {len(out_ents)} tensors   "
          f"{time.time()-t0:.0f}s")
    print("\nNOW GATE IT. It is not a model until G-VERBATIM and a coherence probe say so —")
    print("two all-Q4 models on this disk are gibberish and both loaded perfectly.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


