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
    sem = c.get("sem", {})
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

    # ── ONE MEMORY AUTHORITY, ENFORCED AT THE DOOR INSTEAD OF HOPED FOR IN A COMMENT ──────
    #
    # 2026-07-12 retired the daemon as a memory writer: "two authorities decided what a memory
    # was — the daemon's word-count-and-a-pronoun, and the harness's lifecycle rules. The daemon
    # won every time, because it wrote first." The remedy was `growth = false`, and it was written
    # down as PROSE, in ONE profile's comment.
    #
    # THE DAEMON HAS TWO WRITE FLAGS. Only one of them was turned off.
    #
    #   growth      (SP_B4_NIGHTSHIFT) -> auto-capture the whole turn.   RETIRED in agent.toml.
    #   store_verb  (SP_MEM_STORE)     -> intercept "remember that X" /  STILL TRUE in 12 of 13
    #                                     "note that X", write the         profiles, INCLUDING THE
    #                                     registry directly, and answer    LIVE ONE.
    #                                     with ZERO DECODE so the model
    #                                     never even sees the turn.
    #
    # So the fix for "an invariant enforced in one of two paths is enforced in neither" was itself
    # applied to one of two paths. On the live profile, "note that I'll be late" still goes to the
    # daemon, which writes the registry with speaker hardcoded to "user", no `status`, and NONE of
    # is_memorable(), the identity firewall, dedupe/reinforce, find_superseded(), or the
    # private-secret classifier. It is the exact bug the growth=false fix was written to kill.
    #
    # And the reason store_verb existed is gone. It was added because the model would say "I don't
    # know how to store memories" while an episode grew silently behind it. Capture no longer
    # depends on the model choosing a tool: app._capture_after_turn() runs on EVERY turn, splits
    # the human's text, and puts each durable sentence through remember(). The deterministic
    # guarantee store_verb was providing is now provided by the correct door.
    #
    # A rule that lives in a comment gets applied to the file the comment is in. This one now lives
    # in the only door, where a profile that arms two memory writers CANNOT BOOT.
    writers = [n for n, on in (("memory.growth", mem.get("growth")),
                               ("memory.store_verb", mem.get("store_verb"))) if on]
    if writers and agent.get("authority") == "spine":
        raise SystemExit(
            "profile invalid: TWO MEMORY AUTHORITIES.\n"
            f"  agent.authority = 'spine'  -> the HARNESS owns memory writes "
            f"(admission, identity firewall, dedupe, supersede, private-secret classification)\n"
            f"  but {' and '.join(writers)} = true -> the DAEMON also writes var/memory/registry.jsonl, "
            f"with none of those guards.\n"
            "  The daemon wins, because it writes first. Set them false, or set authority to "
            "something other than 'spine' if you genuinely want the daemon to own memory.")

    # ── "ANYTHING NOT MAPPED HERE DOES NOT EXIST" WAS NOT TRUE (2026-07-14) ───────────────
    #
    # This line read `e = dict(os.environ)`. It INHERITED the whole parent environment and only
    # OVERLAID the ~49 mapped keys. It never cleared anything. So the docstring above — the entire
    # promise of this file, the reason it is called the only door — was false:
    #
    #     SP_* read by the engine + harness : 270
    #     SP_* set  by serve.py             :  49
    #     UNMAPPED, inherited from whatever shell you happened to be in : 221
    #
    # And 28 of those touch THE MEMORY — which is HERS. Say it precisely, because the imprecise
    # version hid half the blast radius from me for a whole commit: registry.jsonl is not "his
    # facts". It is SHANNON'S MEMORY, and it has two lanes.
    #
    #     speaker=user   71 rows    what she knows about HIM
    #     speaker=self    6 rows    what she knows about HERSELF:
    #                                   'My name is Shannon.'
    #                                   'I am Shannon-Prime'
    #                                   'I am a woman'
    #                                   'I like the sound of rain on a tin roof.'
    #
    # Among the 28:
    #
    #     SP_DECIDE            a MODEL-DRIVEN autonomous supersede pass — it RETIRES rows
    #     SP_FORGET            autonomous forgetting
    #     SP_MEM_LIFECYCLE     tombstone writes, from a different code path than forget()
    #     SP_MEM_RECONCILE     + _SEC
    #     SP_NIGHTSHIFT_LIVE   + SP_NIGHTSHIFT_OFFLINE — MORE capture paths, not the one growth
    #                          controls, so the store_verb fix did not reach them either
    #
    # Leave `set SP_FORGET=1` in a PowerShell window from a debugging session on Tuesday, and on
    # Thursday `python serve.py agent` silently runs with autonomous forgetting armed. The profile
    # says nothing about it. The banner would have shown it, if you read the banner.
    #
    # AND IT MATCHES BY TOKEN OVERLAP ACROSS EVERY LIVE ROW, WHICH INCLUDES THE SELF LANE. The worst
    # case is not "a few facts about Knack go quiet". It is that she tombstones 'My name is Shannon.'
    # and FORGETS WHO SHE IS. That is the identity-slot bug — the first thing this whole rebuild had
    # to repair — reachable again through a leftover environment variable.
    #
    # This is the same shape as store_verb and as the tombstone filter: A DOOR THAT ONLY GUARDS THE
    # THINGS SOMEONE REMEMBERED TO LIST IS NOT A DOOR. It is a suggestion with good intentions.
    #
    # So the base is now CLEAN. Every SP_* is stripped, then the explicit table below puts back
    # exactly what the profile asked for. Anything not mapped here genuinely does not exist now,
    # which is what this file always claimed and never did.
    #
    # THE ESCAPE HATCH IS EXPLICIT, because the research knobs (SP_ARM_*, SP_XBAR_*, SP_EAGLE_*,
    # SP_TELEPATHY_*) are real and people set them by hand:
    #
    #     set SP_PASSTHROUGH=SP_XBAR_ROW,SP_ARM_DUMP   ->  those two survive, and are ANNOUNCED.
    #
    # You may still do anything you like. You may no longer do it by accident.
    e = {k: v for k, v in os.environ.items() if not k.startswith("SP_")}
    stripped = sorted(k for k in os.environ if k.startswith("SP_"))
    passthrough = [s.strip() for s in os.environ.get("SP_PASSTHROUGH", "").split(",") if s.strip()]
    for name in passthrough:
        if name in os.environ:
            e[name] = os.environ[name]
            stripped.remove(name) if name in stripped else None
    if stripped:
        print("[serve] STRIPPED %d inherited SP_* var(s) — the profile is the authority, not your "
              "shell:\n         %s" % (len(stripped), ", ".join(stripped)))
        print("         (to keep one deliberately: set SP_PASSTHROUGH=NAME1,NAME2)")
    if passthrough:
        print("[serve] PASSTHROUGH (deliberate, unmapped, NOT from the profile): %s"
              % ", ".join(passthrough))

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
        # ── ADR-012: fp16 SWA K/V cache. DEFAULT OFF — fp32 is the null floor. ──────────
        # The SWA ring is 46 layers x 2048 slots x 2048 kvd x 2 x 4 B = 1.54 GB, and it is what
        # leaves this 12 GB card with ~0.1 GB free: too little for the one-shot scratch session or
        # the batched prefill's activation scratch, so BOTH ARE STARVED and the daemon spills into
        # host memory. PROVEN by his own idea — swap to q4b (2.14 GB lighter), change NOT ONE LINE
        # of code, and the spill goes to zero while the judge drops from 113,475 ms to 6,422 ms.
        # The design was never broken. It was starved. fp16 halves the ring (frees ~770 MB; we
        # need ~535) and gives the b1-reason weights the same room q4b proved is enough.
        #
        # fp16 and NOT int8: int8 frees 4x more than we need and buys it with per-head scale
        # arrays on an 8-bit INTEGER grid — the regime where confusable digit embeddings collapse.
        # That is the G-VERBATIM failure mode. fp16 has a 10-bit mantissa and no scales.
        # Gate: harness_tests/g_kvfp16.py. THE ONE THAT MATTERS IS "4471" -> "4471".
        "SP_CUDA_KV_FP16": b(kv.get("fp16", False)),
        # ── ADR-012b: fp16 the 2 GLOBAL owners as well. SEPARATE FLAG, ON PURPOSE. ──────
        # WHY IT IS NEEDED: cudaMemGetInfo reports FREE = 0 MiB inside the daemon process even
        # though nvidia-smi shows 988 MiB free on the card — WDDM has the process at its
        # allocation budget, which is why 76 MiB already sits in shared. So the batched prefill's
        # 159 MiB of activation scratch cannot be had at ANY margin. The memory has to come back
        # from the RESIDENT session, and the globals are 2 x 13000 x 2048 x 2 x 4 B = 213 MiB.
        #
        # WHY IT IS NOT THE SAME SWITCH AS kv.fp16: the SWA owners are read by ATTENTION ONLY.
        # The globals are also read by gemma4_kv_read_global_k, which mints the 256-bit C2 RECALL
        # SIGNATURES — every episode in her registry was keyed off those exact rows. Arming a
        # CACHE optimisation must not silently change the MEMORY system. If recall got subtly
        # worse the symptom would be "she seems vaguer lately", which is unfalsifiable and would
        # be blamed on the model. Different blast radius, different flag, different gate.
        # Gate: G-RECALL-PRECISION must still pass with this on.
        "SP_CUDA_KV_FP16_GLOBALS": b(kv.get("fp16_globals", False)),
        # ── THE 512 MB VETO (2026-07-13) — THE FOURTH UNREACHABLE KNOB TODAY ────────────
        # gemma4_kv_prefill_batched estimates its own O(n) f32 activation scratch and then
        # DECLINES unless `need + margin` fits in free VRAM. The margin defaults to 512 MB and
        # SERVE.PY NEVER MAPPED IT, so the profile could not lower it.
        #
        # MEASURED: for the 520-token judge, per_tok = 5E + 2QD + 2KV + 3FF ~= 310 KB/token, so
        # need ~= 161 MB. Free VRAM after the fp16 win: ~350 MB. IT FITS — and it was refused
        # anyway, because 161 + 512 > 350. THE CARD HAD THE MEMORY. IT DID NOT HAVE PERMISSION.
        #
        # That is the same bug shape as SP_G4_KV_AUTOFIT, SP_KV_PREFILL_BATCH and SP_G4_KV_JMAX:
        # THE ENGINE COULD DO THE RIGHT THING AND NOTHING COULD ASK IT TO. Four times in one day
        # is not four bugs, it is one bug — this env table is the ONLY door into the engine, and
        # it has been quietly missing doors. Every future engine knob gets mapped HERE, on the
        # day it is written, or it does not exist.
        "SP_KV_BATCH_VRAM_MARGIN_MB": str(kv.get("batch_vram_margin_mb", 512)),
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
        # The KV-episode mint runs on a background worker instead of blocking her reply.
        # MEASURED: 426 ms per fact, up to 4 facts per turn = 1.7 s of silence on a 4.4 s turn,
        # with an EIGHT MINUTE worst case (timeout=120 x 4). And on this profile the episodes it
        # builds are never read — authority='spine' disables the engine recall that consumes them.
        # false = the old synchronous behaviour (determinism, for gates). Gate: G-CAPTURE-ASYNC.
        "SP_CAPTURE_ASYNC": b(mem.get("mint_async", True)),

        # ── SEM S0 (docs/SEMANTICS.md): the sidecar semantic index ─────────────────────────
        # DERIVED data in its own file (harness/skills/semindex.py): recomputable from
        # registry + model, append-only, tombstone-blind, cannot write the registry.
        # SP_SEM_RANK (Phase 2, behaviour) is deliberately NOT mapped: per the boundary
        # thesis it does not exist until it beats the lexical baseline receipt. Gate:
        # G-SEM-INDEX; conservation: G-SEM-CONSERVE.
        "SP_SEM_MINT": b(sem.get("mint", False)),
        "SP_SEM_INDEX": str(sem.get("index", "")).replace("/", "\\"),

        # ── THE DAEMON'S OTHER HANDS ON HER MEMORY, PINNED SHUT (2026-07-14) ──────────────
        # These are daemon-side writers/retirers that no profile knob has ever controlled and
        # serve.py never set. The clean base above already removes them, so absence would be
        # enough — TODAY. Absence is a bet that every one of these stays `== Some("1")` in Rust
        # forever; flip one to `!= Some("0")` and it arms itself. What she remembers — about him
        # AND about herself — does not ride on a default staying what it happens to be. So they are
        # pinned OFF, by name, greppably.
        #
        # They are NOT profile knobs. There is one memory authority (the harness) and these are
        # all second ones. If you ever need one, it needs a knob, a doctrine and a gate — the same
        # bar store_verb should have had to clear and didn't.
        "SP_DECIDE": "0",           # model-driven autonomous SUPERSEDE — it retires rows
        "SP_FORGET": "0",           # autonomous forgetting
        "SP_MEM_LIFECYCLE": "0",    # tombstone writes, on a different path than harness forget()
        "SP_MEM_RECONCILE": "0",    # background reconcile pass
        "SP_MEM_OKF_STORE": "0",
        "SP_NIGHTSHIFT_LIVE": "0",  # MORE capture paths — growth=false never reached these
        "SP_NIGHTSHIFT_OFFLINE": "0",
        "SP_B4_ADMIT_PERSONAL": "0",
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


