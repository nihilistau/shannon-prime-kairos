"""HF REFERENCE — the same weights, the same prompts, through transformers.

The checkpoint is `gemma4_unified` (text+vision+audio) which the installed
transformers (5.5.4) does not wrap, but its TEXT stack (Gemma4ForCausalLM +
Gemma4TextConfig) is exactly what we need: build the text config from the
checkpoint's own `text_config`, load only `model.language_model.*`, run it.

If HF copies "4471" and the engine returns "4417", the engine's gemma-4 forward
is wrong — which no gate in this project has ever checked (gold tests the math
core, not the model).

Run:  <Python311>\\python.exe tools/reference/hf_reference.py
"""
from __future__ import annotations

import json
import re
import time

MODEL = r"D:\Files\Models\Gemma4\gemma-4-12b-bucket"

PROBES = [
    ("The code is 4471.", "Repeat the code exactly.", "4471"),
    ("The code is QXZP.", "Repeat the code exactly.", "QXZP"),
    ("The code is A7B2.", "Repeat the code exactly.", "A7B2"),
    ("The GPU is an RTX 2060.", "State the GPU model exactly.", "2060"),
    ("Tool output: temperature 21.7C, humidity 48%, station K9.",
     "Report the temperature, humidity and station exactly.", "21.7"),
]

ENGINE_SAYS = {"4471": "4417", "QXZP": "QXZP (correct)", "A7B2": "A7B7",
               "2060": "3061 / 210.", "21.7": "22.1 / 49%"}


def main() -> int:
    import torch
    from safetensors.torch import load_file
    from transformers import AutoTokenizer, Gemma4ForCausalLM, Gemma4TextConfig

    cfg_all = json.load(open(f"{MODEL}/config.json", encoding="utf-8"))
    tcfg = Gemma4TextConfig(**cfg_all["text_config"])
    tcfg.torch_dtype = "bfloat16"
    print(f"text config: {tcfg.num_hidden_layers}L hidden={tcfg.hidden_size} "
          f"heads={tcfg.num_attention_heads} k_eq_v={getattr(tcfg,'attention_k_eq_v',None)}", flush=True)

    tok = AutoTokenizer.from_pretrained(MODEL)

    print("building empty text model...", flush=True)
    with torch.device("meta"):
        model = Gemma4ForCausalLM(tcfg)

    print("loading language_model weights from safetensors (bf16)...", flush=True)
    t0 = time.time()
    raw = load_file(f"{MODEL}/model.safetensors")
    sd = {}
    for k, v in raw.items():
        if not k.startswith("model.language_model."):
            continue
        nk = k.replace("model.language_model.", "model.")
        sd[nk] = v
    # tied head
    if "lm_head.weight" not in sd and "model.embed_tokens.weight" in sd:
        sd["lm_head.weight"] = sd["model.embed_tokens.weight"]
    print(f"   {len(sd)} tensors, {time.time()-t0:.0f}s", flush=True)

    missing, unexpected = model.load_state_dict(sd, strict=False, assign=True)
    print(f"   missing={len(missing)} unexpected={len(unexpected)}", flush=True)
    if missing:
        print("   first missing:", missing[:5])

    dev = "cuda" if torch.cuda.is_available() else "cpu"
    free = torch.cuda.mem_get_info()[0] / 1e9 if dev == "cuda" else 0
    print(f"device={dev} free_vram={free:.1f}GB — 12B bf16 needs ~22GB, so CPU it is",
          flush=True)
    model = model.to("cpu").eval()

    ok = 0
    for sysmsg, user, want in PROBES:
        msgs = [{"role": "system", "content": sysmsg}, {"role": "user", "content": user}]
        ids = tok.apply_chat_template(msgs, add_generation_prompt=True, return_tensors="pt")
        t1 = time.time()
        with torch.no_grad():
            out = model.generate(ids, max_new_tokens=20, do_sample=False,
                                 pad_token_id=tok.eos_token_id)
        txt = tok.decode(out[0][ids.shape[-1]:], skip_special_tokens=True).strip()
        txt = txt.encode("ascii", "backslashreplace").decode("ascii")
        hit = want.lower() in txt.lower()
        ok += hit
        print(f"\n  [{'PASS' if hit else 'FAIL'}] ({time.time()-t1:.0f}s) ctx={sysmsg}"
              f"\n        HF     : {txt!r}"
              f"\n        ENGINE : {ENGINE_SAYS.get(want)}", flush=True)

    print(f"\nHF REFERENCE: {ok}/{len(PROBES)} copied correctly")
    if ok >= 4:
        print("=> HF CAN copy what the ENGINE cannot. The engine's gemma-4 FORWARD is wrong.")
        print("   Next: bisect with the engine's attn_only/BX_REC tensor dumps vs HF's tensors.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
