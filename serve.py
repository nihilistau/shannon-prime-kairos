"""kairos serve — ONE profile-driven launcher (G-KAIROS-P3, replaces the .bat zoo).

Usage:
    python serve.py [profile]      # default: agent   (profiles/<name>.toml)
    python serve.py agent --stop   # stop the stack

Reads the profile, maps it to the engine/gateway env with an EXPLICIT table,
ECHOES the effective config (the banner-must-echo lesson), refuses invalid
compositions (two recall authorities), launches the daemon then the gateway,
and waits for both healths.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import tomllib
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
VAR = os.path.join(ROOT, "var")


def load_profile(name: str) -> dict:
    p = os.path.join(ROOT, "profiles", f"{name}.toml")
    with open(p, "rb") as f:
        return tomllib.load(f)


def build_env(c: dict) -> dict:
    """The ONE explicit profile→env mapping. Anything not mapped here does not exist."""
    paths, kv, mem = c["paths"], c["kv"], c["memory"]
    agent, dec, veto = c["agent"], c["decode"], c.get("veto", {})
    if mem.get("recall_authority") != "L5":
        raise SystemExit(f"profile invalid: recall_authority must be 'L5' (got {mem.get('recall_authority')!r})")

    e = dict(os.environ)
    e["PATH"] = paths["llvm_bin"].replace("/", "\\") + os.pathsep + e.get("PATH", "")
    b = lambda v: "1" if v else "0"
    e.update({
        # Tier 0
        "SP_DAEMON_BACKEND": "cuda",
        "SP_DAEMON_KVDECODE": "1",
        "SP_CUDA_DECODE_INT8": "1",
        "SP_DAEMON_KVDECODE_RING_W": str(kv["ring_w"]),
        "SP_DAEMON_KVDECODE_PMAX": str(kv["pmax"]),
        "SP_PERSIST_KV": b(kv["persist"]),
        "SP_PERSIST_B4": b(kv["persist_b4"]),
        "SP_PREFIX_SNAPSHOT": b(kv.get("prefix_snapshot", False)),  # P1c
        "SP_EOT_BIAS": str(dec["eot_bias"]),
        "SP_NO_REPEAT_NGRAM": str(dec["no_repeat_ngram"]),
        # P5a: gateway serving regime. '0' = certified-float turns (explicit
        # client byteexact still wins; daemon default stays exact for gates).
        "SP_GATEWAY_BYTEEXACT": "0" if dec.get("byteexact") is False else "1",
        "CUBLAS_WORKSPACE_CONFIG": ":16:8",
        # memory / recall (L5 authority)
        "SP_AUTO_RECALL_DEFAULT": b(mem["auto_recall_default"]),
        "SP_RECALL_REGISTRY": paths["registry"].replace("/", "\\"),
        "SP_RECALL_L5": "1",
        "SP_RECALL_L5_TAU": str(mem["l5_tau"]),
        "SP_RECALL_ATTR_GATE": b(mem["attr_gate"]),
        "SP_RECALL_ATTR_TAU": str(mem["attr_tau"]),
        "SP_RECALL_QONLY": b(mem["qonly"]),
        "SP_RECALL_L5_PROMPT": mem["delivery"],
        # growth
        "SP_B4_NIGHTSHIFT": b(mem["growth"]),
        "SP_NIGHTSHIFT_PERSIST": b(mem["persist_growth"]),
        "SP_MEM_STORE": b(mem["store_verb"]),
        "SP_MEM_CLASSIFY": b(mem["classify"]),
        "SP_MEM_POLICY": b(mem["policy"]),
        "SP_QKEY_MINT": b(mem["qkey_mint"]),
        # veto
        "SP_SPECTEST": b(veto.get("spectest", False)),
        "SP_SPECTEST_HEAD": paths["spectest_head"].replace("/", "\\"),
        # gateway
        "SP_DAEMON_URL": f"http://127.0.0.1:{c['serve']['port']}",
        "SP_SPINE_TOOLSET": b(agent["spine_toolset"]),
        "SP_SPINE_RECALL": b(agent["spine_recall"]),
        "SP_GATEWAY_AUTHORITY": agent.get("authority", "l5"),
        "SP_GATEWAY_PREWARM": b(agent.get("prewarm", False)),
        "SP_PERSONALITY": b(agent["personality"]),
        "SP_MCP_TOOLS": b(agent["mcp_tools"]),
        # P1a: the kairos exe has no frontend_mockups beside it; the daemon
        # serves THE kairos console (its charter home) via the env override.
        "SP_CONSOLE_DIR": os.path.join(ROOT, "console"),
        "SP_PERSONA_FILE": os.path.join(ROOT, "persona.md"),
        "SP_MCP_CONFIG": os.path.join(ROOT, "mcp_servers.json"),
        "SP_DAEMON_LOG": os.path.join(VAR, "daemon.log"),
        "PYTHONPATH": ROOT,
    })
    # [debug] knobs (P5): optional taps, unset unless the profile arms them.
    dbg = c.get("debug", {})
    if dbg.get("hidden_dump"):
        os.makedirs(os.path.dirname(dbg["hidden_dump"].replace("/", "\\")), exist_ok=True)
        e["SP_HIDDEN_DUMP"] = dbg["hidden_dump"].replace("/", "\\")
    return e


def echo(env: dict) -> None:
    keys = [k for k in sorted(env) if k.startswith(("SP_", "CUBLAS"))]
    print("-- effective config --")
    for k in keys:
        print(f"  {k}={env[k]}")


def wait_http(url: str, secs: int) -> bool:
    for _ in range(secs):
        try:
            urllib.request.urlopen(url, timeout=2).read()
            return True
        except Exception:
            time.sleep(1)
    return False


def stop() -> None:
    subprocess.run(["taskkill", "/F", "/IM", "sp-daemon.exe"], capture_output=True)
    subprocess.run(["powershell", "-NoProfile", "-Command",
                    "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
                    "Where-Object {$_.CommandLine -match 'harness.server.app'} | "
                    "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"], capture_output=True)
    print("stack stopped")


def stop_gateway_only() -> None:
    subprocess.run(["powershell", "-NoProfile", "-Command",
                    "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
                    "Where-Object {$_.CommandLine -match 'harness.server.app'} | "
                    "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"], capture_output=True)


def main() -> int:
    name = next((a for a in sys.argv[1:] if not a.startswith("-")), "agent")
    if "--stop" in sys.argv:
        stop()
        return 0
    c = load_profile(name)
    os.makedirs(VAR, exist_ok=True)
    env = build_env(c)
    # ── --gateway-only (P1b-2a lesson): restart JUST the gateway with the SAME
    # schema-checked env the full boot uses. Hand-rolled envs wedged a daemon
    # turn on 2026-07-11 (receipt G-KAIROS-P1b-2a) — the launcher owns the env.
    if "--gateway-only" in sys.argv:
        print(f"[kairos serve] profile={name} (gateway-only bounce; daemon untouched)")
        stop_gateway_only()
        gw_log = open(os.path.join(VAR, "gateway.log"), "w")
        subprocess.Popen(
            [sys.executable, "-m", "harness.server.app"],
            env=env, cwd=ROOT, stdout=gw_log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW)
        if not wait_http(f"http://127.0.0.1:{c['serve']['gateway_port']}/health", 45):
            print("!! gateway did not come up — see var/gateway.log")
            return 1
        print(f"[kairos serve] gateway up on :{c['serve']['gateway_port']}")
        return 0
    print(f"[kairos serve] profile={name}")
    echo(env)

    stop()
    daemon_log = open(os.path.join(VAR, "daemon.boot.log"), "w")
    subprocess.Popen(
        [c["paths"]["engine_exe"].replace("/", "\\"), "start",
         "--model", c["paths"]["model"], "--tokenizer", c["paths"]["tokenizer"],
         "--port", str(c["serve"]["port"])],
        env=env, stdout=daemon_log, stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW)
    if not wait_http(f"http://127.0.0.1:{c['serve']['port']}/v1/metrics", 90):
        print("!! daemon did not come up — see var/daemon.log")
        return 1
    print(f"[kairos serve] daemon up on :{c['serve']['port']}")

    gw_log = open(os.path.join(VAR, "gateway.log"), "w")
    subprocess.Popen(
        [sys.executable, "-m", "harness.server.app"],
        env=env, cwd=ROOT, stdout=gw_log, stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW)
    if not wait_http(f"http://127.0.0.1:{c['serve']['gateway_port']}/health", 45):
        print("!! gateway did not come up — see var/gateway.log")
        return 1
    print(f"[kairos serve] gateway up on :{c['serve']['gateway_port']}")
    # ── LOAD-TIME PREFILL (operator, 2026-07-11): do NOT report ready while the
    # preamble is still prefilling. The old behavior (background prewarm + open
    # gateway) let the first user turn race the prefill on the one resident
    # session -> persist guard miss -> BOTH paid ~5 minutes. Wait for it here;
    # the gateway also gates chat traffic on the same event.
    if c["agent"].get("prewarm", False):
        print("[kairos serve] prefilling the persona+tools prefix (load-time; ~2-5 min cold)...", flush=True)
        t0 = time.time()
        hot = False
        for _ in range(900):
            try:
                h = json.loads(urllib.request.urlopen(
                    f"http://127.0.0.1:{c['serve']['gateway_port']}/health", timeout=3).read())
                if h.get("warm"):
                    hot = True
                    break
            except Exception:
                pass
            time.sleep(1)
        print(f"[kairos serve] {'prefix HOT in %.0fs — first turn is fast' % (time.time() - t0) if hot else 'prewarm did not confirm; first turn may be slow'}")
    print(f"[kairos serve] READY. console:  http://127.0.0.1:{c['serve']['port']}/")
    print(f"[kairos serve] operator: http://127.0.0.1:{c['serve']['port']}/operator.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
