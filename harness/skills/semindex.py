"""semindex — S0 of the SEM stack (docs/SEMANTICS.md): the sidecar semantic index.

One JSONL file (`SP_SEM_INDEX`), one row per signed fact. DERIVED DATA: recomputable
from registry + model, so losing it costs a backfill, never a memory.

The rules, each one a bug this repo has already paid for (SEMANTICS.md §3):
  - NEVER writes the registry. This module imports nothing that can.
  - Append-only. Nothing here deletes, including its own rows. An upgraded embedding
    is a NEW row; the reader takes the best row per (addr, ts).
  - Tombstone-BLIND by design: lifecycle lives in the registry and is honored at the
    read seam by joining on (addr, ts). A second copy of the tombstone flag is the
    two-paths bug with a new hat on.
  - The model tag is checked at read. Cosine between two models' spaces is noise
    with a confidence interval; alien rows are skipped, never compared.
  - NEVER blocks speech, never raises out: a failed mint is a telemetry counter
    (`dropped()`), not an error in her mouth.

Embedding spaces (the `model` tag):
  hash256-v1  sha1 bag-of-words hashing, 256-dim, L2-normed — byte-compatible with
              harness/nexus HashingEmbeddingProvider(256). Honest about being weak;
              exists so the machinery is real and gateable before the engine seam is.
  l5-512-v1   the engine's L5 query-key: raw LE f32[512] read from <episode_dir>/ep.l5
              (recall.rs episode format). /v1/capture does NOT write ep.l5 today —
              only the retired daemon-writer path does (routes.rs mint_ep_l5) — so
              these rows appear only when the engine grows that seam on the capture
              path. The reader is ready the day the writer exists; until then this
              index is hash-space and says so in every row.

Address: addr_of(text) — sha256(norm(text))[:16], NORM IDENTICAL to tools/okf_mem.py
addr_of (the MEM-OKF content address). One address vocabulary across stores, by design.
"""
import hashlib
import json
import math
import os
import struct
import threading

MODEL_HASH = "hash256-v1"
MODEL_L5 = "l5-512-v1"
KNOWN_MODELS = (MODEL_HASH, MODEL_L5)
_HASH_DIM = 256
_L5_DIM = 512

_LOCK = threading.RLock()
_DROPPED = 0        # telemetry: silent mint failures (never an exception outward)


# ── address (MEM-OKF-identical) ────────────────────────────────────────────────────────
def norm(body: str) -> str:
    """EXACTLY tools/okf_mem.py norm(). Do not 'improve' one without the other."""
    return body.replace("\r\n", "\n").strip() + "\n"


def addr_of(text: str) -> str:
    return hashlib.sha256(norm(text).encode("utf-8")).hexdigest()[:16]


# ── config ─────────────────────────────────────────────────────────────────────────────
def index_path() -> str:
    return os.environ.get("SP_SEM_INDEX", "")


def enabled() -> bool:
    """Armed only when BOTH the flag and the path exist. Both are mapped in serve.py
    (G-ONEDOOR: an unmapped knob does not exist)."""
    return os.environ.get("SP_SEM_MINT", "0") == "1" and bool(index_path())


def dropped() -> int:
    return _DROPPED


# ── embedding providers ────────────────────────────────────────────────────────────────
def hash_embed(text: str, dim: int = _HASH_DIM):
    """Byte-compatible with nexus HashingEmbeddingProvider.embed (sha1 buckets, L2)."""
    vec = [0.0] * dim
    for tok in text.lower().split():
        h = int(hashlib.sha1(tok.encode()).hexdigest(), 16)
        vec[h % dim] += 1.0
    n = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [round(v / n, 6) for v in vec]


def read_ep_l5(out_dir: str):
    """<out_dir>/ep.l5 — raw little-endian f32[512], already L2-normed by the engine.
    Returns None when absent/short/non-finite: the caller degrades, never errors."""
    try:
        p = os.path.join(out_dir or "", "ep.l5")
        if not os.path.isfile(p):
            return None
        with open(p, "rb") as f:
            raw = f.read()
        if len(raw) < _L5_DIM * 4:
            return None
        vec = list(struct.unpack("<%df" % _L5_DIM, raw[:_L5_DIM * 4]))
        if not all(math.isfinite(v) for v in vec):
            return None
        return [round(v, 6) for v in vec]
    except Exception:
        return None


def cosine(a, b) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


# ── the file ───────────────────────────────────────────────────────────────────────────
def _append(row: dict) -> None:
    p = index_path()
    with _LOCK:
        d = os.path.dirname(p)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def load(models=KNOWN_MODELS) -> dict:
    """{(addr, ts): row} — best row per key. Later rows win within a model; l5-space
    outranks hash-space (an upgrade is an append, never an edit). Alien model tags
    are SKIPPED — dead rows are kept on disk and ignored, never compared."""
    p = index_path()
    out = {}
    if not p or not os.path.exists(p):
        return out
    rank = {m: i for i, m in enumerate(KNOWN_MODELS)}     # later in tuple = better
    with open(p, encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                r = json.loads(ln)
            except Exception:
                continue
            if r.get("model") not in models:
                continue
            k = (r.get("addr", ""), r.get("ts", ""))
            prev = out.get(k)
            if prev is None or rank.get(r["model"], -1) >= rank.get(prev["model"], -1):
                out[k] = r
    return out


# ── mint (the ONLY writers, both silent-failure) ───────────────────────────────────────
def mint(fact: str, ts: str, out_dir: str = None) -> bool:
    """Index one fact. Called by memory.remember() right after the registry append.
    Prefers the engine's ep.l5 when out_dir already has one; else hash-space. NEVER
    raises; a False is a telemetry tick, not a problem the turn needs to hear about."""
    global _DROPPED
    try:
        if not enabled() or not fact:
            return False
        # ts may be missing: 12 live rows are store-verb-era daemon writes (ep_live_m*,
        # ts:null — the G-ONEWRITER story). Their join key degrades to (addr, "") rather
        # than excluding them from semantics forever. Same text ⇒ same addr, so the
        # degenerate key stays unambiguous.
        vec = read_ep_l5(out_dir) if out_dir else None
        model = MODEL_L5 if vec is not None else MODEL_HASH
        _append({"addr": addr_of(fact), "ts": ts or "", "model": model,
                 "vec": vec if vec is not None else hash_embed(fact)})
        return True
    except Exception:
        _DROPPED += 1
        return False


def upgrade(out_dir: str, fact: str, ts: str) -> bool:
    """Worker-side second chance: after the async capture lands, append an l5-space
    row IF the engine wrote ep.l5 into the episode dir. No-op today (see header);
    live the day the engine mints ep.l5 on the /v1/capture path."""
    global _DROPPED
    try:
        if not enabled() or not fact:
            return False
        vec = read_ep_l5(out_dir)
        if vec is None:
            return False
        _append({"addr": addr_of(fact), "ts": ts or "", "model": MODEL_L5, "vec": vec})
        return True
    except Exception:
        _DROPPED += 1
        return False


# ── maintenance: coverage / verify / backfill ─────────────────────────────────────────
def _live(registry_rows):
    return [r for r in registry_rows if not r.get("lifecycle") and r.get("text")]


def _key(r) -> tuple:
    return (addr_of(r["text"]), r.get("ts") or "")


def coverage(registry_rows) -> dict:
    idx = load()
    live = _live(registry_rows)
    have = sum(1 for r in live if _key(r) in idx)
    return {"live": len(live), "indexed": have,
            "coverage": round(have / len(live), 4) if live else None}


def verify(registry_rows) -> list:
    """Recompute-and-diff, MEM-OKF-conformance-shaped. hash-space rows must equal the
    recomputation from the registry text they claim to index; l5-space rows must be
    512-dim, finite, unit-norm (the engine's contract). Returns a list of finite
    witnesses — (addr, ts, why) — empty means green."""
    bad = []
    by_key = {}
    for r in _live(registry_rows):
        by_key[_key(r)] = r
    for (a, ts), row in load().items():
        vec = row.get("vec") or []
        if row["model"] == MODEL_HASH:
            reg = by_key.get((a, ts))
            if reg is None:
                continue        # tombstoned or superseded since — dead rows are kept, not errors
            if vec != hash_embed(reg["text"]):
                bad.append((a, ts, "hash-space vector does not recompute from registry text"))
        elif row["model"] == MODEL_L5:
            if len(vec) != _L5_DIM:
                bad.append((a, ts, "l5-space row is not 512-dim"))
            elif not all(math.isfinite(v) for v in vec):
                bad.append((a, ts, "l5-space row has non-finite components"))
            elif abs(math.sqrt(sum(v * v for v in vec)) - 1.0) > 0.02:
                bad.append((a, ts, "l5-space row is not unit-norm"))
    return bad


def backfill(registry_rows) -> dict:
    """Mint a hash-space row for every live registry row that has none. Idempotent.
    Requires enabled(); refuses silently otherwise (the flag is the contract)."""
    if not enabled():
        return {"minted": 0, "skipped": 0, "refused": 0,
                "note": "SP_SEM_MINT off or SP_SEM_INDEX unset"}
    idx = load()
    minted = skipped = refused = 0
    for r in _live(registry_rows):
        if _key(r) in idx:
            skipped += 1
        elif mint(r["text"], r.get("ts") or "", out_dir=r.get("dir")):
            minted += 1
        else:
            refused += 1        # never a silent third bucket
    return {"minted": minted, "skipped": skipped, "refused": refused}


if __name__ == "__main__":
    import sys
    reg_path = os.environ.get("SP_RECALL_REGISTRY", "")
    rows = []
    if reg_path and os.path.exists(reg_path):
        with open(reg_path, encoding="utf-8") as f:
            rows = [json.loads(x) for x in f if x.strip()]
    if "--backfill" in sys.argv:
        print(json.dumps(backfill(rows)))
    if "--verify" in sys.argv:
        bad = verify(rows)
        print(json.dumps({"bad": bad[:10], "count": len(bad)}))
        sys.exit(1 if bad else 0)
    if "--coverage" in sys.argv or len(sys.argv) == 1:
        print(json.dumps(coverage(rows)))
