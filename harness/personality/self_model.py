"""PF-B1 — fact ownership + the agent self-model, stored as OKF concepts.

`mem_owner` is an axis ORTHOGONAL to `mem_class` (ADR-004): who the fact is ABOUT.
  - self  : a fact about the AGENT (its capabilities/identity) — the self-model.
  - user  : a fact about the OPERATOR.
The owner is set at CAPTURE by the SOURCE (the agent asserting a self-fact vs the user stating a
user-fact), NOT inferred from text — so it needs no classifier. Facts are written as content-
addressed OKF concepts with `mem_owner` frontmatter, so the same store-merge (engine) + curator
(DF-B6) machinery serves/curates them. `render_self_model()` produces the self-model block for the
persona system prefix (PF-B2 will fold it into load_agent_system).
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Dict, List, Optional

HARNESS_ROOT = Path(__file__).resolve().parents[2]
SELF_TIER = HARNESS_ROOT / "memory-okf-self"   # the self-model + user-facts store (owner-tagged)


def _resolve_root(root=None) -> Path:
    """Root precedence: explicit arg > SP_SELF_MODEL_ROOT env > default SELF_TIER."""
    return Path(root) if root else Path(os.environ.get("SP_SELF_MODEL_ROOT") or SELF_TIER)

# CONSUMED from THE class registry (2026-07-14, INVARIANT-ROADMAP.md Tier 1.2). The
# local copy had drifted from the 2026-07-12 engine fix (fact/episodic-event -> system,
# not recite: a remembered thing is CONTEXT, not a command). self-fact stays recite by
# doctrine — she does not paraphrase who she is. G-MEMCLASS convicts any new copy.
from harness.skills import memclass as _mc

_CLASS_DELIVERY = _mc.delivery_map()


def _addr(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


class SelfModelStore:
    """OKF-concept store for owner-tagged facts (self-model + user-facts)."""

    def __init__(self, root=None):
        self.full = _resolve_root(root) / "full"
        self.full.mkdir(parents=True, exist_ok=True)

    def _write(self, statement: str, owner: str, mem_class: str) -> str:
        addr = _addr(statement)
        deliv = _CLASS_DELIVERY.get(mem_class, "recite")
        fm = ["---", "type: mem-concept", f"title: {owner}-fact", f"addr: {addr}",
              f"mem_class: {mem_class}", f"mem_owner: {owner}", f"mem_delivery: {deliv}",
              f"ts: {int(time.time())}", "---", "", statement, ""]
        (self.full / f"{addr}.md").write_text("\n".join(fm), encoding="utf-8")
        return addr

    def remember_self(self, statement: str, mem_class: str = "self-fact") -> str:
        """Record a fact ABOUT THE AGENT (the self-model)."""
        return self._write(statement, "self", mem_class)

    def remember_user(self, statement: str, mem_class: str = "fact") -> str:
        """Record a fact ABOUT THE USER."""
        return self._write(statement, "user", mem_class)

    def _iter(self):
        for p in sorted(self.full.glob("*.md")):
            raw = p.read_text(encoding="utf-8")
            owner = mem_class = None
            body = []
            fences = 0
            for line in raw.splitlines():
                if line.strip() == "---":
                    fences += 1; continue
                if fences >= 2:
                    body.append(line)
                elif line.strip().startswith("mem_owner:"):
                    owner = line.split(":", 1)[1].strip()
                elif line.strip().startswith("mem_class:"):
                    mem_class = line.split(":", 1)[1].strip()
            yield {"addr": p.stem, "owner": owner, "class": mem_class,
                   "text": "\n".join(body).strip()}

    def facts(self, owner: Optional[str] = None) -> List[Dict]:
        return [f for f in self._iter() if owner is None or f["owner"] == owner]

    def self_facts(self) -> List[Dict]:
        return self.facts("self")

    def user_facts(self) -> List[Dict]:
        return self.facts("user")


def remember_self(statement: str, mem_class: str = "self-fact", root=None) -> str:
    return SelfModelStore(root).remember_self(statement, mem_class)


def remember_user(statement: str, mem_class: str = "fact", root=None) -> str:
    return SelfModelStore(root).remember_user(statement, mem_class)


def render_self_model(root=None, max_facts: int = 20) -> str:
    """The self-model block for the persona system prefix — ONLY self-facts (never user-facts)."""
    facts = SelfModelStore(root).self_facts()[:max_facts]
    if not facts:
        return ""
    lines = "\n".join(f"- {f['text']}" for f in facts)
    return f"About yourself (self-model):\n{lines}"
