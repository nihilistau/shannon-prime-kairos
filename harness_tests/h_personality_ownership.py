"""G-PF-OWNERSHIP (PF-B1) — fact ownership: self-facts (about the agent) vs user-facts (about the
operator) are stored owner-tagged as OKF concepts, distinguishable, and the self-model renders ONLY
self-facts. The axis the rest of the personality framework hangs on."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness.personality import self_model as SM

ROOT = Path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "_pf_ownership_gate"))


def main() -> int:
    if ROOT.exists():
        shutil.rmtree(ROOT)
    store = SM.SelfModelStore(ROOT)

    # self-facts (the agent's self-model)
    store.remember_self("I can read and write memories.")
    store.remember_self("I run a 12B model on an RTX 2060 and classify my own memories.")
    # user-facts (about the operator)
    store.remember_user("The user's name is Knack.")
    store.remember_user("The user prefers tea over coffee.", mem_class="preference")

    selff = store.self_facts()
    userf = store.user_facts()
    self_ok = len(selff) == 2 and all(f["owner"] == "self" for f in selff)
    user_ok = len(userf) == 2 and all(f["owner"] == "user" for f in userf)
    distinct = set(f["addr"] for f in selff).isdisjoint(f["addr"] for f in userf)

    # the self-model render must contain ONLY self-facts (never leak user-facts)
    rendered = SM.render_self_model(ROOT)
    render_has_self = "read and write memories" in rendered
    render_no_user = "Knack" not in rendered and "prefers tea" not in rendered

    # OKF-conformant frontmatter (composes with the engine store-merge): mem_class + mem_owner present
    sample = (ROOT / "full" / f"{selff[0]['addr']}.md").read_text(encoding="utf-8")
    okf_ok = "mem_owner: self" in sample and "mem_class:" in sample and "type: mem-concept" in sample

    print(f"self_facts={len(selff)} (owner=self ok={self_ok})  user_facts={len(userf)} (owner=user ok={user_ok})")
    print(f"distinct addrs={distinct}  okf_frontmatter={okf_ok}")
    print(f"self-model render: {rendered!r}")
    print(f"render has self-facts={render_has_self}  render excludes user-facts={render_no_user}")
    ok = self_ok and user_ok and distinct and okf_ok and render_has_self and render_no_user
    print(f"RESULT pf-ownership: {'PASS' if ok else 'FAIL'} "
          f"(self vs user owner-tagged + distinct + OKF-conformant + self-model excludes user-facts)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
