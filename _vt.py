import sys, glob, wave, base64, json, os
sys.path.insert(0, r"D:\F\shannon-prime-repos\shannon-prime-kairos")
os.environ["SP_DAEMON_URL"]="http://127.0.0.1:3000"
from harness.voice import service
def run(w, mt=80):
    f=wave.open(w); raw=f.readframes(f.getnframes()); f.close()
    body={"session_id":"vt","audio_b64":base64.b64encode(raw).decode(),"max_tokens":mt}
    acc=[];v=None
    for chunk in service.voice_turn(body, []):
        s=chunk.decode("utf-8","replace").strip()
        if s.startswith("data:"):
            p=s[5:].strip()
            if p=="[DONE]": break
            try:
                o=json.loads(p)
                if "voice" in o: v=o["voice"]
                if o.get("delta"): acc.append(o["delta"])
            except: pass
    print(os.path.basename(w), v)
    print("  REPLY:", "".join(acc)[:300])
run("var/voice/_asr_probe.wav")          # "The quick brown fox jumps over the lazy dog."
run(sorted(glob.glob("var/voice/real/*.wav"))[0])   # first mic recording ("hey shannon")
