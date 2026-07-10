"""voice_export_ir.py — new ear checkpoint -> OpenVINO IR for the live loader (P1).

Loads var/voice/voice_ctc.pt (the P1 CTC ear), rebuilds the GNA-conservative
encoder, exports ONNX at the STATIC training Tmax (GNA needs static shapes; the
CPU plugin also runs it), converts to OV IR: var/voice/voice_ctc.xml/.bin.
The POT-i16 GNA quantization stays the audio_port lane (G-VOICE-1 silicon leg);
this IR is the FP32 CPU rung so live serving upgrades immediately.

Run: python tools/voice_export_ir.py
"""
from __future__ import annotations

import os

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "var", "voice")


def main() -> int:
    import torch
    import torch.nn as nn

    ck = torch.load(os.path.join(OUT, "voice_ctc.pt"), map_location="cpu",
                    weights_only=False)  # our own ckpt carries numpy vsub
    vsub = ck["vsub"]
    V = len(vsub)
    n_mels = int(ck["n_mels"])
    hidden = int(ck.get("hidden", 256))
    z = np.load(os.path.join(OUT, "voice_frames.npz"), allow_pickle=True)
    tmax = int(z["train_X"].shape[1])
    print(f"ckpt: V={V} n_mels={n_mels} hidden={hidden} best={ck.get('best'):.3f} Tmax={tmax}")

    class Enc(nn.Module):
        # MUST mirror the trainer's Sequential indexing (Dropout shifts indices;
        # eval-mode dropout folds to identity at export).
        def __init__(s):
            super().__init__()
            s.net = nn.Sequential(
                nn.Conv1d(n_mels, hidden, 3, padding=1), nn.ReLU(), nn.Dropout(0.0),
                nn.Conv1d(hidden, hidden, 3, padding=1), nn.ReLU(), nn.Dropout(0.0),
                nn.Conv1d(hidden, hidden, 3, padding=1), nn.ReLU())
            s.head = nn.Conv1d(hidden, V + 1, 1)

        def forward(s, x):                      # [1,T,mel] -> [1,T,V+1]
            return s.head(s.net(x.transpose(1, 2))).transpose(1, 2)

    net = Enc().eval()
    net.load_state_dict(ck["state"])

    onnx_path = os.path.join(OUT, "voice_ctc.onnx")
    torch.onnx.export(net, torch.zeros(1, tmax, n_mels), onnx_path,
                      input_names=["mel"], output_names=["logits"], opset_version=13)
    print(f"onnx -> {onnx_path}")

    import openvino as ov
    m = ov.convert_model(onnx_path)
    ov.save_model(m, os.path.join(OUT, "voice_ctc.xml"), compress_to_fp16=False)
    print(f"IR -> {os.path.join(OUT, 'voice_ctc.xml')}")

    # keep vsub.npy in sync with the checkpoint (the ear + wsub read it)
    np.save(os.path.join(OUT, "vsub.npy"), np.asarray(vsub, dtype=np.int64))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
