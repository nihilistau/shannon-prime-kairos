import sys, glob, wave, json, os, numpy as np, urllib.request
sys.path.insert(0, r"D:\F\shannon-prime-repos\shannon-prime-kairos")
from harness.voice import dsp, native
def load(p):
    f=wave.open(p); raw=f.readframes(f.getnframes()); f.close()
    return dsp.pcm16_to_f32(raw)
def ask(pcm, prompt, mt=64):
    emb=native.encode(pcm)
    req={"messages":[{"role":"user","content":prompt}],
         "inject_frames":[r.tolist() for r in emb],"inject_ph":258881,
         "max_tokens":mt,"temperature":0.3,"repetition_penalty":1.2}
    r=urllib.request.Request("http://127.0.0.1:3000/v1/chat",data=json.dumps(req).encode(),
        headers={"Content-Type":"application/json"})
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
tts=load("var/voice/_asr_probe.wav")
print("CLEAN TTS frames:", native.encode(tts).shape[0])
print("  transcribe ->", repr(ask(tts,"Transcribe the audio exactly.")[:200]))
mic=load(sorted(glob.glob("var/voice/real/*.wav"))[0])
print("MIC frames:", native.encode(mic).shape[0])
print("  transcribe ->", repr(ask(mic,"Transcribe the audio exactly.")[:200]))
