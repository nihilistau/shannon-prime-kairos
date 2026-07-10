---
type: design
title: "ADR-KAI5 — Latent Telepathy to Audio: Shannon as a continuous speech backbone via the existing LatentBridge framework"
description: "Extends the PROVEN Telepathy LatentBridge (TELE-1..10b, gemma->qwen) to audio decoders. Two new bridges: (IN) audio->Shannon residual = the native encoder-free voice path retroactively cast as a linear adapter; (OUT) Shannon hidden-tap -> Mimi/voxtral continuous decoder latent = a CALM-style Voice-Head. The OUT bridge reads Shannon and writes an EXTERNAL decoder, so it structurally cannot perturb the 12B latent space (same safety as the Qwen bridge). Design-only; additive; default-off."
tags: [design, telepathy, latent-bridge, audio, voice, mimi, voxtral, csm, calm, kai4, kai5]
timestamp: 2026-07-11T00:00:00Z
resource: shannon-prime-kairos/papers/ADR-KAI5-LATENT-TELEPATHY-AUDIO.md
sp_status: DRAFT
sp_gate: G-VOICEHEAD-PARITY (off=null floor) | G-VOICEHEAD-ROUNDTRIP | G-VOICEHEAD-REJECT | G-ADAPTER-CONFORM | G-AUDIO-IN-PARITY
sp_commit: TBD
sp_repro: "see 8. Gates; PoC harness under kairos tools/telepathy_audio/ (offline, default-off)"
---

# ADR-KAI5 — Latent Telepathy to Audio

**Status:** DRAFT for review. **Author:** Claude (SP hat), 2026-07-11. **Builds on:** [PPT-LAT-TELEPATHY-LatentBridge-spec.md] (the LatentBridge framework, TELE-1..10b GREEN), [ADR-KAI4-LATENT-VOICE.md] (the native encoder-free audio channel proven 2026-07-11), and the byte-exact served gemma4-12b-unified.

> **Receipts-first honesty.** PROVEN today: (1) the native encoder-free **audio-IN** path — raw 16k -> 640-sample frames -> RMSNorm -> `embed_audio.projection` [3840,640] -> `gemma4_kv_inject_seq` at token 258881; clean TTS transcribes real speech through the served 12B. (2) The **Telepathy LatentBridge** framework: cross-family gemma->qwen2.5-coder, generation-tuned adapter, held-out reconstruction CE 4.66->0.83, positional bandwidth kept, cemented in the daemon (`telepathy.rs`, `SP_TELEPATHY` default-off, fail-closed license). Everything in 5-7 below (the audio-OUT Voice-Head) is **SPEC/PoC** until gated. No overclaim.

---

## 1. The thesis this restores

Shannon-Prime's constitution (CONTRACT 6): **every modality enters and leaves the model through ONE latent seam** — no detokenize/retokenize round-trip. Telepathy is the named framework for that (`LatentBridge{src -> adapter -> dst}` over the `gemma4_kv_inject*` transport). Today the seam carries: same-family draft->12B (identity), cross-family gemma->qwen (learned affine/MLP), and — as of ADR-KAI4 — **audio->12B (linear projection)**. This ADR adds the missing direction: **12B->audio**, so Shannon can *speak* from latent space without emitting text tokens. When both audio directions are bridges, the thesis is whole: one bus, thin per-modality adapters in and out.

## 2. Non-negotiable constraint (operator, 2026-07-11)

> "we don't want it to mess with our current system's latent space. the system works well."

This is satisfied **by construction**, not by discipline:

- The **audio-OUT** bridge's `src` is a *read tap* on Shannon's hidden state and its `dst` is an **external audio decoder** (Mimi / voxtral-rs / Pocket-TTS). It never writes into the 12B residual — identical safety posture to the gemma->qwen bridge, which reads Gemma and writes Qwen. The byte-exact forward is untouched.
- The **audio-IN** bridge writes into the 12B residual, but only on a voice-input turn, `DEFAULT_OFF`, via the already-proven `gemma4_kv_inject_seq` seam (the working KAI-4 path). It is the system that already works.
- Everything is a **new registry entry**, `DEFAULT_OFF`, fail-closed license, process-isolatable (the TELE-9 sidecar pattern gives its own address space, zero VRAM contention with the resident 12B).

No change to the byte-exact core, the served daemon parity, the agent stack, or the existing Qwen bridge.

## 3. What we already have (anti-rebuild inventory)

| asset | state | reuse for KAI-5 |
|---|---|---|
| `LatentBridge` struct + `AdapterBin` loader + affine transfer + `RouteDecision` + fail-closed license | GREEN (`telepathy.rs`, `SP_TELEPATHY`) | the object model + transport + safety for BOTH new bridges |
| `gemma4_kv_inject_seq(s, embs, n_frames, ph)` generic residual-frame inject | GREEN (KAI-3/4 audio, TELE native) | audio-IN transport (already used) |
| `embed_audio.projection` [3840,640] + per-frame RMSNorm | GREEN (KAI-4, 2026-07-11) | audio-IN is retroactively a **linear LatentBridge adapter** |
| generation-tuned cross-family adapter (linear + residual-MLP, warm-start, low-lr) | GREEN (TELE-10/10b) | the training recipe for the audio-OUT Voice-Head adapter |
| self-distillation pairing (deterministic `h` from byte-exact forward) | implicit | free `(text, h, audio-latent)` triples, zero labels |
| voxtral-mini-realtime-rs (flow-matching TTS, continuous conditioning) | ours, on-device | the sovereign audio-OUT `dst` decoder |
| TELE-11/12 boundary (gist channel PROVEN, never-fuse, two-stage) | GREEN | the honest-scope guardrails for audio |

## 4. External grounding (verified 2026-07-11)

- **Kyutai CALM** (Continuous Audio Language Models, Defossez et al., rev. Jan 2026): a transformer backbone emits a contextual embedding per timestep; an **MLP** turns it into the **next continuous frame of an audio VAE via consistency modeling** — no discrete tokens, higher quality at lower cost than token models. Ships **Pocket TTS** (100M, faster-than-realtime on laptop CPU). *This is the audio-OUT Voice-Head, published, with a ready decoder.*
- **Mimi** codec: 24kHz -> conv+transformer -> **12.5Hz sequence of 512-dim continuous latent** -> RVQ (codebook-0 semantic 256-d + acoustic). The 512-dim pre-quantization latent is the OUT target and the richer IN source. Apache, streaming, low-latency.
- **CSM / Moshi**: backbone -> codebook-0 -> depth-transformer over acoustic codebooks = **discrete**. REJECT the discrete path (the tokenization tax we already rejected in the Audex teardown). Reuse their **codec (Mimi)** and their **full-duplex interface** (inner-monologue dual stream), never their backbone. Shannon IS the backbone.

The convergence: our own Audex teardown ("continuous conditioning vector, reject discrete tokens") + CALM (the same idea, published, from the Mimi authors) + our TELE-11/12 finding (the latent channel is a strong **continuous/gist** carrier, weak on exact symbols). Speech is a continuous/gist target — this plays to the channel's proven strength.

## 5. The two bridges

### 5.1 Bridge IN — `audio -> 12B` (already live; formalize as a LatentBridge)

```
LatentBridge {
  src:     audio (raw-640 frames  |  Mimi-encoder 512-d semantic latent)
  dst:     shannon-12b-unified.residual  (inject token 258881)
  adapter: linear   # v0 = embed_audio.projection (native, PROVEN)
                    # v1 = learned linear from Mimi-enc latent (robust on noisy mic)
  transport: gemma4_kv_inject_seq
  flags:   DEFAULT_OFF | ONE_SHOT
}
```

v0 is done (KAI-4). v1 is optional: the raw-640 projection is shallow (clean TTS works; noisy mic struggles). Mimi's encoder latent is denoised/learned — a `Mimi-enc-512 -> 3840` linear adapter (fit on paired `(audio -> Mimi-latent, audio -> what the native path injects)` or directly on ASR supervision) would harden real-room comprehension. Same seam, new adapter, default-off.

### 5.2 Bridge OUT — `12B -> audio` (the build: a continuous CSM, Shannon as backbone)

```
LatentBridge {
  src:     shannon-12b-unified.hidden  (late-residual tap, layer ~L; the "intent" vector)
  dst:     audio-decoder  (Mimi.decoder  |  voxtral-rs flow decoder  |  Pocket-TTS)
  adapter: learned  # consistency/flow MLP: h[3840] -> decoder-latent[512] per 12.5Hz frame
  transport: (NEW dst type) hand adapted latent to the external decoder forward
  flags:   DEFAULT_OFF | REQUIRE_ATTEST
}
```

This is the CALM architecture with Shannon as the backbone. Per-timestep: read `h_t` -> Voice-Head MLP -> 512-d Mimi frame (consistency-modeled) -> Mimi decoder -> waveform. No RVQ, no discrete audio tokens, no backbone surgery. The `dst` taxonomy gains one member ("decoder/vocoder") — the only framework extension KAI-5 needs.

**Rate adapter:** Shannon decodes at token rate; Mimi wants 12.5Hz. Per CALM, the MLP emits one VAE frame per backbone step; we pace the backbone (or interpolate) to 12.5Hz. Detail for the PoC to measure.

**Why it can't corrupt Shannon:** `src` is a read-only tap; `dst` is external. The 12B forward is byte-identical whether the Voice-Head fires or not. `G-VOICEHEAD-PARITY` asserts exactly this.

## 6. Training the Voice-Head (byte-exactness is the unlock)

Because Shannon's forward is a deterministic fixed function, `h_t` is a **stable regression target**, so this is supervised, offline, and verifiable — no RL, no backbone touch:

1. **Self-distill pairs.** For a corpus of utterances: run Shannon on the text -> capture the per-position `h_t` sequence (deterministic). TTS the same text (our voxtral-rs) -> Mimi-encode -> the 512-d target latent sequence. Align by time. Result: `(h_t, mimi_latent_t)` pairs, zero human labels.
2. **Fit `B_out`.** Warm-start a linear map, then a zero-init residual-MLP (the exact TELE-10b recipe that took gemma->qwen CE 4.66->0.83). Objective = consistency/flow matching to the VAE frame (CALM), not cosine (the "cosine trap" TELE-10 flagged). Low lr (TELE-10: 3e-4 diverged, 3e-5 converged).
3. **Verify bit-stably.** Same `h` -> same latent -> cacheable, unit-testable. Decode through Mimi; measure MOS/STOI vs the TTS reference.

## 7. Safety, licensing, honest scope (inherited)

- **Null floor:** `DEFAULT_OFF` + no license => both bridges inert; daemon byte-identical. (`G-VOICEHEAD-PARITY`, `G-AUDIO-IN-PARITY`.)
- **IP:** Telepathy is the separately-licensed proprietary component on the MIT substrate; the Voice-Head adapter ships under it, fail-closed, self-disabling only (no host-external effects). The audio codecs stay at their own licenses (Mimi Apache, voxtral-rs ours).
- **Honest scope:** the latent channel is a **continuous/gist** carrier (TELE-11/12). For speech that is the *right* target. We do NOT claim it transmits exact symbols through the audio channel; if precise text is needed it rides the parallel clean-text stream (Moshi inner-monologue), never fused into the latent (TELE-12 never-fuse).

## 8. Gates (new, mirroring the Telepathy contract)

| gate | asserts | status |
|---|---|---|
| `G-AUDIO-IN-PARITY` | audio-IN bridge off => 12B byte-identical | inherited GREEN (KAI-4 default path) |
| `G-VOICEHEAD-PARITY` | Voice-Head off / no license => 12B forward + daemon byte-identical (read-tap only) | SPEC (PoC) |
| `G-VOICEHEAD-ROUNDTRIP` | `(text -> h -> B_out -> Mimi.decode)` audio is intelligible + speaker-consistent >= stated MOS/STOI threshold | SPEC (PoC) |
| `G-VOICEHEAD-REJECT` | an out-of-domain `h` (e.g. a refusal/empty turn) does not emit garbage speech | SPEC |
| `G-ADAPTER-CONFORM` | the Voice-Head adapter ships all five spec-3.1 deliverables + green gates | SPEC |
| `G-AUDIO-IN-ROBUST` (optional) | Mimi-enc IN adapter beats raw-640 on noisy-mic ASR | SPEC |

## 9. Phased plan (all additive, default-off; nothing touches the working path)

- **P0 (PoC, offline):** `kairos tools/telepathy_audio/` — self-distill `(h, mimi_latent)` pairs from the served 12B + voxtral-rs TTS + Mimi encode; fit `B_out` (linear -> residual-MLP); decode through Mimi; report intelligibility. Process-isolated, no daemon wiring. **Answers: does Shannon's `h` drive a vocoder?**
- **P1:** register the Voice-Head as a `LatentBridge` (`dst`=decoder), `SP_VOICEHEAD` default-off, `G-VOICEHEAD-PARITY` null-floor gate. Sidecar first (TELE-9 pattern), native later.
- **P2:** streaming + rate adapter -> realtime; wire into the console voice channel as an *alternative* output to the v0 browser TTS (opt-in).
- **P3 (optional):** Mimi-encoder IN adapter for noisy-mic robustness; full-duplex dual-stream (Moshi interface) with Shannon as the single backbone.

## 10. Open questions

- Best tap layer `L` for `h_t` (TELE-2 found late residual ~16-22 is the clean seam for gemma->qwen; the Voice-Head may prefer the final pre-logit hidden — PoC measures).
- Consistency vs flow-matching for the frame head (CALM uses consistency; voxtral-rs uses flow — pick per decoder).
- Which `dst` decoder ships first: Mimi.decoder (smallest, streaming, Apache) vs voxtral-rs (most sovereign) vs Pocket-TTS (published-with-CALM). Recommend Mimi for the PoC (fastest to a number), voxtral-rs for the sovereign product.
