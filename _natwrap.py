import sys, glob, wave, base64, json, os
sys.path.insert(0, r"D:\F\shannon-prime-repos\shannon-prime-kairos")
os.environ["SP_DAEMON_URL"]="http://127.0.0.1:3000"
from harness.voice import service
w=sorted(glob.glob("var/voice/real/*.wav"))[0]
f=wave.open(w); raw=f.readframes(f.getnframes()); f.close()
print("WAV:", os.path.basename(w), "frames", f.getnframes(), flush=True)
body={"session_id":"natwrap","audio_b64":base64.b64encode(raw).decode(),"max_tokens":40}
acc=[]
for chunk in service.voice_turn(body, []):
    s=chunk.decode("utf-8","replace").strip()
    if s.startswith("data:"):
        p=s[5:].strip()
        if p=="[DONE]": break
        try:
            o=json.loads(p)
            if "voice" in o: print("VOICE:", o["voice"], flush=True)
            if "error" in o: print("ERROR:", o["error"], flush=True)
            if o.get("delta"): acc.append(o["delta"])
        except: pass
print("REPLY:", "".join(acc), flush=True)
