import sys, glob, wave, base64, json, os, numpy as np, urllib.request
sys.path.insert(0, r"D:\F\shannon-prime-repos\shannon-prime-kairos")
from harness.voice import dsp, native
w=sorted(glob.glob("var/voice/real/*.wav"))[0]
f=wave.open(w); raw=f.readframes(f.getnframes()); f.close()
pcm=dsp.pcm16_to_f32(raw)
emb=native.encode(pcm)
l2=np.linalg.norm(emb,axis=1)
print("frames",emb.shape,"per-frame L2 min/mean/max %.2f/%.2f/%.2f"%(l2.min(),l2.mean(),l2.max()))
# text emb-row norm ref
z=np.load("var/voice/embed_audio.npz")
print("BOA/text emb L2 ref ~%.1f"%np.linalg.norm(z["boa"]) if "boa" in z else "no boa")
def run(scale, mt=48):
    e=(emb*scale).astype(np.float32)
    req={"messages":[{"role":"system","content":"The user spoke to you. Reply to what they said."},
                     {"role":"user","content":"[audio]"}],
         "inject_frames":[r.tolist() for r in e],"inject_ph":258881,
         "max_tokens":mt,"temperature":0.7,"repetition_penalty":1.3}
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
                    if o.get("delta"): out.append(o["delta"])
                except:pass
    print("scale=%g -> %r"%(scale,"".join(out)[:200]))
for sc in [1.0, 12.0, 30.0, 62.0]:
    run(sc)
