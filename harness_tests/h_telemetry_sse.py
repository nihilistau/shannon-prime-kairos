"""G-HARNESS-TELEMETRY-SSE — the harness half of the LM-B2 SSE sink.

Runs the TelemetrySink against a LIVE sp-daemon (served with SP_TELEMETRY=1 + a
memory store), fires recall queries, and verifies the harness durably sinks the
engine's broadcast telemetry — content-addressed, deduped, and STILL redacted.

PRECONDITION: sp-daemon on :3000 with SP_TELEMETRY=1 and a servable secret concept
(e.g. run_refine.bat off in the engine repo, store = _refine_corpus/store).

    python tests/h_telemetry_sse.py
"""
from __future__ import annotations

import os
import shutil
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness.inference.client import get_client
from harness.inference.inference_config import InferenceConfig
from harness.telemetry.sink import TelemetrySink

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_telemetry_gate")
SECRET = "orchid"  # the private-secret value that must NEVER appear in the sink

QUERIES = [
    "What is the chemical symbol for gold now?",
    "What is the recovery phrase for the Meridian vault archive?",
]


def main() -> int:
    if os.path.isdir(ROOT):
        shutil.rmtree(ROOT)
    client = get_client()
    if not client.health():
        print("FAIL: daemon not healthy on :3000 (start run_refine.bat off with SP_TELEMETRY=1)")
        return 1

    sink = TelemetrySink(ROOT)
    stop = threading.Event()
    th = threading.Thread(target=sink.run, args=(client, stop), daemon=True)
    th.start()
    time.sleep(1.5)  # let the /v1/events subscription establish

    cfg = InferenceConfig(max_tokens=40, temperature=0.0)
    for q in QUERIES:
        try:
            client.chat(messages=[{"role": "user", "content": q}], config=cfg)
        except Exception as exc:
            print(f"  (query error, continuing: {exc})")
    time.sleep(3.0)  # drain the event stream
    stop.set()
    time.sleep(0.5)

    stats = sink.stats()
    print(f"\nsink stats: {stats}")

    # 1) records durably written
    n = stats.get("records", 0)
    # 2) both record kinds present (decision + turn)
    kinds_ok = stats.get("kind_decision", 0) >= 1 and stats.get("kind_turn", 0) >= 1
    # 3) REDACTION: the secret must not appear in ANY sinked record
    leak = 0
    for fn in os.listdir(sink.records):
        body = open(os.path.join(sink.records, fn), encoding="utf-8").read()
        if SECRET in body.lower():
            leak += 1
    # 4) DEDUP: re-sinking an existing record is idempotent
    dup_ok = True
    files = os.listdir(sink.records)
    if files:
        body = open(os.path.join(sink.records, files[0]), encoding="utf-8").read()
        _, is_new = sink.sink(body)
        dup_ok = (is_new is False)

    print(f"records={n}  kinds_ok={kinds_ok}  redaction_leak={leak}  dedup_ok={dup_ok}")
    ok = n >= 2 and kinds_ok and leak == 0 and dup_ok
    print(f"REDACTION: secret {SECRET!r} in sinked records = {leak} -> {'PASS' if leak == 0 else 'FAIL'}")
    print(f"RESULT harness-telemetry-sse: {'PASS' if ok else 'FAIL'} "
          f"(durable sink + kinds + redacted + dedup)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
