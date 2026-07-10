"""G-HARNESS-DAEMON-E2E -- first real token off the LIVE sp-daemon through the gateway.

The harness's inference seam (SPDaemonClient + InferenceConfig.to_sp_chat) driving
the resident Gemma-4-12B over POST /v1/chat. Requires the daemon up on :3000 and
the gateway extra (httpx). This is a LIVE gate, not an offline unit test.

    python tests/g_daemon_e2e.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from harness.inference.client import SPDaemonClient
from harness.inference.inference_config import InferenceConfig

DAEMON = os.environ.get("SP_DAEMON_URL", "http://127.0.0.1:3000")


def main() -> int:
    c = SPDaemonClient(DAEMON)
    print(f"[daemon]   {DAEMON}")
    print(f"[health]   {c.health()}   metrics={c.metrics()}")

    # Clean generation test: a single-knob config through the real seam.
    cfg = InferenceConfig(temperature=0.0, max_tokens=24, auto_recall=False)
    body = cfg.to_sp_chat(messages=[{"role": "user", "content": "x"}])
    print(f"[seam]     to_sp_chat -> {body}")

    msgs = [{"role": "user", "content": "Reply with exactly: HELLO FROM THE HARNESS"}]
    print("[stream]   ", end="", flush=True)
    gen = c.chat_stream(messages=msgs, config=cfg)
    toks = []
    resp = None
    try:
        while True:
            d = next(gen)
            toks.append(d)
            print(d, end="", flush=True)
    except StopIteration as stop:
        resp = stop.value
    print()

    text = (resp.text if resp else "".join(toks)).strip()
    chat_id = resp.chat_id if resp else None
    ok = len(toks) > 0 and len(text) > 0
    print(f"[aggregate] tokens={len(toks)} chat_id={chat_id} text={text!r}")
    print(f"G-HARNESS-DAEMON-E2E: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
