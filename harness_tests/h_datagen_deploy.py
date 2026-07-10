"""G-DF-DEPLOY (DF-B6) — the harness mem_class curator deploys the promoted 0.5B adapter (CPU) as
the drop-in replacement for the engine's 12B model_classify: classify on CPU (reproduce DF-B4),
correct a mis-classed store concept, and honor safety-monotone. The engine then reconciles via
LM-B1 (already GREEN)."""
from __future__ import annotations

import json
import os
import shutil
import sys

os.environ["CUDA_VISIBLE_DEVICES"] = ""  # idle CPU task; never touch the resident engine GPU
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datagen import mem_class_curator as C

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADAPTER = os.path.join(ROOT, "datagen", "adapters", "mem_class")
EVAL = os.path.join(ROOT, "datagen", "datasets", "mem_class_eval.jsonl")
STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_deploy_gate", "store")


def _concept(addr, mem_class, delivery, body):
    fm = ["---", "type: mem-concept", f"title: {addr}", f"addr: {addr}",
          f"mem_class: {mem_class}", f"mem_delivery: {delivery}", "mem_authority: overrides-prior",
          "---", "", body, ""]
    return "\n".join(fm)


def main() -> int:
    print("loading curator on CPU (Qwen2.5-0.5B + adapter)...", flush=True)
    cur = C.MemClassCurator(ADAPTER)
    print("curator loaded", flush=True)

    # 1) reproduce DF-B4 accuracy on the distinct eval set, on CPU, in the harness
    rows = [json.loads(l) for l in open(EVAL, encoding="utf-8") if l.strip()]
    correct = sum(cur.classify(e["instruction"]) == e["output"] for e in rows)
    acc = correct / len(rows)
    print(f"CPU classify acc on distinct eval: {correct}/{len(rows)} = {acc:.3f}", flush=True)

    # 2) curate a mis-classed store: a secret written as counterfact -> curator corrects to private-secret
    full = os.path.join(STORE, "full")
    if os.path.isdir(STORE):
        shutil.rmtree(STORE)
    os.makedirs(full)
    open(os.path.join(full, "aaaa0001.md"), "w", encoding="utf-8").write(
        _concept("aaaa0001", "counterfact", "systemecho",
                 "The recovery phrase for the Meridian vault archive is orchid tango falcon delta."))
    # a persona written as counterfact -> should correct to persona
    open(os.path.join(full, "aaaa0002.md"), "w", encoding="utf-8").write(
        _concept("aaaa0002", "counterfact", "systemecho", "My name is Aldric Vance."))
    # a genuine private-secret -> must NOT be downgraded (safety-monotone)
    open(os.path.join(full, "aaaa0003.md"), "w", encoding="utf-8").write(
        _concept("aaaa0003", "private-secret", "attr-gate-strict", "The launch code is Zulu-9-Tango."))

    corr = cur.curate_store(STORE)
    by_addr = {c["addr"]: c for c in corr}
    print("corrections:", json.dumps(corr), flush=True)

    secret_fixed = by_addr.get("aaaa0001", {}).get("to") == "private-secret"
    persona_fixed = by_addr.get("aaaa0002", {}).get("to") == "persona"
    # aaaa0003 must NOT appear in corrections (stayed private-secret) -> safety-monotone held
    monotone_ok = "aaaa0003" not in by_addr
    # verify the frontmatter was actually rewritten on disk
    disk1 = C._frontmatter_class(open(os.path.join(full, "aaaa0001.md"), encoding="utf-8").read())
    disk_ok = disk1 == "private-secret"

    print(f"secret_fixed(counterfact->private-secret)={secret_fixed}  "
          f"persona_fixed={persona_fixed}  safety_monotone={monotone_ok}  disk_rewritten={disk_ok}")
    ok = (acc >= 0.6 and secret_fixed and persona_fixed and monotone_ok and disk_ok)
    print(f"RESULT df-deploy: {'PASS' if ok else 'FAIL'} "
          f"(CPU classify acc={acc:.2f} + corrects mis-class + safety-monotone + rewrites store)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
