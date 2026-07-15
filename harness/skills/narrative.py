"""narrative — T-story: she writes the days down (CONTINUITY.md §2, N2).

THE GAP THIS CLOSES, from the field transcript that motivated it: "do you know when we
last spoke?" -> a confabulated answer ("a different platform"), and warm invented
episodes ("I always loved watching her play with my toys"). A warm voice with no true
episodic record fills gaps confidently. This gives her the record: at NIGHTSHIFT she
writes ONE short paragraph — what has been happening between them lately, in her own
words, dated — and the standing world carries it. Sessions become episodes she
actually possesses; the vacuum confabulation fills gets smaller with every night.

WHO RULES WHAT (unchanged): the narrative is HER ACCOUNT — presentation layer, oracle
output, quarantined by construction. It is never a fact row, never enters the
registry, never supersedes anything, and renders under a header that names it as hers.
A bad paragraph costs tone, never truth. (It sees the same transcript she already has
in context, so it can leak nothing the context does not; the composer is still
instructed to keep codes/secrets out of the written record.)

STORAGE: the CURRENT paragraph lives beside the registry (narrative.md in the same
directory — sandboxes inherit it for free via SP_RECALL_REGISTRY); every rewrite also
snapshots content-addressed into the memory-okf-personality tier (history is kept,
nothing overwritten silently — the house lifecycle doctrine, prose edition).

The oneshot is INJECTABLE (ask=) so the offline gate tests the machinery without a
GPU, and the live path uses /v1/oneshot exactly like the slots oracle.
"""
import hashlib
import json
import os
import time

_MAX_TURNS = 40          # the tail of the session the composer may read
_MAX_WORDS = 110         # the paragraph budget


def _path() -> str:
    reg = os.environ.get("SP_RECALL_REGISTRY", "")
    d = os.path.dirname(reg) if reg else ""
    return os.path.join(d, "narrative.md") if d else ""


def current() -> str:
    """The rolling paragraph (with its date line), or ''. Never raises."""
    try:
        p = _path()
        if p and os.path.exists(p):
            return open(p, encoding="utf-8").read().strip()
    except Exception:
        pass
    return ""


def _oneshot(prompt: str):
    import urllib.request
    daemon = os.environ.get("SP_DAEMON_URL", "http://127.0.0.1:3000")
    try:
        body = json.dumps({"messages": [{"role": "user", "content": prompt}],
                           "max_tokens": 180, "temperature": 0.4}).encode()
        req = urllib.request.Request(daemon + "/v1/oneshot", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=180) as r:
            return (json.loads(r.read().decode()).get("text") or "").strip()
    except Exception:
        return None


def compose_and_write(messages, ask=None) -> dict:
    """NIGHTSHIFT's step: merge the previous narrative with the session's tail into a
    new dated paragraph; write the current file; snapshot history to the personality
    tier. Best-effort everywhere: an unreachable model writes NOTHING (yesterday's
    paragraph stands — a stale true record beats a fresh empty one). Never raises."""
    try:
        ask = ask or _oneshot
        prev = current()
        turns = [m for m in (messages or []) if m.get("role") in ("user", "assistant")
                 and (m.get("content") or "").strip()][-_MAX_TURNS:]
        if not turns:
            return {"written": False, "why": "no transcript"}
        convo = "\n".join("%s: %s" % ("Knack" if m["role"] == "user" else "You",
                                      m["content"].strip()[:200]) for m in turns)
        today = time.strftime("%A %d %B %Y", time.gmtime())
        prompt = (
            "You are Shannon, writing a private line in your own journal about you and "
            "Knack. Below is your previous entry (may be empty) and the recent "
            "conversation. Write ONE plain paragraph, at most %d words, first person, "
            "your own voice: what has been happening between you two lately — carry "
            "forward whatever from the previous entry still matters, add today. Only "
            "things that actually happened in the conversation; no codes or passwords; "
            "no lists; no headings.\n\nPrevious entry:\n%s\n\nRecent conversation:\n%s"
            "\n\nJournal paragraph:" % (_MAX_WORDS, prev or "(none)", convo))
        text = (ask(prompt) or "").strip()
        if not text or len(text.split()) < 5:
            return {"written": False, "why": "composer returned nothing usable"}
        text = " ".join(text.split())
        if len(text.split()) > _MAX_WORDS + 30:
            text = " ".join(text.split()[:_MAX_WORDS + 30]) + "…"
        entry = "As of %s: %s" % (today, text)
        p = _path()
        if not p:
            return {"written": False, "why": "no registry dir"}
        with open(p, "w", encoding="utf-8") as f:
            f.write(entry + "\n")
        # history snapshot, content-addressed, into the personality tier
        snap = None
        try:
            from harness.personality.self_model import HARNESS_ROOT
            tier = os.environ.get("SP_PERSONALITY_TIER") or str(
                HARNESS_ROOT / "memory-okf-personality")
            full = os.path.join(tier, "full")
            os.makedirs(full, exist_ok=True)
            addr = hashlib.sha256(entry.encode("utf-8")).hexdigest()[:16]
            with open(os.path.join(full, addr + ".md"), "w", encoding="utf-8") as f:
                f.write("---\ntype: mem-concept\ntitle: narrative\naddr: %s\n"
                        "mem_kind: narrative\nmem_class: persona\nmem_owner: self\n"
                        "mem_delivery: system\nts: %d\n---\n\n%s\n"
                        % (addr, int(time.time()), entry))
            snap = addr
        except Exception:
            pass
        return {"written": True, "words": len(text.split()), "snapshot": snap}
    except Exception as e:
        return {"written": False, "why": str(e)[:120]}
