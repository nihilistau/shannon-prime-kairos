"""
Shannon-Prime Daemon Client
===========================

The harness's replacement for the LMStudio REST/SDK client. Talks to the
Shannon-Prime universal resident daemon (``sp-daemon``) over HTTP:

    POST /v1/chat        — SSE token stream  (one ``{"delta": ...}`` per token)
    POST /v1/abort/{id}  — cancel an in-flight generation
    GET  /v1/metrics     — tokens/sec, session position, phase
    GET  /v1/debug/backend_counts — which wire backend is live

The daemon stream is Shannon-Prime native (NOT OpenAI ``/v1/chat/completions``).
This client adapts it into the harness's :class:`StreamEvent` shape, which the
:class:`~harness.inference.stream_processor.StreamProcessor` then mines for
inline tags. The OpenAI-compatible surface lives one layer up in
``harness.server`` so external callers get a familiar API while the daemon stays
native.

Launch reference (the daemon this client targets)::

    sp-daemon start --model gemma4-12b-b1.sp-model \\
        --tokenizer gemma4-12b-b1.sp-tokenizer --port 3000
    # env: SP_DAEMON_BACKEND=cuda SP_DAEMON_KVDECODE=1 SP_CUDA_DECODE_INT8=1
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Generator, List, Optional

from harness.inference.inference_config import InferenceConfig

logger = logging.getLogger(__name__)

try:  # httpx is the preferred transport; degrade gracefully if absent
    import httpx
except Exception:  # pragma: no cover - import guard
    httpx = None  # type: ignore


DEFAULT_DAEMON_URL = "http://127.0.0.1:3000"


# ──── Event / response shapes ─────────────────────────────────────────────
@dataclass
class StreamEvent:
    """One normalized streaming event.

    The sp-daemon only emits ``delta`` token events plus a terminal ``[DONE]``;
    this dataclass keeps the richer LMStudio-style event surface so downstream
    processors (and the SSE server) don't need to change when the backend's
    event vocabulary grows (tool calls, reasoning deltas, etc.).
    """

    event_type: str            # "message.delta" | "message.end" | "chat.start" | "error"
    content: str = ""
    chat_id: Optional[int] = None
    error: Optional[Dict[str, Any]] = None
    stats: Dict[str, Any] = field(default_factory=dict)
    is_done: bool = False


@dataclass
class InferenceResponse:
    """Aggregated result of a completed generation."""

    text: str = ""
    chat_id: Optional[int] = None
    model: str = ""
    finish_reason: str = "stop"
    stats: Dict[str, Any] = field(default_factory=dict)


# ──── Client ──────────────────────────────────────────────────────────────
class SPDaemonClient:
    """Thin HTTP client over the Shannon-Prime daemon.

    CONNECTS: InferenceConfig, StreamProcessor
    CALLED BY: InferenceRouter, InferenceOrchestrator, tool-calling loop, SSE server
    EMITS: StreamEvent stream
    """

    def __init__(
        self,
        base_url: str = DEFAULT_DAEMON_URL,
        timeout: float = 300.0,
        default_model: str = "",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.default_model = default_model
        self._client = httpx.Client(timeout=timeout) if httpx else None

    # ---- core: streaming chat -------------------------------------------
    def chat_stream(
        self,
        *,
        prompt: Optional[str] = None,
        messages: Optional[List[Dict[str, Any]]] = None,
        prompt_tokens: Optional[List[int]] = None,
        config: Optional[InferenceConfig] = None,
        on_event: Optional[Callable[[StreamEvent], None]] = None,
    ) -> Generator[str, None, InferenceResponse]:
        """Stream tokens from ``POST /v1/chat``.

        Yields the text delta of each token; returns the aggregated
        :class:`InferenceResponse` when the stream closes. ``on_event`` (if
        given) receives the normalized :class:`StreamEvent` for each line.
        """
        if self._client is None:
            raise RuntimeError("httpx is required for SPDaemonClient (pip install httpx)")

        cfg = config or InferenceConfig()
        body = cfg.to_sp_chat(prompt=prompt, messages=messages, prompt_tokens=prompt_tokens)
        logger.info("[SPDaemonClient] -> daemon: keys=%s eot_bias=%s max_tokens=%s temp=%s rep=%s msgs=%d",
                    sorted(body.keys()), body.get("eot_bias"), body.get("max_tokens"),
                    body.get("temperature"), body.get("repetition_penalty"),
                    len(body.get("messages") or []))

        text_parts: List[str] = []
        chat_id: Optional[int] = None
        resp = InferenceResponse(model=cfg.model or self.default_model)

        if on_event:
            on_event(StreamEvent("chat.start"))

        url = f"{self.base_url}/v1/chat"
        try:
            with self._client.stream("POST", url, json=body) as stream:
                stream.raise_for_status()
                for line in stream.iter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    payload = line[len("data:"):].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        evt = json.loads(payload)
                    except json.JSONDecodeError:
                        logger.warning("[SPDaemonClient] bad SSE line (operation=parse): %s", payload[:120])
                        continue
                    delta = evt.get("delta", "")
                    if chat_id is None:
                        chat_id = evt.get("chat_id")
                    if delta:
                        text_parts.append(delta)
                        if on_event:
                            on_event(StreamEvent("message.delta", content=delta, chat_id=chat_id))
                        yield delta
        except Exception as exc:  # surface, do not swallow (Oracle convention)
            logger.error("[SPDaemonClient] stream failed (operation=chat): %s", exc)
            if on_event:
                on_event(StreamEvent("error", error={"message": str(exc)}, is_done=True))
            raise

        resp.text = "".join(text_parts)
        resp.chat_id = chat_id
        if on_event:
            on_event(StreamEvent("message.end", chat_id=chat_id, is_done=True))
        return resp

    # ---- convenience: blocking chat -------------------------------------
    def chat(
        self,
        *,
        prompt: Optional[str] = None,
        messages: Optional[List[Dict[str, Any]]] = None,
        config: Optional[InferenceConfig] = None,
    ) -> InferenceResponse:
        """Run a generation to completion and return the aggregated response."""
        gen = self.chat_stream(prompt=prompt, messages=messages, config=config)
        try:
            while True:
                next(gen)
        except StopIteration as stop:
            return stop.value  # type: ignore[return-value]

    # ---- control / health -----------------------------------------------
    def abort(self, chat_id: int) -> bool:
        """Cancel a running generation. Returns True on 204."""
        if self._client is None:
            return False
        try:
            r = self._client.post(f"{self.base_url}/v1/abort/{chat_id}")
            return r.status_code == 204
        except Exception as exc:
            logger.error("[SPDaemonClient] abort failed (operation=abort, id=%s): %s", chat_id, exc)
            return False

    def metrics(self) -> Dict[str, Any]:
        """Return ``GET /v1/metrics`` (tokens_per_sec, session_pos, phase)."""
        if self._client is None:
            return {}
        try:
            return self._client.get(f"{self.base_url}/v1/metrics").json()
        except Exception as exc:
            logger.error("[SPDaemonClient] metrics failed (operation=metrics): %s", exc)
            return {}

    def health(self) -> bool:
        """True if the daemon answers ``/v1/metrics``."""
        return bool(self.metrics())

    def backend_counts(self) -> Dict[str, Any]:
        """Return wire-backend dispatch counters (diagnostic)."""
        if self._client is None:
            return {}
        try:
            return self._client.get(f"{self.base_url}/v1/debug/backend_counts").json()
        except Exception:
            return {}

    # ---- daemon-wide event stream (LM-B2 SSE telemetry sink) -------------
    def subscribe_events(
        self,
        *,
        want: Optional[List[str]] = None,
        timeout: Optional[float] = None,
    ) -> Generator[StreamEvent, None, None]:
        """Subscribe to the daemon-wide ``GET /v1/events`` SSE bus and yield each
        event as a :class:`StreamEvent` (``event_type`` = the SSE ``event:`` name,
        ``content`` = the raw ``data:`` payload). This is a LONG-LIVED stream
        (chat lifecycle + PoUW mints + LM-B2 ``telemetry`` records), distinct from
        the per-request ``chat_stream``. ``want`` filters to the given event names
        (e.g. ``["telemetry"]``); ``None`` yields all. The telemetry payload is
        already class-redacted by the engine — the harness only sinks it.
        """
        if self._client is None:
            raise RuntimeError("httpx is required for SPDaemonClient (pip install httpx)")
        url = f"{self.base_url}/v1/events"
        # /v1/events is unbounded — do not inherit the chat timeout.
        client = httpx.Client(timeout=timeout) if timeout is not None else \
            httpx.Client(timeout=httpx.Timeout(None))
        try:
            with client.stream("GET", url) as stream:
                stream.raise_for_status()
                ev_name: Optional[str] = None
                for line in stream.iter_lines():
                    if line.startswith("event:"):
                        ev_name = line[len("event:"):].strip()
                    elif line.startswith("data:"):
                        data = line[len("data:"):].strip()
                        if data == "keepalive" or data == "[DONE]":
                            continue
                        name = ev_name or "message"
                        if want is None or name in want:
                            yield StreamEvent(name, content=data)
                        ev_name = None
                    elif line == "":
                        ev_name = None
        except Exception as exc:  # surface, do not swallow (Oracle convention)
            logger.error("[SPDaemonClient] events stream failed (operation=events): %s", exc)
            raise
        finally:
            client.close()


# ──── Singleton ───────────────────────────────────────────────────────────
_CLIENT: Optional[SPDaemonClient] = None


def get_client(base_url: Optional[str] = None) -> SPDaemonClient:
    """Return the process-wide daemon client singleton."""
    global _CLIENT
    if _CLIENT is None or (base_url and base_url != _CLIENT.base_url):
        _CLIENT = SPDaemonClient(base_url or DEFAULT_DAEMON_URL)
    return _CLIENT
