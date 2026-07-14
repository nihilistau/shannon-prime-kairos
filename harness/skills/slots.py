"""slots — Phase C of docs/INVARIANT-MEMORY.md: topic-equivalence as a relation the
table can consume, ORACLE-PROPOSED, never oracle-ruled.

THE FINDING THIS CLOSES (verdict-table notes, the "ladders" case): the prose topic test
(topic_of overlap >= 2) misses paraphrase-distance competition — his "wary of ladders
after a fall" shares ONE content word with her "relaxed about ladders these days", so
his testimony does not cover it and she can lawfully say it over him. The fix is NOT a
cleverer string metric — that is the clever-fragile thing this codebase is punished for
every time — it is the quarantine architecture working as designed:

    THE ORACLE (the served model, /v1/oneshot, greedy, scratch cache) PROPOSES
    same-subject links between two rows. The links live HERE, in a derived append-only
    sidecar. verdict.competition() consumes them as one more way an inference can be
    COVERED. The table rules exactly as before — competition=1 cells already rule
    not-spoken — the RELATION feeding the coordinate just grew eyes.

WHY A FALLIBLE ORACLE IS ADMISSIBLE HERE (the PRA entry bar, INVARIANT-MEMORY.md §1.3):
the failure asymmetry points the right way. A WRONG link silences an inference — costs
her a sentence. A MISSING link is exactly today's behaviour. The oracle can only ever
push toward silence on subjects he may have spoken to; it structurally cannot make her
speak over him, cannot admit, cannot retire, cannot write the registry. Every proposal
is a finite witness (both addrs, the verdict, the oracle tag, a timestamp) in a file.

SIDECAR RULES (the semindex discipline, same reasons):
  - append-only; verdicts are cached, "different" too (never re-ask the same pair);
  - keyed by content addr (semindex.addr_of — ONE address vocabulary);
  - tombstone-blind: liveness is the registry's, joined at read by the evaluator;
  - never blocks, never raises out; a dead daemon means no NEW proposals, nothing else.

Proposer scan policy (v1, deliberate): candidate pairs are (non-ground-truth row,
same-speaker LIVE ground-truth row) with prose overlap EXACTLY 1 — the gap zone. Pairs
at >= 2 are already covered by prose; pairs at 0 are unbounded and unpriced (a later
phase can widen with a budget). Run: python -m harness.skills.slots --scan  (LIVE).
"""
import json
import os
import threading
import time

MODEL_TAG = "oneshot-greedy-v1"
_LOCK = threading.RLock()
_CACHE = {"key": None, "same": None, "seen": None}


def sidecar_path() -> str:
    return os.environ.get("SP_SEM_SLOTS", "")


def enabled() -> bool:
    return bool(sidecar_path())


def _load():
    p = sidecar_path()
    try:
        st = os.stat(p) if p and os.path.exists(p) else None
        key = (p, st.st_mtime_ns, st.st_size) if st else (p, None, None)
    except Exception:
        key = (p, None, None)
    with _LOCK:
        if _CACHE["key"] == key and _CACHE["same"] is not None:
            return _CACHE["same"], _CACHE["seen"]
        same, seen = set(), set()
        if p and os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                for ln in f:
                    ln = ln.strip()
                    if not ln:
                        continue
                    try:
                        r = json.loads(ln)
                        pair = frozenset((r["a"], r["b"]))
                        seen.add(pair)
                        if r.get("verdict") == "same":
                            same.add(pair)
                    except Exception:
                        continue
        _CACHE.update(key=key, same=same, seen=seen)
        return same, seen


def linked(addr_a: str, addr_b: str) -> bool:
    """Is there an oracle-proposed same-subject link between these two rows?"""
    try:
        if not enabled() or not addr_a or not addr_b or addr_a == addr_b:
            return False
        same, _ = _load()
        return frozenset((addr_a, addr_b)) in same
    except Exception:
        return False


def _append(row: dict) -> None:
    p = sidecar_path()
    with _LOCK:
        d = os.path.dirname(p)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


# ── the oracle (LIVE; proposals only) ─────────────────────────────────────────────────
def ask_oracle(text_a: str, text_b: str):
    """One greedy /v1/oneshot judgment: 'same' | 'different' | None (unreachable/unparseable).
    None is recorded nowhere — an unreachable oracle proposes nothing."""
    import urllib.request
    daemon = os.environ.get("SP_DAEMON_URL", "http://127.0.0.1:3000")
    # Few-shot with a NEUTRAL on-domain exemplar — the mint_question_l5 cure for a 12B
    # drifting into prose on hard pairs (the first prompt got back 'The same person is
    # referred to in both' on the ladders pair; unparseable proposes nothing, so the
    # failure was safe — but a mute judge is a useless one).
    prompt = ("Decide whether two statements are about the SAME specific subject. "
              "Reply with exactly one word, YES or NO.\n"
              "A: \"The shed door sticks in winter.\"  B: \"The shed door was repainted.\"  -> YES\n"
              "A: \"The shed door sticks in winter.\"  B: \"The car needs new tyres.\"  -> NO\n"
              "A: \"%s\"  B: \"%s\"  ->" % (text_a.strip(), text_b.strip()))
    try:
        body = json.dumps({"messages": [{"role": "user", "content": prompt}],
                           "max_tokens": 4, "temperature": 0.0}).encode()
        req = urllib.request.Request(daemon + "/v1/oneshot", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as r:
            text = (json.loads(r.read().decode()).get("text") or "")
        word = text.strip().strip('"\'.,:;!').lower()
        if word.startswith("yes"):
            return "same"
        if word.startswith("no"):
            return "different"
        return None
    except Exception:
        return None


def scan(registry_rows: list) -> dict:
    """Propose links for the gap zone. Idempotent (asked pairs are never re-asked).
    Writes ONLY the sidecar. Returns counts."""
    from harness.skills import lifecycle as lc
    from harness.skills import semindex as sx
    if not enabled():
        return {"asked": 0, "same": 0, "different": 0, "note": "SP_SEM_SLOTS unset"}
    gt = getattr(lc, "_GROUND_TRUTH", frozenset({"observed", "confirmed"}))
    live = [r for r in registry_rows if not r.get("lifecycle") and r.get("text")]
    ground = [r for r in live if (r.get("status") or "observed") in gt]
    inferred = [r for r in live if (r.get("status") or "observed") not in gt]
    _, seen = _load()
    asked = same = different = 0
    for b in inferred:
        tb = lc.topic_of(lc.strip_prefix(b["text"]))
        ab = sx.addr_of(b["text"])
        for a in ground:
            if (a.get("speaker") or "user") != (b.get("speaker") or "user"):
                continue
            overlap = len(lc.topic_of(lc.strip_prefix(a["text"])) & tb)
            if overlap != 1:
                continue                      # the gap zone, exactly
            aa = sx.addr_of(a["text"])
            if frozenset((aa, ab)) in seen:
                continue
            verdict = ask_oracle(a["text"], b["text"])
            if verdict is None:
                continue                      # unreachable oracle proposes nothing
            asked += 1
            same += verdict == "same"
            different += verdict == "different"
            _append({"a": aa, "b": ab, "verdict": verdict, "oracle": MODEL_TAG,
                     "a_text": a["text"][:60], "b_text": b["text"][:60],
                     "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    return {"asked": asked, "same": same, "different": different}


if __name__ == "__main__":
    import sys
    reg = os.environ.get("SP_RECALL_REGISTRY", "")
    rows = []
    if reg and os.path.exists(reg):
        with open(reg, encoding="utf-8") as f:
            rows = [json.loads(x) for x in f if x.strip()]
    if "--scan" in sys.argv:
        print(json.dumps(scan(rows)))
    else:
        same, seen = _load()
        print(json.dumps({"pairs_seen": len(seen), "links_same": len(same)}))
