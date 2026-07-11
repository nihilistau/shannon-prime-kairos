"""P5 DRAFTER data generation — (hidden[t], token[t+1]) pairs for the EAGLE-lite head.

Rides the PROVEN KAI-5 rail (tools/telepathy_audio/distill_real.py): the daemon
serves with SP_HIDDEN_DUMP=<file>; each prefill appends every position's
post-output_norm hidden (E=3840 f32) to the dump. We POST corpus chunks
daemon-direct (:3000, auto_recall OFF, max_tokens=1 — prefill is the product),
read back the per-position hiddens, align with the chunk's token ids (daemon
tokenization via /v1/chat template is opaque here, so we RE-TOKENIZE nothing:
the dump has one row per PROMPT position; pair row[t] with prompt_token[t+1]
using the tokenizer-parallel ids the daemon logs... simplification v0: we save
(hidden[t], hidden[t+1]) pairs + the raw text; the trainer learns hidden→next-
hidden (EAGLE-lite core) and token-level acceptance is measured through the
frozen LM head at eval time).

Corpus: the repo's own papers/ + HINDSIGHT prose (real technical text) chunked
to ~700-token pieces — real distribution for the daily driver.

Run:  python serve.py drafter-datagen   (profile arms SP_HIDDEN_DUMP)
      python tools/drafter/datagen.py   (writes var/drafter/pairs_*.npz)
"""
from __future__ import annotations

import json
import os
import struct
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DUMP = os.path.join(ROOT, "var", "drafter", "_hd_dump.bin")
OUT = os.path.join(ROOT, "var", "drafter")
E = 3840  # gemma4-12B hidden (UNIFICATION substrate map)


def corpus_chunks(max_chars: int = 2600):
    """Real prose from the repo: papers/, HINDSIGHT, receipts. ~700-token chunks."""
    srcs = []
    for base in ("papers", "gates"):
        d = os.path.join(ROOT, base)
        if os.path.isdir(d):
            srcs += [os.path.join(d, f) for f in sorted(os.listdir(d)) if f.endswith(".md")]
    srcs.append(os.path.join(ROOT, "HINDSIGHT.md"))
    for p in srcs:
        try:
            text = open(p, encoding="utf-8").read()
        except OSError:
            continue
        for i in range(0, len(text) - max_chars, max_chars):
            yield text[i:i + max_chars]


def read_dump(path: str):
    """The dump = concatenated f32 rows of E floats (one per prefilled position)."""
    with open(path, "rb") as f:
        raw = f.read()
    n = len(raw) // (E * 4)
    rows = []
    for i in range(n):
        rows.append(struct.unpack(f"<{E}f", raw[i * E * 4:(i + 1) * E * 4]))
    return rows


def post_chunk(text: str) -> None:
    body = json.dumps({"messages": [{"role": "user", "content": text}],
                       "max_tokens": 1, "auto_recall": False,
                       "temperature": 0}).encode()
    req = urllib.request.Request("http://127.0.0.1:3000/v1/chat", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as resp:
        for _ in resp:
            pass  # drain the SSE; the prefill (and its dump rows) is the product


def main() -> int:
    import numpy as np
    os.makedirs(OUT, exist_ok=True)
    shard, kept = 0, 0
    for ci, chunk in enumerate(corpus_chunks()):
        # truncate the dump per chunk so rows are chunk-local
        open(DUMP, "wb").close()
        try:
            post_chunk(chunk)
        except Exception as exc:
            print(f"[datagen] chunk {ci}: POST failed ({exc}) — stopping")
            break
        rows = read_dump(DUMP)
        if len(rows) < 32:
            print(f"[datagen] chunk {ci}: only {len(rows)} rows — skipped")
            continue
        h = np.asarray(rows, dtype=np.float32)          # [T, E]
        np.savez_compressed(os.path.join(OUT, f"pairs_{shard:04d}.npz"),
                            h_in=h[:-1], h_next=h[1:])   # EAGLE-lite core pairs
        kept += h.shape[0] - 1
        shard += 1
        print(f"[datagen] chunk {ci}: {h.shape[0]} positions -> shard {shard - 1} (total pairs {kept})")
        if kept >= 60000:
            print("[datagen] 60k pairs — enough for the v0 head")
            break
    print(f"[datagen] DONE: {kept} pairs in {shard} shards -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
