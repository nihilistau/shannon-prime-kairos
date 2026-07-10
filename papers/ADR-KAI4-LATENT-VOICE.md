---
type: adr
title: "ADR-KAI4 — THE LATENT VOICE: sovereign realtime voice I/O on the GNA + the 12B's audio channel"
description: "Bidirectional voice: GNA ear (PROVEN ON SILICON) streaming into the 12B's residual audio channel; a latent Voice Head + GAN vocoder for text-bypassing output; Audex teardown verdicts; phased gates."
tags: [kai4, voice, audio, gna, vocoder, gan, audex, adr]
sp_status: ACTIVE
sp_gate: "G-VOICE-0 .. G-VOICE-5 (defined §7)"
sp_commit: "kairos genesis+"
sp_repro: "every claim carries its receipt (OKFS addr or gate log path)"
---

# ADR-KAI4 — THE LATENT VOICE

## 0. Where we actually are (the inventory nobody should re-derive)

The 2026-07-10 inventory (OKFS pre-flight + asset sweep) established that **the input
half of this campaign is largely BUILT and GATED**:

| asset | state | receipt |
|---|---|---|
| GNA ear encoder: log-mel(64, 40ms/640 hop, 16k) → Conv1d×3(256) → CTC head | trained, ckpt `C:\Users\Knack\audio_ctc.pt` (0.868 held-out) | `_xbar/p2b/kai3/G-KAIROS-3-AUDIO_7of8.log` |
| GNA-legal quantization (POT i16, pad=0, ch÷4) | **full recovery 0.877 == FP32** | `G-KAIROS-3-GNA-i16_quant_gate.log` |
| **Physical GNA 2.0 silicon execution** (`GNA.GNA_HW`, driver 03.05.00.2116, OV 2023.3 Windows) | **GREEN — bit-parity with SW_EXACT** | `G-KAIROS-3-GNA-HW.log` |
| The 12B voice channel: `inject_frames` (E-dim residual frames) + audio placeholder **258881** through `gemma4_kv_inject_seq` | live in the daemon `/v1/chat` | routes.rs B5 seam; KAI-1/2/3 gates |
| Real speech → 12B execution pivot | **7/8** | KAI-3 re-gate 2026-06-17 |
| Projection math: CTC-greedy → softmax(τ=0.2)·W_sub (√H-scaled embed rows) → on-manifold [E] | exported in KAI2 packets | audio_ctc_projector.py |
| WAV/resample/mel/ring-buffer DSP in OUR Rust crate (+ Level-Zero iGPU backend, flow-matching TTS) | voxtral-mini-realtime-rs (ours) | crate tree |
| GNA driver bundle + kernel-module source (frozen target) | archive/notes_and_stuff/GNA | driver zips + gna2-*.h |

What does NOT exist: live microphone capture, VAD/wake trip, streaming (vs file-batch)
framing, ANY output path (voice head, vocoder), and GUI integration.
One constraint to respect: **WSL2 has no GNA MMIO passthrough** — GNA_HW runs native
Windows (WSL was only ever the CPU-emulation leg). The live pipeline is Windows-native.

## 1. Corrections to the Gemini brief (keep the direction, fix the mechanism)

1. **"Train a lightweight GNA acoustic extractor"** — already trained, quantized, and
   running on the silicon (§0). The work is *streaming* it, not building it.
2. **"1024-d latent manifold"** — the served 12B's hidden is **E = 3840**
   (arch: 48L/3840H, OKFS 55e022c6). Injection is at the residual seam, not 1024-d.
3. **"Gemma4 9B voice pathway"** (operator) — our serve is the **12B**; its voice
   channel is the audio-placeholder token **258881** + `inject_frames`. No 9B exists in
   our stack; everything below targets the 12B we actually serve (and the E2B for
   cheap experiments, as in KAI-1/2).
4. **GNA "GAN for cheap"** — right instinct, sharpened: the GNA is inference-only,
   INT16/INT8, conv/affine-only, **no transposed conv, no padding, out-channels ÷4**
   (GNA_HW_BRINGUP receipts). A vocoder CAN be shaped for it (§4), but that is a
   *gated experiment*, not an assumption. The deprecated-silicon point stands and is
   real leverage: the target is frozen, our driver bundle is archived, nothing
   changes underneath us.
5. **"NV-Whisper is heavy, GPU-bound"** — agreed, and we already beat it: our ear runs
   on the GNA at ~zero CPU/GPU cost. Additional NUC asset Gemini missed: the **iGPU
   (UHD, Level-Zero)** — our voxtral crate already has a zero-copy L0 backend. The
   compute map is: GNA = always-on ear + wake; iGPU = optional heavier audio nets;
   CPU = vocoder v0; **2060 stays 100% Gemma's**.
6. **"HiFi-GAN stripped down"** — v0 vocoder runs on CPU (int8 conv1d stack is
   trivially realtime at 16k); the GNA port replaces transposed-conv upsampling with
   nearest-neighbor-repeat + conv (GNA-legal) and must pass a POT i16 recovery gate
   like the ear did. Do not promise GNA vocoding until G-VOICE-4 is green.

## 2. Audex-2B/30B teardown (arXiv 2607.05196) — steal / reject, with receipts

**Architecture** (paper + HF card): single Transformer decoder; audio INPUT encoded +
projected into the text embedding space (continuous); audio OUTPUT as **discrete
codec tokens** (XCodec1/XCodec2) extending the vocabulary, generated uniformly with
text; streaming TTS via a separate **"Audex causal speech decoder"**; trained on
157.4B audio + 320.5B text tokens; thinking/instruct modes; `<sound>` placeholder.

**STEAL:**
- **The unified-input validation.** Their input side IS our inject_frames seam —
  continuous projection into the embedding manifold, one KV cache, one decoder. We
  had it gated before the paper existed. Confidence, not homework.
- **The two-stage output split.** Even NVIDIA does not make the LLM emit waveforms:
  the LLM emits a compact acoustic stream, a small *causal/streaming* decoder renders
  audio. That is exactly our Voice Head → GAN split. Their "streaming decoder trades
  a little quality for latency vs full XCodec2" note tells us the latency budget is
  won at the decoder, not the LLM.
- **The `<sound>` placeholder + template discipline** — mirrors our 258881 channel;
  their thinking/instruct duality maps to our reason model's modes.
- **Task framing for training data** (ASR/TTS/S2S prompt formats) — reusable when we
  scale the ear vocab and train the voice head.

**REJECT:**
- **Discrete audio-token OUTPUT through the text softmax.** A 262k→+audio vocab
  extension, RVQ codebooks, and token-rate decode on the 2060 is the tokenization tax
  we exist to avoid. Our output leaves the model as a CONTINUOUS conditioning vector
  read from the hidden state (the Voice Head is a Tier-1 style head, ADR-002) — no
  vocabulary surgery on the served 12B, no retraining of the backbone.
- **Their encoder economics.** 157B-token training runs are not our lane; our ear is
  a 2.4MB CTC projector that a NUC trained overnight. We scale ITS vocab (V_sub
  32 → few hundred), not adopt theirs.
- **GPU-resident audio I/O.** GNA+iGPU+CPU own audio; the 2060 never sees a sample.

## 3. Target architecture (the whole loop)

```
                      ┌─ Windows native ────────────────────────────────┐
 mic 16k mono ──► ring buffer ──► VAD (energy v0 / GNA v1)              │
        │                           │ trip (any-voice or "Hey Shannon") │
        │                           ▼                                   │
        │              log-mel 64 @40ms (rustfft/np)                    │
        │                           ▼                                   │
        │              GNA_HW i16 CTC encoder (OV 2023.3)  ◄─ FROZEN    │
        │                           ▼                                   │
        │              CTC-greedy → softmax(τ)·W_sub → [k×E] frames     │
        └──────────────────────────────────────────────┐                │
                                                        ▼               │
   gateway /v1/voice (session transcript, spine)  ──► daemon /v1/chat   │
                                                   inject_frames, 258881│
                                                        ▼               │
                                            12B resident KV (persist)   │
                                                        ▼               │
                    ┌─────────── output, phased ────────┴─────────┐     │
                    │ v0: streamed text → browser TTS (stopgap)   │     │
                    │ v1: streamed text → OUR vocoder (CPU GAN)   │     │
                    │ v2: VOICE HEAD reads hidden state → acoustic│     │
                    │     conditioning [T×C] → GAN vocoder → PCM  │     │
                    │     (text bypassed; text still logged)      │     │
                    │ v3: vocoder POT i16 → GNA (G-VOICE-4)       │     │
                    └──────────────────────────────────────────────┘    │
```

Voice Head (v2, the latent leap): a small trained head mapping decode-time hidden
states → mel/conditioning frames. Training data comes free from our own loop: run the
12B on text, render the SAME text with our TTS (voxtral flow-matching / v1 vocoder),
pair (hidden-state sequence, mel sequence), train the head like KAI-3 in reverse
(CTC's alignment-free trick has an output twin: attention-free monotonic aligner or
simple duration-regulated upsampling). Interruption = VAD trip during playback →
abort decode + duck output (the sessioned gateway already owns the turn).

## 4. The GNA-GAN (v3) — honest constraints

GNA 2.0 legal set (proven by our own bring-up): Conv1d/affine, ReLU-family PWL, no
padding, out-channels ÷4, INT16 weights/activations via POT, small internal buffers.
A melGAN-class generator reshaped to that set: NN-repeat upsampling (×2 stages) +
valid convs + PWL activations; receptive-field trimmed; POT-calibrated per stage.
Gate = spectral/MOS-proxy recovery vs the FP32 twin ≥ 0.9 AND realtime factor < 0.5
on GNA_HW. If GNA buffers can't hold the upsample stages, the fallback stands: GNA
runs the ear + wake FOREVER-CHEAP, CPU runs the vocoder (still zero 2060 cost).

## 5. What we reuse from our own shelf

voxtral-mini-realtime-rs (ours): `hound`/`rubato`/`rustfft` DSP, `ring_buffer.rs`
streaming, L0 iGPU backend, and the flow-matching TTS as the v1 acoustic teacher for
voice-head training data. The GNA archive driver bundle is the frozen target. The
kai3 OV toolchain (`ov2023_win`, POT scripts) is the quantization lane. Browser
WebAudio (console) is the capture surface — the same origin the console already owns.

## 6. Phases

- **P0 (this session): the loop exists.** Console voice channel (toggle, mic capture,
  VAD meter, push-to-talk + auto-trip), gateway `/v1/voice` (PCM in → mel → projector
  → inject_frames → streamed reply), browser-TTS output stopgap, wake-word toggle
  stub. Ear content limited to the trained V_sub — that's fine, P0 gates plumbing.
- **P1: the ear grows up.** Scale V_sub 32 → 512 (multi-voice TTS corpus render via
  our own crate), retrain, POT, re-gate on GNA_HW. Wake-word head ("Hey Shannon") as
  a second tiny output on the same encoder. Free speech becomes genuinely legible.
- **P2: our voice out (text-conditioned).** CPU GAN vocoder (mel→PCM, int8) + a text→mel
  front (or the voxtral flow-matching TTS quantized) replaces browser TTS. Streaming
  chunks, interruption ducking.
- **P3: the latent leap.** Voice Head: hidden→conditioning, trained on self-generated
  pairs; decode streams conditioning frames to the vocoder; text generation becomes a
  logging side-channel, not the audio path.
- **P4: GNA vocoder port** (§4 gate) + always-on wake on GNA (mic never sleeps, ~0W).

## 7. Gates

| gate | proves |
|---|---|
| G-VOICE-0 | mic→VAD→mel→projector→inject_frames→12B reply, live, end-to-end through the console; PLUS parity: the live framing path reproduces a KAI-3 packet bit-close (same wav → cos>0.999 vs aud_NN.bin) |
| G-VOICE-1 | V_sub-512 ear: held-out CTC ≥0.85 + GNA_HW POT recovery ≥ FP32−0.02 + live paraphrase understanding |
| G-VOICE-WAKE | "Hey Shannon" head: ≥95% trip, <1 false-trip/hour on room noise, on GNA_HW |
| G-VOICE-2 | our vocoder realtime on CPU: RTF<0.3, MOS-proxy vs teacher ≥0.9, streaming chunk latency <150ms |
| G-VOICE-3 | voice head: hidden→conditioning→audio intelligible (WER-proxy vs spoken text ≤1.5× the text-TTS path) — the text-bypass gate |
| G-VOICE-4 | GNA vocoder: POT recovery + RTF on silicon |
| G-VOICE-LIVE | operator conversation: interrupt mid-reply, wake from cold, 3-turn voice chat, no keyboard |

## 7.5 P1.5 — live-play findings (2026-07-11 operator voice session)

First real-microphone conversation surfaced four things the synthetic gates could
not:

1. **Real-mic speech is OUT OF DISTRIBUTION for the SAPI-trained ear.** The ear
   scored 0.796 on held-out SAPI sentences but confabulates on live mic input
   (invented a gaming backstory, a different GPU spec each turn, mic-troubleshoot
   patter) — mostly-blank CTC output + a few random tokens → the 12B free-
   associates. FIX (P1.5): waveform **acoustic augmentation** (reverb, mic-EQ
   tilt, colored noise at random SNR, gain/clip) in voice_frames (--aug_copies)
   so the SAPI corpus better matches live capture; retrain. TRUE fix (P1.6) =
   real-speech data — the console should offer a **speak → see transcript →
   correct → becomes a training pair** loop (self-improving ear, the CosySim
   pattern). Bank it.
2. **AudioContext sample-rate mismatch** (the "getting out of sync"): the browser
   often runs the context at 48k even when 16k is requested; the ear is trained
   strictly on 16k, so the audio is time-warped. FIX: console resamples the
   captured utterance to EXACTLY 16k before send.
3. **Replies truncated mid-sentence.** Voice max_tokens 96 → 256; console sends
   256. (Chat path already 512.)
4. **Control-token leakage on the injected-frame path** (`<0x0D>`, stray ```` ``` ````,
   `[audio]`). FIX: voice service strips them from the stream; a graceful-framing
   system note tells the model to answer what it can make out and ASK rather than
   invent when the audio is unclear.

**★ ROLEPLAY (bank for later — a genuine emergent strength).** The 12B runs
scenario roleplay beautifully UNPROMPTED ("The Cosmic Adventure: Journey to Alpha
Centauri", coherent multi-turn GM). This is a natural harness feature: a
`roleplay`/`scenario` mode (spine decider + a scene-state memory tier, mirroring
CosySim's scenario engine) that formalizes what the model already does well —
scene setup, character state, turn structure, an exit verb. NOT built now;
tracked as a KAI/harness backlog item so it is not lost. Do NOT over-engineer:
the model's unprompted quality is the bar; the harness should scaffold
persistence + structure, not replace the model's improvisation.

## 8. Decision (answers Gemini's closing question)

Input first — because it is already built. P0 wires the PROVEN ear to a microphone
and the console; that alone delivers "talk to Shannon". Output rides the stopgap →
own-vocoder → latent-head ladder, each rung gated, so voice chat WORKS at every
phase while the text-bypass leap is earned rather than assumed.
