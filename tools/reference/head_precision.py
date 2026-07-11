"""G-VERBATIM — THE HEAD TEST.  (2026-07-12)

HYPOTHESIS: the tied LM head is the ONLY matmul in the served model whose
ACTIVATIONS are crushed to int8, and that noise is larger than the logit margin
between confusable tokens (digits), so the argmax coin-flips.

  cuda_forward.cu:1725  the f32 embedding uploads ONLY if V*E*4 <= 2 GB.
                        12B: 262144*3840*4 = 4.03 GB  ->  NEVER resident.
  cuda_forward.cu:2650  tied head + no f32 embd  ->  REQUIRES SP_CUDA_DECODE_INT8=1.
  gemv_w_packed()       -> k_quant_act_int8(h)   (int8, per-16-block absmax scale)
                        -> k_gemv_q8_dp4a_v2(int8 codes . int8 acts)

Every other matmul dp4a's too, but its error is absorbed by the residual stream.
The HEAD's output IS the decision.

KEY ALGEBRA: dp4a accumulates int32 exactly and the block scale is CONSTANT
within its 16-lane block, so

    logit_int8[v] = row_scale[v]/127 * ( codes[v,:] @ dequant(quant(h)) )
    logit_f32 [v] = row_scale[v]/127 * ( codes[v,:] @ h )

i.e. the served head is the honest head fed a ROUND-TRIPPED activation. So both
logit vectors come from ONE pass over the weights against a small [E x 2P] matrix.

We take the engine's OWN post-output_norm hidden (SP_HIDDEN_DUMP, written by
g4_kv_step through the resident weights the daemon serves with), sweep the prompt
positions, apply final_logit_softcapping=30 to both, and count ARGMAX FLIPS.
"""
from __future__ import annotations

import json
import struct
import sys

import numpy as np

SP = r"D:\F\shannon-prime-repos\models\gemma4-12b-b1-reason.sp-model"
DUMP = r"D:\F\shannon-prime-repos\shannon-prime-kairos\var\hidden\head.bin"
TOK = r"D:\Files\Models\Gemma4\gemma-4-12b-bucket\tokenizer.json"
V, E = 262144, 3840
SOFTCAP, QMAX, BLK = 30.0, 127.0, 16


def sp_tensor(path, name):
    with open(path, "rb") as f:
        h = f.read(512)
        tc = struct.unpack_from("<I", h, 316)[0]
        toff, doff = struct.unpack_from("<Q", h, 320)[0], struct.unpack_from("<Q", h, 328)[0]
        f.seek(toff)
        for _ in range(tc):
            e = f.read(256)
            if e[:80].split(b"\0")[0].decode("utf-8", "replace") == name:
                return doff + struct.unpack_from("<Q", e, 152)[0]
    raise KeyError(name)


def act_roundtrip(h: np.ndarray) -> np.ndarray:
    """EXACTLY k_quant_act_int8 then dequant: per-16-block absmax scale, RTN int8."""
    n = h.size
    npad = (n + BLK - 1) // BLK * BLK
    hp = np.zeros(npad, dtype=np.float64)
    hp[:n] = h
    b = hp.reshape(-1, BLK)
    scale = np.abs(b).max(axis=1) / QMAX
    inv = np.where(scale > 0, 1.0 / np.maximum(scale, 1e-30), 0.0)
    q = np.rint(b * inv[:, None]).clip(-127, 127)
    return (q * scale[:, None]).reshape(-1)[:n]


def main() -> int:
    hid = np.fromfile(DUMP, dtype=np.float32)
    if not hid.size or hid.size % E:
        print(f"!! bad dump ({hid.size} floats) — is SP_HIDDEN_DUMP armed?")
        return 1
    hid = hid.reshape(-1, E)
    npos = hid.shape[0]

    vocab = {}
    try:
        with open(TOK, "r", encoding="utf-8") as f:
            for t, i in json.load(f)["model"]["vocab"].items():
                vocab[int(i)] = t
    except Exception as e:
        print(f"(tokenizer unavailable: {e})")
    name = lambda i: repr(vocab.get(int(i), f"<{i}>"))

    codes = np.memmap(SP, dtype=np.int8, mode="r", offset=sp_tensor(SP, "token_embd.weight"),
                      shape=(V, E))
    rs = np.array(np.memmap(SP, dtype=np.float32, mode="r",
                            offset=sp_tensor(SP, "token_embd.weight.scale"),
                            shape=(V,)), dtype=np.float64) / QMAX

    P = int(sys.argv[1]) if len(sys.argv) > 1 else min(24, npos)
    sel = list(range(npos - P, npos))
    print(f"hidden dump: {npos} positions x {E} (post-output_norm = the head's input)")
    print(f"probing the last {P} positions\n")

    Hf = np.stack([hid[p].astype(np.float64) for p in sel], axis=1)       # [E, P] honest
    Hq = np.stack([act_roundtrip(hid[p].astype(np.float64)) for p in sel], axis=1)  # [E, P] served
    X = np.concatenate([Hf, Hq], axis=1)                                   # [E, 2P] one pass

    Z = np.empty((V, 2 * P), dtype=np.float64)
    STEP = 8192
    for i in range(0, V, STEP):
        Z[i:i + STEP] = (np.asarray(codes[i:i + STEP], dtype=np.float64) @ X) * rs[i:i + STEP, None]
    Z = SOFTCAP * np.tanh(Z / SOFTCAP)                                     # final_logit_softcapping
    A, B = Z[:, :P], Z[:, P:]                                              # honest | served

    flips = 0
    print(f"  {'pos':>4}  {'HONEST f32 head':<22} {'SERVED int8 head':<22} {'margin':>8} {'noise':>8}")
    for j, p in enumerate(sel):
        a, b = A[:, j], B[:, j]
        ta, tb = int(np.argmax(a)), int(np.argmax(b))
        srt = np.sort(a)[::-1]
        margin = srt[0] - srt[1]
        noise = float(np.sqrt(np.mean((a - b) ** 2)))
        flag = ""
        if ta != tb:
            flips += 1
            flag = "  <<< FLIPPED"
        print(f"  {p:>4}  {name(ta):<22} {name(tb):<22} {margin:8.4f} {noise:8.4f}{flag}")

    print(f"\n  ARGMAX FLIPS: {flips}/{P} positions")
    print(f"  mean top1-top2 margin : {np.mean([np.sort(A[:,j])[::-1][0]-np.sort(A[:,j])[::-1][1] for j in range(P)]):.4f}")
    print(f"  mean int8 logit noise : {np.mean([np.sqrt(np.mean((A[:,j]-B[:,j])**2)) for j in range(P)]):.4f}")
    if flips:
        print("\n  *** THE INT8 ACTIVATION QUANT IN THE TIED HEAD CHANGES THE MODEL'S CHOICE.")
        print("  *** Fix: feed the head f32 activations (keep int8 WEIGHTS) — k_gemv_q8_xf32.")
    else:
        print("\n  No flip in this window. Compare margin vs noise: where the margin is")
        print("  the same order as the noise, the token is a coin-flip (digits live there).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

