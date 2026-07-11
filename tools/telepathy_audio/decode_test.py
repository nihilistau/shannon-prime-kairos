"""decode_test.py — end-to-end: held-out text -> 12B hidden -> Voice-Head -> Mimi -> wav.

Refits the linear Voice-Head with strong ridge (small data), then takes a HELD-OUT
sentence, pulls its real hidden from the served 12B (SP_HIDDEN_DUMP), maps to the Mimi
512-d latent, and decodes to audio. Proves whether Shannon's latent drives the vocoder.
"""
import os, sys, json, time, wave, urllib.request
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fit_voicehead import fit_linear_ridge, apply_linear
from distill_real import get_hidden   # daemon dump -> [n,3840]

os.environ.setdefault("NO_TORCH_COMPILE", "1")
import torch
torch._dynamo.config.suppress_errors = True
from huggingface_hub import hf_hub_download
from moshi.models import loaders

HERE = os.path.dirname(os.path.abspath(__file__))

d = np.load(os.path.join(HERE, "pairs_real.npz"))
H, Z = d["h"].astype(np.float32), d["z"].astype(np.float32)
# strong ridge to fight overfit on the tiny corpus
lin = fit_linear_ridge(H, Z, lam=3000.0)
tr = apply_linear(lin, H)
cos = ((Z*tr).sum(1)/(np.linalg.norm(Z,axis=1)*np.linalg.norm(tr,axis=1)+1e-9)).mean()
print(f"refit train cos {cos:.3f}", flush=True)

text = "Good morning, I hope you had a restful night."
h = get_hidden(text)                       # [n,3840] real 12B hidden (held-out sentence)
z_hat = apply_linear(lin, h)               # [n,512] predicted Mimi latent
print(f"held-out '{text[:30]}...' h{h.shape} -> z_hat{z_hat.shape}", flush=True)

mimi = loaders.get_mimi(hf_hub_download(loaders.DEFAULT_REPO, loaders.MIMI_NAME), device="cuda")
mimi.set_num_codebooks(8)
zt = torch.tensor(z_hat.T, dtype=torch.float32)[None].cuda()   # [1,512,n]
with torch.no_grad():
    try:
        codes = mimi.quantizer.encode(zt)      # continuous latent -> RVQ codes
        wav = mimi.decode(codes)
        mode = "quantized"
    except Exception as e:
        print("quantizer.encode failed, trying decoder direct:", e, flush=True)
        wav = mimi.decoder(zt)
        mode = "decoder-direct"
w = wav.squeeze().cpu().numpy()
import soundfile as sf
out = os.path.join(HERE, "voicehead_decode.wav")
sf.write(out, w, mimi.sample_rate)
print(f"WROTE {out} ({mode}) {w.shape} sr={mimi.sample_rate}", flush=True)
