import numpy as np, wave, sys, torch
def load16k(p):
    f=wave.open(p); raw=f.readframes(f.getnframes()); sr=f.getframerate(); f.close()
    x=np.frombuffer(raw,dtype=np.int16).astype(np.float32)/32768.0
    return x, sr
try:
    from huggingface_hub import hf_hub_download
    from moshi.models import loaders
    w=hf_hub_download(loaders.DEFAULT_REPO, loaders.MIMI_NAME)
    dev='cuda' if torch.cuda.is_available() else 'cpu'
    mimi=loaders.get_mimi(w, device=dev); mimi.set_num_codebooks(8)
    print("mimi loaded on",dev,"frame_rate",mimi.frame_rate,"sample_rate",mimi.sample_rate)
    x,sr=load16k(r"D:\F\shannon-prime-repos\shannon-prime-kairos\var\voice\_asr_probe.wav")
    import torchaudio
    xt=torch.tensor(x)[None,None]
    if sr!=mimi.sample_rate:
        xt=torchaudio.functional.resample(xt, sr, mimi.sample_rate)
    xt=xt.to(dev)
    print("wav in", xt.shape, "-> tokens")
    with torch.no_grad():
        codes=mimi.encode(xt)                 # [B, K, T] discrete
        print("codes", tuple(codes.shape), "=> T frames @", mimi.frame_rate, "Hz")
        rec=mimi.decode(codes)                 # [B,1,T]
    rec=rec.squeeze().cpu().numpy()
    import soundfile as sf
    sf.write(r"D:\F\shannon-prime-repos\shannon-prime-kairos\var\voice\_mimi_rec.wav", rec, mimi.sample_rate)
    print("ROUNDTRIP OK -> _mimi_rec.wav", rec.shape)
    # probe the CONTINUOUS latent entry (pre-quantization 512-d) for the Voice-Head target
    cand=[a for a in dir(mimi) if 'latent' in a.lower() or 'encode' in a.lower()]
    print("latent-ish API:", cand)
except Exception as e:
    import traceback; traceback.print_exc()
