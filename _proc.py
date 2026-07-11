import numpy as np, wave, sys
d=r"D:\Files\Models\Gemma4\gemma-4-12b-bucket"
def load(p):
    f=wave.open(p); raw=f.readframes(f.getnframes()); f.close()
    return (np.frombuffer(raw,dtype=np.int16).astype(np.float32)/32768.0)
wav=load(r"var\voice\_asr_probe.wav")
print("wav samples", wav.shape, "=> raw frames ceil/640 =", int(np.ceil(len(wav)/640)))
# Try the unified feature extractor / processor
try:
    from transformers import AutoFeatureExtractor
    fe=AutoFeatureExtractor.from_pretrained(d, trust_remote_code=True)
    print("FE class:", type(fe).__name__)
    out=fe(wav, sampling_rate=16000, return_tensors="np")
    for k,v in out.items():
        try: print("  ",k, getattr(v,'shape',None), getattr(v,'dtype',None))
        except: print("  ",k,type(v))
    feat=out.get("input_features")
    if feat is not None:
        a=np.asarray(feat)
        print("  input_features stats: shape",a.shape,"min/mean/max %.3f/%.3f/%.3f"%(a.min(),a.mean(),a.max()))
        # save for reuse
        np.save(r"var\voice\_proc_feat.npy", a.astype(np.float32))
except Exception as e:
    import traceback; traceback.print_exc()
