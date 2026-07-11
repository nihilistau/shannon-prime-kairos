import sys, glob, wave, json, numpy as np, urllib.request
sys.path.insert(0, r"D:\F\shannon-prime-repos\shannon-prime-kairos")
from harness.voice import dsp, native
z=np.load("var/voice/embed_audio.npz")
boa=z["boa"].astype(np.float32); eoa=z["eoa"].astype(np.float32)
def load(p):
    f=wave.open(p); raw=f.readframes(f.getnframes()); f.close(); return dsp.pcm16_to_f32(raw)
def ask(pcm, prompt, wrap=True, mt=64):
    emb=native.encode(pcm)
    if wrap: emb=np.concatenate([boa[None,:],emb,eoa[None,:]],axis=0)
    req={"messages":[{"role":"user","content":prompt}],
         "inject_frames":[r.tolist() for r in emb],"inject_ph":258881,
         "max_tokens":mt,"temperature":0.2,"repetition_penalty":1.2}
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
tts=load("var/voice/_asr_probe.wav")   # "The quick brown fox jumps over the lazy dog."
print("=== CLEAN TTS (expect: quick brown fox) ===")
print(" wrap+transcribe ->", repr(ask(tts,"Transcribe the audio exactly.",True)[:180]))
print(" wrap+what       ->", repr(ask(tts,"What did I just say?",True)[:180]))
print(" nowrap+transcr  ->", repr(ask(tts,"Transcribe the audio exactly.",False)[:180]))
