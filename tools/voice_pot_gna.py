"""voice_pot_gna.py — POT DefaultQuantization (GNA target) for the P1 voice ear.

Adapts the KAI-3 POT lane to our voice_ctc ONNX (input layout [1, T, n_mels]).
POT (openvino-dev 2023.3) emits GNA-native i16 scale factors the libGNA graph
compiler trusts. Calibrates on the training frames. Outputs var/voice/
voice_ctc_gna.xml/.bin. G-VOICE-1 silicon leg: score i16 vs FP32 recovery.

Run: python tools/voice_pot_gna.py
"""
from __future__ import annotations

import os

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "var", "voice")


def main() -> int:
    import openvino as ov
    from openvino.tools.pot import DataLoader, IEEngine, load_model, save_model, create_pipeline

    onnx = os.path.join(OUT, "voice_ctc.onnx")
    z = np.load(os.path.join(OUT, "voice_frames.npz"), allow_pickle=True)
    n_mels = int(z["n_mels"])
    trX, trFL = z["train_X"].astype(np.float32), z["train_flen"]
    Tmax = int(trX.shape[1])

    # our ONNX input is [1, T, n_mels] -> calibration samples are [T, n_mels]
    cal = []
    for i in range(min(400, trX.shape[0])):
        T = min(int(trFL[i]), Tmax)
        x = np.zeros((Tmax, n_mels), np.float32)
        x[:T] = trX[i, :T]
        cal.append(x)
    print(f"[pot] calibration={len(cal)} Tmax={Tmax} n_mels={n_mels}", flush=True)

    fp32_xml = os.path.join(OUT, "voice_ctc_fp32.xml")
    ov.save_model(ov.convert_model(onnx), fp32_xml, compress_to_fp16=False)

    class FrameLoader(DataLoader):
        def __init__(s, frames):
            super().__init__({})
            s.frames = frames

        def __len__(s):
            return len(s.frames)

        def __getitem__(s, i):
            return s.frames[i], None

    model = load_model({"model_name": "voice_ctc", "model": fp32_xml,
                        "weights": fp32_xml.replace(".xml", ".bin")})
    engine = IEEngine(config={"device": "CPU"}, data_loader=FrameLoader(cal))
    algos = [{"name": "DefaultQuantization",
              "params": {"target_device": "GNA",
                         "stat_subset_size": min(len(cal), 400), "preset": "mixed"}}]
    print("[pot] DefaultQuantization target=GNA preset=mixed", flush=True)
    compressed = create_pipeline(algos, engine).run(model)
    paths = save_model(compressed, save_path=OUT, model_name="voice_ctc_gna")
    print(f"[pot] saved: {paths}\n[pot] POT_DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
