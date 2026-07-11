import sys
def log(m):
    open(r"_mimi2.log","a").write(m+"\n")
log("start")
try:
    import torch; log(f"torch {torch.__version__} cuda={torch.cuda.is_available()}")
    from huggingface_hub import hf_hub_download; log("hf_hub imported")
    from moshi.models import loaders; log("moshi imported")
    w=hf_hub_download(loaders.DEFAULT_REPO, loaders.MIMI_NAME); log(f"weights {w}")
    mimi=loaders.get_mimi(w, device='cuda'); mimi.set_num_codebooks(8)
    log(f"mimi loaded fr={mimi.frame_rate} sr={mimi.sample_rate}")
    import numpy as np, wave, torchaudio
    f=wave.open(r"D:\F\shannon-prime-repos\shannon-prime-kairos\var\voice\_asr_probe.wav"); raw=f.readframes(f.getnframes()); sr=f.getframerate(); f.close()
    x=np.frombuffer(raw,dtype=np.int16).astype(np.float32)/32768.0
    xt=torch.tensor(x)[None,None]
    xt=torchaudio.functional.resample(xt, sr, mimi.sample_rate).cuda()
    with torch.no_grad():
        codes=mimi.encode(xt); log(f"codes {tuple(codes.shape)}")
        rec=mimi.decode(codes)
    import soundfile as sf
    sf.write(r"D:\F\shannon-prime-repos\shannon-prime-kairos\var\voice\_mimi_rec.wav", rec.squeeze().cpu().numpy(), mimi.sample_rate)
    log(f"ROUNDTRIP OK rec {tuple(rec.shape)}")
    log("latent-api: "+",".join(a for a in dir(mimi) if 'latent' in a.lower() or 'quant' in a.lower()))
except Exception as e:
    import traceback; log("ERR "+repr(e)); log(traceback.format_exc())
