"""XXH64 (seed 0) — the tensor-table key.

sp_model_find_tensor (sp_model_load.c:214) BINARY-SEARCHES the tensor table on
`name_hash` — "table sorted by name_hash asc" — and sp_model.h §4 puts that field at
offset 208 of the 256-byte entry.

I am NOT assuming this is stock XXH64. `verify()` recomputes the hash of every tensor name
in an existing, known-good model and compares against the name_hash the file actually
stores. If it reproduces all 996, the implementation is right by construction and the
repacker can be trusted to write a table the C loader can search.
"""
from __future__ import annotations

import struct

M = 0xFFFFFFFFFFFFFFFF
P1 = 0x9E3779B185EBCA87
P2 = 0xC2B2AE3D27D4EB4F
P3 = 0x165667B19E3779F9
P4 = 0x85EBCA77C2B2AE63
P5 = 0x27D4EB2F165667C5


def _rotl(x: int, r: int) -> int:
    return ((x << r) | (x >> (64 - r))) & M


def _round(acc: int, val: int) -> int:
    acc = (acc + (val * P2)) & M
    acc = _rotl(acc, 31)
    return (acc * P1) & M


def _merge(acc: int, val: int) -> int:
    acc ^= _round(0, val)
    return ((acc * P1) + P4) & M


def xxh64(data: bytes, seed: int = 0) -> int:
    n = len(data)
    i = 0
    if n >= 32:
        v1 = (seed + P1 + P2) & M
        v2 = (seed + P2) & M
        v3 = seed & M
        v4 = (seed - P1) & M
        while i + 32 <= n:
            v1 = _round(v1, struct.unpack_from("<Q", data, i)[0])
            v2 = _round(v2, struct.unpack_from("<Q", data, i + 8)[0])
            v3 = _round(v3, struct.unpack_from("<Q", data, i + 16)[0])
            v4 = _round(v4, struct.unpack_from("<Q", data, i + 24)[0])
            i += 32
        h = (_rotl(v1, 1) + _rotl(v2, 7) + _rotl(v3, 12) + _rotl(v4, 18)) & M
        h = _merge(h, v1)
        h = _merge(h, v2)
        h = _merge(h, v3)
        h = _merge(h, v4)
    else:
        h = (seed + P5) & M

    h = (h + n) & M

    while i + 8 <= n:
        h ^= _round(0, struct.unpack_from("<Q", data, i)[0])
        h = ((_rotl(h, 27) * P1) + P4) & M
        i += 8
    if i + 4 <= n:
        h ^= (struct.unpack_from("<I", data, i)[0] * P1) & M
        h = ((_rotl(h, 23) * P2) + P3) & M
        i += 4
    while i < n:
        h ^= (data[i] * P5) & M
        h = (_rotl(h, 11) * P1) & M
        i += 1

    h ^= h >> 33
    h = (h * P2) & M
    h ^= h >> 29
    h = (h * P3) & M
    h ^= h >> 32
    return h


def verify(model_path: str) -> bool:
    """Reproduce every name_hash in a known-good model. If this fails, the repacker would
    write a table the C binary search cannot walk — and the model would load as garbage or
    not at all."""
    with open(model_path, "rb") as f:
        hdr = f.read(512)
        tc = struct.unpack_from("<I", hdr, 316)[0]
        toff = struct.unpack_from("<Q", hdr, 320)[0]
        f.seek(toff)
        bad = 0
        prev = -1
        sorted_ok = True
        for _ in range(tc):
            e = f.read(256)
            name = e[:80].split(b"\0")[0]
            stored = struct.unpack_from("<Q", e, 208)[0]
            if xxh64(name) != stored:
                bad += 1
            if stored < prev:
                sorted_ok = False
            prev = stored
    print(f"  {tc} tensors :: name_hash mismatches = {bad}")
    print(f"  table sorted ascending by name_hash : {sorted_ok}")
    return bad == 0 and sorted_ok


if __name__ == "__main__":
    import sys
    p = sys.argv[1] if len(sys.argv) > 1 else \
        r"D:\F\shannon-prime-repos\models\gemma4-12b-b1-reason.sp-model"
    print(f"verifying xxh64 against {p}")
    ok = verify(p)
    print("\n" + ("XXH64 CONFIRMED — safe to write tables." if ok else
                  "MISMATCH — do NOT write a table with this hash."))
    raise SystemExit(0 if ok else 1)
