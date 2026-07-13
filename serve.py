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
    # G-VERBATIM lint (2026-07-12): no_repeat_ngram>=2 BANS re-emitting any N-token
    # sequence already in context — which is exactly what quoting a number, a memory
    # or a tool result requires. It cost us a multi-day hunt (the model was innocent:
    # it wanted '7' at margin 9.0 and the sampler masked it). Never again silently.
    if int(dec.get("no_repeat_ngram", 0)) >= 2 and os.environ.get("SP_ALLOW_NGRAM_BAN") != "1":
        raise SystemExit(
            f"profile invalid: no_repeat_ngram={dec['no_repeat_ngram']} breaks verbatim copy "
            f"(G-VERBATIM). Set 0, or export SP_ALLOW_NGRAM_BAN=1 to override deliberately.")

    e = dict(os.environ)
    e["PATH"] = paths["llvm_bin"].replace("/", "\\") + os.pathsep + e.get("PATH", "")
    b = lambda v: "1" if v else "0"
    e.update({
        # Tier 0
        # G-VERBATIM (2026-07-12): the SERVING forward does NOT go through the L1
        # ABI / math-core. kvdecode=1 routes the chat path straight into the CUDA
        # gemma4_kv_* re-implementation. kvdecode=0 falls back to the L1 session
        # (prefill_chunk/decode_step) = the math-core forward the gold gates test.
        # That fallback is our IN-HOUSE REFERENCE for the copy bug.
        "SP_DAEMON_BACKEND": c["paths"].get("backend", "cuda"),
        "SP_DAEMON_KVDECODE": "1" if kv.get("kvdecode", True) else "0",
        # G-VERBATIM (2026-07-12): the KV cache was ALWAYS int8-quantized. Digit
        # tokens have near-identical embeddings, so int8 K/V collapses them and
        # the model cannot read a number back out of its own context ("4471" ->
        # "4417"/"4481", "RTX 2060" -> "RTX 3061", tool time -> "2014-365"),
        # while distinctive words (quartzblanket, Knack) survive. Profile-driven
        # now; the gate is harness_tests/g_verbatim.py.
        "SP_CUDA_DECODE_INT8": "1" if kv.get("int8", True) else "0",
        "SP_DAEMON_KVDECODE_RING_W": str(kv["ring_w"]),
        "SP_DAEMON_KVDECODE_PMAX": str(kv["pmax"]),
        # ── THE 32-TOKEN CLIFF (2026-07-13) ─────────────────────────────────────────────
        # MEASURED: 164 SECONDS to say "Hello! How are you today?".
        #     !! RE-PREFILL 2679 tok in 163.3s -- the cache was thrown away
        # ...on a prompt that shared a 2517-token IDENTICAL PREAMBLE with the cache that was
        # already resident. 94% of the work had already been done, correctly, and sat in VRAM.
        # It was thrown away because the OTHER 6% differed.
        #
        # The persist-KV cache can rewind a divergence of at most REWIND_BOUND tokens before
        # it gives up and re-prefills from token 0. REWIND_BOUND was a hardcoded 32, and the
        # SWA undo-journal that bounds it (SP_G4_KV_JMAX) defaults to 64 and WAS NOT MAPPED
        # HERE AT ALL -- the engine reads it, the profile could not set it. (RING_W and PMAX
        # were mapped. JMAX was not. Third unreachable knob today, same shape as SP_G4_KV_AUTOFIT
        # and SP_KV_PREFILL_BATCH: THE ENGINE COULD DO THE RIGHT THING AND NOTHING COULD ASK IT TO.)
        #
        # 32 tokens is not a budget, it is a cliff. Everything real steps off it:
        #     a new conversation      diverges ~160 tokens
        #     a recall injection      diverges ~100-200
        #     an aux/judge call       diverges ~1450
        # Each one costs a FULL re-prefill of a preamble that never changed.
        #
        # The journal costs VRAM (~750 KB per journalled position across the SWA owners at
        # ring_w=2048), so this is a real trade against pmax -- which is why it belongs in the
        # profile, in front of the operator, and not buried as a constant in routes.rs.
        "SP_DAEMON_KVDECODE_JMAX": str(kv.get("jmax", 64)),
        "SP_KV_REWIND_BOUND": str(kv.get("rewind_bound", 32)),
        # ── THE SILENT SPILL (2026-07-13). The knob existed and NOTHING COULD REACH IT. ──
        # MEASURED, this session, on the 2060: daemon 11,272 MiB dedicated of a 12,288 MiB
        # card, desktop 674 MiB, and 336 MiB ALREADY IN SHARED (host) MEMORY AT IDLE. An
        # 11-token prompt with max_tokens=4 did not return in four minutes.
        #
        # This is NOT an OOM. Windows/WDDM does not fail an oversubscribed CUDA allocation --
        # it silently backs it with system RAM over PCIe and keeps going. No error, no log,
        # no crash. Just every touched page crossing the bus. THE WORST FAILURE MODE THERE IS:
        # the one that never fails, only degrades, so it presents as a mystery instead of a bug.
        # It is the true answer to "why is it fast at first but painfully slow 6000 turns
        # later?" -- the KV grows into the last free megabytes and then you are not running on
        # a GPU any more, you are running on a GPU pretending.
        #
        # pmax*128 KB is the only Pmax-scaling term (the 8 global-attention layers; the SWA
        # layers are ring-bounded and O(1)). pmax=12096 => ~1.55 GB, allocated FLAT, on a card
        # with ~340 MiB spare. gemma4_kv_open has had the fix since ADR-010/PK2 wave-6 -- it
        # reads cudaMemGetInfo and clamps Pmax to the VRAM that is ACTUALLY FREE -- and it is
        # default-off, and this table never mapped it, so the profile could not turn it on and
        # nobody knew it was there.
        #
        # THE SAME BUG AS EVERY OTHER BUG IN THIS CODEBASE: the invariant is enforced in one of
        # two paths, so it is enforced in NEITHER. The engine can size itself to the card. The
        # launcher could not ask it to.
        #
        # It only ever clamps DOWN, never up. Gate: harness_tests/g_vram.py.
        "SP_G4_KV_AUTOFIT": b(kv.get("autofit", True)),
        "SP_G4_KV_AUTOFIT_MARGIN_MB": str(kv.get("autofit_margin_mb", 512)),
        "SP_PERSIST_KV": b(kv["persist"]),
        "SP_PERSIST_B4": b(kv["persist_b4"]),
        "SP_PREFIX_SNAPSHOT": b(kv.get("prefix_snapshot", False)),  # P1c
        # G-PERF (2026-07-12): prefill is ~60 ms/TOKEN per-token — the 1618-token
        # preamble therefore costs ~96 s cold (measured: prefill 102035 ms for ~1600
        # tok). CONTRACT-BATCH-PREFILL replaces the per-token launch storm with one
        # n-wide forward. The C side enforces its preconditions (cold turn, ring-off,
        # full cache) and ERRORS otherwise, falling through to the per-token path —
        # so arming it can only help or no-op. Gate before trusting: G-VERBATIM.
        "SP_KV_PREFILL_BATCH": b(kv.get("prefill_batch", False)),
        "SP_EOT_BIAS": str(dec["eot_bias"]),

        # KAIROS: arm the continuation impulse (the raw stop-vs-continue logit margin the
        # forward already computes and used to discard). Off => never computed, byte-identical.

        "SP_KAIROS": b(c.get("kairos", {}).get("enabled", False)),
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
    # G-VERBATIM: keep the tap open through the DECODE steps (the ones that make
    # every token the user sees). Without this we only ever measured prefill.
    if dbg.get("hidden_dump_decode"):
        e["SP_HIDDEN_DUMP_DECODE"] = "1"
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


