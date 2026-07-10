"""
Inference Configuration
========================

Backend-agnostic generation parameters and their projection onto the
Shannon-Prime ``sp-daemon`` ``POST /v1/chat`` request schema.

This is the single place that knows what knobs exist. Clients, the router and
the orchestrator all pass an :class:`InferenceConfig` and never hand-build
backend payloads.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


# ──── Config ──────────────────────────────────────────────────────────────
@dataclass
class InferenceConfig:
    """Unified, backend-agnostic generation config.

    Every field maps cleanly onto the sp-daemon ``/v1/chat`` schema via
    :meth:`to_sp_chat`. Unset (``None``) fields are omitted so the daemon's
    own defaults apply.
    """

    # Sampling
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    repetition_penalty: Optional[float] = None
    frequency_penalty: Optional[float] = None
    seed: Optional[int] = None
    max_tokens: Optional[int] = 512
    stop: Optional[List[str]] = None

    # Shannon-Prime native knobs (the levers LMStudio never had)
    byteexact: Optional[bool] = None        # exact-integer islands, bit-deterministic
    raw_logits: Optional[bool] = None       # disable control-token suppression (null floor)
    auto_recall: Optional[bool] = None      # autonomous W_c episodic recall head
    replay: Optional[str] = None            # explicit episode dir to replay
    replay_npos: Optional[int] = None
    single_entry: Optional[bool] = None     # route text via residual seam
    eot_bias: Optional[float] = None        # logit bias on stop tokens so the model STOPS cleanly
                                            # (without this the gateway path never terminates)

    # Routing / model selection (harness-side, not sent to daemon)
    model: Optional[str] = None

    def to_sp_chat(
        self,
        *,
        prompt: Optional[str] = None,
        messages: Optional[List[Dict[str, Any]]] = None,
        prompt_tokens: Optional[List[int]] = None,
    ) -> Dict[str, Any]:
        """Build the sp-daemon ``/v1/chat`` request body.

        Exactly one of ``prompt`` / ``messages`` / ``prompt_tokens`` must be
        supplied (the daemon enforces this).
        """
        body: Dict[str, Any] = {}
        if prompt is not None:
            body["prompt"] = prompt
        if messages is not None:
            body["messages"] = messages
        if prompt_tokens is not None:
            body["prompt_tokens"] = prompt_tokens

        for k in (
            "temperature", "top_p", "top_k", "repetition_penalty",
            "frequency_penalty", "seed", "max_tokens",
            "byteexact", "raw_logits", "auto_recall",
            "replay", "replay_npos", "single_entry", "eot_bias",
        ):
            v = getattr(self, k)
            if v is not None:
                body[k] = v
        if self.stop:
            body["stop"] = self.stop
        return body

    @classmethod
    def merge(cls, base: "InferenceConfig", override: "InferenceConfig") -> "InferenceConfig":
        """Return a new config where non-``None`` override fields win."""
        merged = asdict(base)
        for k, v in asdict(override).items():
            if v is not None:
                merged[k] = v
        return cls(**merged)
