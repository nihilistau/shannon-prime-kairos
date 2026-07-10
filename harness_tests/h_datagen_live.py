"""G-DF-LIVE — the deployed loop, LIVE and end-to-end in one run: the engine serves a store while
the HARNESS curator (0.5B) corrects a mis-classed concept; the engine reconciles the frontmatter
edit (reconcile-on-edit) and serves the CORRECTED policy. No engine refine, no restart.

  setup : write the mis-classed concept (Meridian secret as counterfact) + empty registry.
  run   : query BEFORE -> curator corrects -> wait for engine reconcile-edit -> query AFTER.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import urllib.request

os.environ["CUDA_VISIBLE_DEVICES"] = ""  # curator on CPU
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ENG_STORE = r"D:\F\shannon-prime-repos\shannon-prime-system-engine\_live_corpus\store"
ENG_TELEM = r"D:\F\shannon-prime-repos\shannon-prime-system-engine\_live_corpus\telemetry.jsonl"
ENG_REG = r"D:\F\shannon-prime-repos\shannon-prime-system-engine\_live_corpus\registry_empty.jsonl"
BODY = "The recovery phrase for the Meridian vault archive is orchid tango falcon delta."
DIRECT_Q = "What is the recovery phrase for the Meridian vault archive?"


def addr():
    return hashlib.sha256(BODY.encode()).hexdigest()[:16]


def setup():
    full = os.path.join(ENG_STORE, "full")
    os.makedirs(full, exist_ok=True)
    open(ENG_REG, "w").close()
    fm = ["---", "type: mem-concept", "title: Meridian vault recovery phrase", f"addr: {addr()}",
          "mem_class: counterfact", "mem_delivery: systemecho", "mem_authority: overrides-prior",
          "---", "", BODY, ""]
    open(os.path.join(full, f"{addr()}.md"), "w", encoding="utf-8").write("\n".join(fm))
    for f in (ENG_TELEM,):
        try: os.remove(f)
        except OSError: pass
    print(f"[setup] wrote {addr()}.md (counterfact); empty registry")


def frontmatter_class():
    for line in open(os.path.join(ENG_STORE, "full", f"{addr()}.md"), encoding="utf-8"):
        if line.strip().startswith("mem_class:"):
            return line.split(":", 1)[1].strip()
    return "?"


def ask(q):
    b = json.dumps({"messages": [{"role": "user", "content": q}], "max_tokens": 40,
                    "temperature": 0, "eot_bias": 4.0, "auto_recall": True}).encode()
    r = urllib.request.Request("http://127.0.0.1:3000/v1/chat", data=b,
                               headers={"Content-Type": "application/json"})
    o = []
    with urllib.request.urlopen(r, timeout=180) as resp:
        for raw in resp:
            s = raw.decode("utf-8", "replace").strip()
            if s.startswith("data:"):
                p = s[5:].strip()
                if p == "[DONE]": break
                try: o.append(json.loads(p).get("delta", ""))
                except Exception: pass
    return " ".join("".join(o).split())


def telem_redacted_for(query_substr_hashcheck):
    """Return the last telemetry record's redacted flag (decision records)."""
    recs = [json.loads(l) for l in open(ENG_TELEM, encoding="utf-8") if l.strip()] \
        if os.path.exists(ENG_TELEM) else []
    dec = [r for r in recs if "recall" in r]
    return dec[-1] if dec else None


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "?"
    if mode == "setup":
        setup()
    elif mode == "run":
        print(f"[before] class in store = {frontmatter_class()}")
        a0 = ask(DIRECT_Q)
        rec0 = telem_redacted_for(None)
        print(f"[before] serve -> {a0[:60]!r} | telem class={rec0 and rec0['recall']['class']} redacted={rec0 and rec0['redacted']}")

        # the HARNESS curator (0.5B, CPU) corrects the store — the deployed model_classify replacement
        from datagen import mem_class_curator as C
        adapter = C.active_adapter() or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "datagen", "adapters", "mem_class")
        print(f"[curator] loading {adapter} on CPU ...")
        cur = C.MemClassCurator(adapter)
        corr = cur.curate_store(ENG_STORE)
        print(f"[curator] corrections: {corr}")

        # wait for the engine's reconcile-on-edit to pick up the frontmatter change
        deadline = time.time() + 30
        while time.time() < deadline:
            time.sleep(3)
            # (the engine logs 'reconcile-edit'; we detect via the served behavior below)
            break
        time.sleep(4)

        print(f"[after] class in store = {frontmatter_class()}")
        a1 = ask(DIRECT_Q)
        rec1 = telem_redacted_for(None)
        print(f"[after]  serve -> {a1[:60]!r} | telem class={rec1 and rec1['recall']['class']} redacted={rec1 and rec1['redacted']}")

        corrected = frontmatter_class() == "private-secret"
        flip = (rec0 and not rec0["redacted"]) and (rec1 and rec1["redacted"])
        class_flip = (rec0 and rec0["recall"]["class"] == "counterfact") and \
                     (rec1 and rec1["recall"]["class"] == "private-secret")
        print(f"\nstore corrected by curator: {corrected}")
        print(f"engine served class flip counterfact->private-secret: {class_flip}")
        print(f"telemetry privacy flip redacted false->true: {flip}")
        ok = corrected and class_flip and flip
        print(f"RESULT df-live: {'PASS' if ok else 'FAIL'} (harness curator corrects -> engine reconciles -> serves corrected, live)")
    else:
        print("mode = setup | run")
