"""G-VERBATIM — the DECODE table test.  (2026-07-12)

tokenizer.rs:296 —
    "`encode` prefers it [the C gemma4 encoder] when present.
     Decode stays on the Rust id_to_bytes path"

ENCODE  : the C gemma4 encoder, loaded from the .sp-tokenizer FILE.
DECODE  : id_to_bytes, built from the SPTB blob EMBEDDED IN THE .sp-model.

Two tables. If they disagree at an id, the model emits the RIGHT token and we
print the WRONG character. That is exactly the observed failure: the forward is
correct (proved: prefill hiddens predict 4,4,7,1 with margins 3-8) and the head
is correct (proved: int8 vs f32 head, 0/26 argmax flips), yet the text says 4417.

This compares, id by id:
    A. SPTB vocab inside the .sp-model      (what we DECODE with)
    B. SPTB vocab in the .sp-tokenizer file (what the C encoder ENCODES with)
    C. HF tokenizer.json                    (ground truth)
"""
from __future__ import annotations

import json
import mmap
import struct
import sys

SPMODEL = r"D:\F\shannon-prime-repos\models\gemma4-12b-b1-reason.sp-model"
SPTOK = r"D:\F\shannon-prime-repos\models\gemma4-12b-b1.sp-tokenizer"
HF = r"D:\Files\Models\Gemma4\gemma-4-12b-bucket\tokenizer.json"
MAGIC = b"SPTB"


def parse_sptb(mm, off: int):
    """Parse an SPTB header+vocab out of an mmap WITHOUT slurping the file
    (the .sp-model is ~12 GB — read only the small pieces we touch)."""
    p = off + 4
    type_id, = struct.unpack_from("<I", mm, p); p += 4
    vocab_size, = struct.unpack_from("<I", mm, p); p += 4
    n_merges, = struct.unpack_from("<I", mm, p); p += 4
    if not (0 <= type_id <= 8) or not (1000 <= vocab_size <= 1 << 21):
        raise ValueError(f"implausible SPTB @0x{off:x}: type={type_id} vocab={vocab_size}")
    vocab = []
    for _ in range(vocab_size):
        n, = struct.unpack_from("<I", mm, p); p += 4
        if n > 512:
            raise ValueError(f"implausible piece len {n} @0x{p:x}")
        vocab.append(mm[p:p + n].decode("utf-8", "replace")); p += n
    return {"type_id": type_id, "vocab_size": vocab_size, "n_merges": n_merges, "vocab": vocab}


def load_embedded(path: str):
    """Scan for the SPTB blob; 'SPTB' can occur by chance inside weight bytes, so
    validate each candidate header and take the first that parses."""
    f = open(path, "rb")
    mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
    off = -1
    while True:
        off = mm.find(MAGIC, off + 1)
        if off < 0:
            raise ValueError("no valid SPTB blob in " + path)
        try:
            return parse_sptb(mm, off), off
        except Exception:
            continue


def main() -> int:
    print("A. SPTB embedded in the .sp-model  (the DECODE table)")
    A, offa = load_embedded(SPMODEL)
    print(f"   type_id={A['type_id']} vocab={A['vocab_size']} merges={A['n_merges']} @0x{offa:x}")

    print("B. SPTB in the .sp-tokenizer file  (the ENCODE table)")
    try:
        B, offb = load_embedded(SPTOK)
        print(f"   type_id={B['type_id']} vocab={B['vocab_size']} merges={B['n_merges']} @0x{offb:x}")
    except Exception as e:
        print(f"   !! {e}")
        B = None

    print("C. HF tokenizer.json               (ground truth)")
    with open(HF, "r", encoding="utf-8") as f:
        hv = json.load(f)["model"]["vocab"]
    C = {int(i): t for t, i in hv.items()}
    print(f"   vocab={len(C)}\n")

    # the digit ids the gate established from HF
    DIGITS = {236770: "1", 236771: "0", 236812: "4", 236819: "9", 236832: "7"}

    print(f"  {'id':>7}  {'HF (truth)':<14}{'.sp-model DECODE':<20}{'.sp-tokenizer ENCODE':<22}")
    bad = 0
    for tid in sorted(DIGITS):
        a = A["vocab"][tid] if tid < A["vocab_size"] else "<oob>"
        b = B["vocab"][tid] if B and tid < B["vocab_size"] else "<n/a>"
        c = C.get(tid, "<missing>")
        mark = ""
        if a != c:
            mark = "   <<< DECODE TABLE WRONG"
            bad += 1
        print(f"  {tid:>7}  {c!r:<14}{a!r:<20}{b!r:<22}{mark}")

    # full-table diff — how widespread is it?
    n = min(A["vocab_size"], len(C))
    mism = [i for i in range(n) if A["vocab"][i] != C.get(i, "\0")]
    print(f"\n  full-table mismatch (.sp-model DECODE vs HF): {len(mism)} / {n} ids")
    if mism:
        lo, hi = min(mism), max(mism)
        print(f"  mismatched id range: {lo} .. {hi}")
        print(f"  first 12 mismatches:")
        for i in mism[:12]:
            print(f"    id {i:>7}: HF {C.get(i)!r:<18} decode-table {A['vocab'][i]!r}")

    print()
    if bad:
        print("  *** THE DECODE TABLE DISAGREES WITH THE MODEL'S OWN VOCAB AT DIGIT IDS.")
        print("  *** The model emits the RIGHT token; we PRINT the wrong character.")
        return 0
    print("  Digit ids decode correctly. The decode table is NOT the bug at these ids.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

