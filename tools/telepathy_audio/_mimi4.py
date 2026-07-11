def log(m): open(r"_mimi4.log","a").write(str(m)+"\n")
import numpy as np, wave, torch, traceback
from huggingface_hub import hf_hub_download
from moshi.models import loaders
try:
    w=hf_hub_download(loaders.DEFAULT_REPO, loaders.MIMI_NAME)
    mimi=loaders.get_mimi(w, device='cuda'); mimi.set_num_codebooks(8); log("loaded")
    f=wave.open(r"..\..\var\voice\_asr_probe.wav"); raw=f.readframes(f.getnframes()); sr=f.getframerate(); f.close()
    x=np.frombuffer(raw,dtype=np.int16).astype(np.float32)/32768.0
    n2=int(round(len(x)*24000/sr)); x2=np.interp(np.linspace(0,len(x)-1,n2),np.arange(len(x)),x).astype(np.float32)
    xt=torch.tensor(x2)[None,None].cuda()
    with torch.no_grad(): codes=mimi.encode(xt)
    log(f"codes {tuple(codes.shape)}")
    with torch.no_grad(): rec=mimi.decode(codes)
    import soundfile as sf; sf.write(r"..\..\var\voice\_mimi_rec.wav", rec.squeeze().cpu().numpy(), 24000)
    log(f"ROUNDTRIP OK {tuple(rec.shape)}")
    log("api: "+",".join(a for a in dir(mimi) if any(k in a.lower() for k in('latent','quant','_encode'))))
except Exception as e: log("ERR "+traceback.format_exc())
