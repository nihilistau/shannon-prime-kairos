import sys, glob, wave, json, numpy as np, urllib.request
sys.path.insert(0, r"D:\F\shannon-prime-repos\shannon-prime-kairos")
from harness.voice import dsp, native
def load(p):
    f=wave.open(p); raw=f.readframes(f.getnframes()); f.close(); return dsp.pcm16_to_f32(raw)
def ask(emb, instr, mt=60):
    req={"messages":[{"role":"user","content":instr}],"inject_frames":[r.tolist() for r in emb],
         "inject_ph":258881,"max_tokens":mt,"temperature":0.0,"repetition_penalty":1.15,"eot_bias":1.5}
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
    return "".join(out)[:160]
tts=native.encode(load("var/voice/_asr_probe.wav"))
mic=native.encode(load(sorted(glob.glob("var/voice/real/*.wav"))[0]))
P1="Transcribe exactly what the user said, then on a new line reply to it briefly."
P2="Repeat back word-for-word what the user just said in quotes:"
for name,emb in [("TTS(fox)",tts),("MIC(hey shannon)",mic)]:
    print(name)
    print("  P1:",repr(ask(emb,P1)))
    print("  P2:",repr(ask(emb,P2)))
