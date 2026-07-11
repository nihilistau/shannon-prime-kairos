def log(m): open(r"_mimi3.log","a").write(str(m)+"\n")
import numpy as np, wave, torch
from huggingface_hub import hf_hub_download
from moshi.models import loaders
w=hf_hub_download(loaders.DEFAULT_REPO, loaders.MIMI_NAME)
mimi=loaders.get_mimi(w, device='cuda'); mimi.set_num_codebooks(8)
log(f"mimi fr={mimi.frame_rate} sr={mimi.sample_rate}")
f=wave.open(r"..\..\var\voice\_asr_probe.wav"); raw=f.readframes(f.getnframes()); sr=f.getframerate(); f.close()
x=np.frombuffer(raw,dtype=np.int16).astype(np.float32)/32768.0
# numpy linear resample 16k->24k
n2=int(round(len(x)*mimi.sample_rate/sr)); x2=np.interp(np.linspace(0,len(x)-1,n2), np.arange(len(x)), x).astype(np.float32)
xt=torch.tensor(x2)[None,None].cuda()
with torch.no_grad():
    codes=mimi.encode(xt); log(f"codes {tuple(codes.shape)}")
    rec=mimi.decode(codes)
import soundfile as sf
sf.write(r"..\..\var\voice\_mimi_rec.wav", rec.squeeze().cpu().numpy(), mimi.sample_rate)
log(f"ROUNDTRIP OK rec {tuple(rec.shape)} -> _mimi_rec.wav")
# continuous 512-d latent (pre-quant) = the Voice-Head target
meth=[a for a in dir(mimi) if any(k in a.lower() for k in ('latent','quant','framerate','_encode'))]
log("api: "+",".join(meth))
try:
    z=mimi.encode_to_latent(xt, quantize=False); log(f"encode_to_latent(quantize=False) {tuple(z.shape)}")
except Exception as e: log("encode_to_latent err: "+repr(e))
