# telepathy_audio — Voice-Head PoC (ADR-KAI5, audio-OUT LatentBridge)

**Goal:** answer one question offline — *can Shannon's hidden state `h_t` drive an audio decoder's continuous latent?* i.e. can the 12B speak from latent space with no discrete tokens, as a `LatentBridge{src: shannon-hidden, dst: audio-decoder}`.

**Safety (why this can't touch the working system):**
- Everything here is **offline** and **process-isolated**. Nothing is wired into the served daemon.
- The Voice-Head is a *read tap* on Shannon + a write to an *external* decoder. It never writes the 12B residual (unlike audio-IN). The byte-exact forward is untouched.
- Default-off: no `LatentBridge` is registered until P1, and then only under `SP_VOICEHEAD` + a valid license (fail-closed), per the Telepathy spec.

## Pipeline (per ADR-KAI5 §6)

```
1. distill_pairs.py   text --> [served 12B, read tap] --> h_t sequence   (deterministic, byte-exact)
                      text --> [voxtral-rs TTS] --> wav --> [Mimi encode] --> mimi_latent_t  (512-d @12.5Hz)
                      time-align --> pairs.npz  {h:[T,3840], z:[T,512]}
2. fit_voicehead.py   warm-start linear (h->z) then zero-init residual-MLP; consistency/flow loss
                      (TELE-10b recipe: low lr, warm-start; NOT cosine). --> voicehead.npz
3. decode_voicehead.py  h --> B_out --> z_hat --> [Mimi decoder] --> wav ; report intelligibility
```

## Status of each stage

- `fit_voicehead.py` — **runnable now.** Trains linear + residual-MLP on any `pairs.npz`, and has a `--selftest` that fabricates a known random map so you can verify the training/roundtrip plumbing with zero external deps.
- `distill_pairs.py` — **hooks marked TODO.** Needs (a) a hidden-state read tap on the served 12B (the ONE new wiring — a read-only `/v1/hidden` or an L1 forward dump), (b) voxtral-rs TTS invocation, (c) Mimi encode. Ships a `--synthetic` generator so the rest of the pipeline is testable today.
- `decode_voicehead.py` — applies the fitted head; Mimi-decodes if `moshi`/`mimi` is importable, else writes `z_hat` for external decoding.

## The one real dependency to wire (P1, not here)

A **read-only hidden-state tap** on Shannon at layer `L`. This is non-destructive and does not alter the forward. Candidates: a debug `/v1/hidden` route that returns the per-position residual, or an L1 forward that dumps `h`. Until that exists, use `--synthetic` to validate plumbing.

## Gates targeted (ADR-KAI5 §8)

`G-VOICEHEAD-PARITY` (off=null floor), `G-VOICEHEAD-ROUNDTRIP` (intelligible + speaker-consistent), `G-VOICEHEAD-REJECT`, `G-ADAPTER-CONFORM`.
