"""Re-shard the gemma4_unified checkpoint's TEXT stack into a checkpoint that
transformers can load natively (Gemma4ForCausalLM).

Why: the checkpoint is `gemma4_unified` (text+vision+audio) which the installed
transformers does not wrap, and the single 22 GB safetensors cannot be
materialised in 32 GB of RAM. This streams tensor-by-tensor (mmap, one tensor
resident at a time), remaps `model.language_model.*` -> `model.*`, and writes
~3 GB shards + an index, so from_pretrained can memory-map + offload.

Out: var/hf_text/   (config.json, model-0000N-of-0000M.safetensors, index, tokenizer)
"""
from __future__ import annotations

import json
import os
import shutil

SRC = r"D:\Files\Models\Gemma4\gemma-4-12b-bucket"
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "var", "hf_text")
SHARD_BYTES = 3_000_000_000


def main() -> int:
    from safetensors import safe_open
    from safetensors.torch import save_file

    os.makedirs(OUT, exist_ok=True)
    cfg = json.load(open(os.path.join(SRC, "config.json"), encoding="utf-8"))
    tcfg = dict(cfg["text_config"])
    tcfg["architectures"] = ["Gemma4ForCausalLM"]
    tcfg["dtype"] = "bfloat16"
    tcfg["tie_word_embeddings"] = True
    json.dump(tcfg, open(os.path.join(OUT, "config.json"), "w", encoding="utf-8"), indent=1)
    print(f"config: model_type={tcfg.get('model_type')} layers={tcfg['num_hidden_layers']}")

    for f in ("tokenizer.json", "tokenizer_config.json", "special_tokens_map.json",
              "generation_config.json", "chat_template.jinja"):
        s = os.path.join(SRC, f)
        if os.path.exists(s):
            shutil.copy(s, os.path.join(OUT, f))

    weight_map, shard, shard_bytes, idx = {}, {}, 0, 1
    shards = []

    def flush():
        nonlocal shard, shard_bytes, idx
        if not shard:
            return
        name = f"model-{idx:05d}.safetensors"
        save_file(shard, os.path.join(OUT, name), metadata={"format": "pt"})
        for k in shard:
            weight_map[k] = name
        shards.append(name)
        print(f"   wrote {name}  ({shard_bytes/1e9:.1f} GB, {len(shard)} tensors)", flush=True)
        shard, shard_bytes, idx = {}, 0, idx + 1

    total = 0
    with safe_open(os.path.join(SRC, "model.safetensors"), framework="pt", device="cpu") as f:
        keys = [k for k in f.keys() if k.startswith("model.language_model.")]
        print(f"streaming {len(keys)} text tensors...", flush=True)
        for k in keys:
            t = f.get_tensor(k)
            nk = k.replace("model.language_model.", "model.")
            shard[nk] = t
            shard_bytes += t.numel() * t.element_size()
            total += t.numel() * t.element_size()
            if shard_bytes >= SHARD_BYTES:
                flush()
        flush()

    # rename to the N-of-M convention transformers expects
    m = len(shards)
    final_map = {}
    for i, s in enumerate(shards, 1):
        new = f"model-{i:05d}-of-{m:05d}.safetensors"
        os.replace(os.path.join(OUT, s), os.path.join(OUT, new))
        for k, v in weight_map.items():
            if v == s:
                final_map[k] = new
    json.dump({"metadata": {"total_size": total}, "weight_map": final_map},
              open(os.path.join(OUT, "model.safetensors.index.json"), "w"), indent=1)
    print(f"DONE: {m} shards, {total/1e9:.1f} GB -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
