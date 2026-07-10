"""G-DF-AUTOTRAIN (DF-B5) — the auto-train trigger: telemetry accrual crosses a threshold and fires
the retrain pipeline (convert + merge + train kickoff); below threshold it no-ops; redacted records
don't count; and it's idempotent (the same telemetry never re-fires)."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datagen import auto_train as A
from pathlib import Path

CORPUS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_autotrain_gate")


def seed(n_clear, n_redacted, classes=("counterfact", "persona", "fact", "preference")):
    recs = os.path.join(CORPUS, "records")
    if os.path.isdir(CORPUS):
        shutil.rmtree(CORPUS)
    os.makedirs(recs)
    log = os.path.join(CORPUS, "log.jsonl")
    with open(log, "w", encoding="utf-8") as lf:
        for i in range(n_clear):
            cls = classes[i % len(classes)]
            rec = {"ts": i, "query": f"clear statement number {i}", "redacted": False,
                   "recall": {"class": cls, "delivery": "systemecho", "decision": "deliver"}}
            body = json.dumps(rec)
            addr = hashlib.sha256(body.encode()).hexdigest()[:16]
            open(os.path.join(recs, f"{addr}.json"), "w", encoding="utf-8").write(body)
            lf.write(json.dumps({"addr": addr, "kind": "decision", "class": cls,
                                 "redacted": False, "ts_event": i}) + "\n")
        for j in range(n_redacted):
            rec = {"ts": 9000 + j, "query": f"#{j:016x}", "redacted": True,
                   "recall": {"class": "private-secret", "delivery": "recite", "decision": "deliver"}}
            body = json.dumps(rec)
            addr = hashlib.sha256(body.encode()).hexdigest()[:16]
            open(os.path.join(recs, f"{addr}.json"), "w", encoding="utf-8").write(body)
            lf.write(json.dumps({"addr": addr, "kind": "decision", "class": "private-secret",
                                 "redacted": True, "ts_event": 9000 + j}) + "\n")


def main() -> int:
    # isolate the state file so the gate doesn't touch the real one
    A.STATE_FILE = Path(tempfile.gettempdir()) / "_autotrain_gate_state.json"
    if A.STATE_FILE.exists():
        A.STATE_FILE.unlink()

    fired = {"n": 0}
    def trigger(new, path):
        fired["n"] += 1
        return {"fired": "mock", "new": new}

    THRESH = 50
    # 1) below threshold (40 clear + 10 redacted): redacted don't count -> 40 < 50 -> no fire
    seed(40, 10)
    usable = A.count_usable(CORPUS)
    r1 = A.check_and_train(THRESH, CORPUS, on_ready=trigger)
    below_ok = (usable == 40 and r1["action"] == "below_threshold" and fired["n"] == 0)
    print(f"[below] usable={usable} (redacted excluded) action={r1['action']} fired={fired['n']}")

    # 2) at threshold (60 clear): 60 >= 50 -> FIRE (convert + merge + trigger)
    seed(60, 5)
    r2 = A.check_and_train(THRESH, CORPUS, on_ready=trigger)
    fire_ok = (r2["action"] == "fired" and fired["n"] == 1 and r2["converted"] > 0)
    print(f"[fire]  usable={A.count_usable(CORPUS)} action={r2['action']} converted={r2.get('converted')} "
          f"combined={r2.get('combined')} fired={fired['n']}")

    # 3) idempotent: no new records since -> no re-fire
    r3 = A.check_and_train(THRESH, CORPUS, on_ready=trigger)
    idem_ok = (r3["action"] == "below_threshold" and fired["n"] == 1)
    print(f"[again] action={r3['action']} new={r3.get('new')} fired={fired['n']} (no re-fire)")

    ok = below_ok and fire_ok and idem_ok
    print(f"RESULT df-autotrain: {'PASS' if ok else 'FAIL'} "
          f"(below=no-op, redacted-excluded, at-threshold fires convert+trigger, idempotent)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
