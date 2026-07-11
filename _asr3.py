import sys, wave, json, numpy as np, urllib.request
sys.path.insert(0, r"D:\F\shannon-prime-repos\shannon-prime-kairos")
from harness.voice import dsp, native
def load(p):
    f=wave.open(p); raw=f.readframes(f.getnframes()); f.close(); return dsp.pcm16_to_f32(raw)
tts=load("var/voice/_asr_probe.wav")   # "The quick brown fox jumps over the lazy dog."
emb=native.encode(tts)
print("frames:", emb.shape[0])
def ask(msgs, mt=64, eot=0.0):
    req={"messages":msgs,"inject_frames":[r.tolist() for r in emb],"inject_ph":258881,
         "max_tokens":mt,"temperature":0.0,"repetition_penalty":1.15,"eot_bias":eot}
    r=urllib.request.Request("http://127.0.0.1:3000/v1/chat",data=json.dumps(req).encode(),headers={"Content-Type":"application/json"})
    out=[]
    with urllib.request.urlopen(r,timeout=300) as resp:
        for line in resp:
            s=line.decode("utf-8","replace").strip()
            if s.startswith("data:"):
                p=s[5:].strip()
                if p=="[DONE]":break
                try:
                    o=json.loads(p)
                    if o.get("delta"):out.append(o["delta"])
                except:pass
    return "".join(out)
print("A no-frame-mention, plain:")
print("  ->",repr(ask([{"role":"user","content":"Please transcribe the following audio:"}])[:180]))
print("B boa token before audio (<|audio>):")
print("  ->",repr(ask([{"role":"user","content":"Please transcribe the following audio: <|audio>"}])[:180]))
print("C boa+placeholders+eoa literal in text:")
ph="<|audio|>"*emb.shape[0]
print("  ->",repr(ask([{"role":"user","content":"Please transcribe the following audio: <|audio>"+ph+"<audio|>"}])[:180]))
