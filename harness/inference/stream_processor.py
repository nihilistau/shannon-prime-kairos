"""
Stream Processor
================

Mines inline control tags out of a token stream and exposes a clean text
channel plus structured side-effects. Ported from CosySim's StreamProcessor;
backend-agnostic — it consumes :class:`~harness.inference.client.StreamEvent`
objects from any source (the sp-daemon, a tool loop, a replayed transcript).

Inline tags::

    [MOOD:happy]            -> mood_tags
    [IMAGE:a red door]      -> image_requests
    [ACTION:sit down]       -> action_tags
    [STAT:arousal+10]       -> stat_deltas
    [VOICE:whisper]         -> voice_style
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Generator, List, Optional, Tuple

from harness.inference.client import StreamEvent


# ──── Patterns ────────────────────────────────────────────────────────────
_PATTERNS: Dict[str, re.Pattern] = {
    "mood": re.compile(r"\[MOOD:([^\]]+)\]"),
    "image": re.compile(r"\[(?:IMAGE|SELFIE|PHOTO):([^\]]+)\]"),
    "action": re.compile(r"\[ACTION:([^\]]+)\]"),
    "stat": re.compile(r"\[STAT:([a-zA-Z_]+)([+-]\d+(?:\.\d+)?)\]"),
    "voice": re.compile(r"\[VOICE:([^\]]+)\]"),
    "trait": re.compile(r"\[TRAIT:([^\]]+)\]"),  # PF-B3: self-modify a personality trait
}
_STRIP = re.compile(r"\[(?:MOOD|IMAGE|SELFIE|PHOTO|ACTION|STAT|VOICE|TRAIT):[^\]]+\]")


@dataclass
class StatDelta:
    stat: str
    delta: float


@dataclass
class ProcessedResponse:
    raw_text: str = ""
    clean_text: str = ""
    mood_tags: List[str] = field(default_factory=list)
    image_requests: List[str] = field(default_factory=list)
    action_tags: List[str] = field(default_factory=list)
    stat_deltas: List[StatDelta] = field(default_factory=list)
    voice_style: str = ""
    all_tags: Dict[str, List[str]] = field(default_factory=dict)
    chat_id: Optional[int] = None
    stats: Dict[str, Any] = field(default_factory=dict)


# ──── Processor ───────────────────────────────────────────────────────────
class StreamProcessor:
    """Accumulate a stream and extract tags.

    CALLED BY: scene/agent reply paths, the SSE server, the CLI coder.
    EMITS: per-tag callbacks + a final ProcessedResponse.
    """

    def __init__(
        self,
        on_delta: Optional[Callable[[str], None]] = None,
        on_mood: Optional[Callable[[str], None]] = None,
        on_image_request: Optional[Callable[[str], None]] = None,
        on_action: Optional[Callable[[str], None]] = None,
        on_stat_delta: Optional[Callable[[StatDelta], None]] = None,
        on_tag: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        self.on_delta = on_delta
        self.on_mood = on_mood
        self.on_image_request = on_image_request
        self.on_action = on_action
        self.on_stat_delta = on_stat_delta
        self.on_tag = on_tag
        self._result = ProcessedResponse()
        self._buf = ""

    def on_event(self, event: StreamEvent) -> None:
        if event.event_type == "message.delta":
            self._buf += event.content
            self._result.chat_id = event.chat_id
            if self.on_delta:
                self.on_delta(event.content)
        elif event.event_type == "message.end":
            self._finalize()
            self._result.stats = event.stats

    def _finalize(self) -> None:
        text = self._buf
        self._result.raw_text = text
        for kind, pat in _PATTERNS.items():
            for m in pat.finditer(text):
                if kind == "mood":
                    val = m.group(1)
                    self._result.mood_tags.append(val)
                    self._result.all_tags.setdefault("mood", []).append(val)
                    if self.on_mood:
                        self.on_mood(val)
                elif kind == "image":
                    val = m.group(1)
                    self._result.image_requests.append(val)
                    if self.on_image_request:
                        self.on_image_request(val)
                elif kind == "action":
                    val = m.group(1)
                    self._result.action_tags.append(val)
                    if self.on_action:
                        self.on_action(val)
                elif kind == "stat":
                    sd = StatDelta(m.group(1), float(m.group(2)))
                    self._result.stat_deltas.append(sd)
                    if self.on_stat_delta:
                        self.on_stat_delta(sd)
                elif kind == "voice":
                    self._result.voice_style = m.group(1)
                if self.on_tag:
                    self.on_tag(kind, m.group(0))
        self._result.clean_text = _STRIP.sub("", text).strip()

    @property
    def result(self) -> ProcessedResponse:
        if not self._result.raw_text and self._buf:
            self._finalize()
        return self._result

    @staticmethod
    def process_generator(
        gen: Generator[str, None, Any],
        **callbacks: Any,
    ) -> ProcessedResponse:
        """Drain a ``chat_stream`` generator into a ProcessedResponse."""
        proc = StreamProcessor(**callbacks)
        for delta in gen:
            proc.on_event(StreamEvent("message.delta", content=delta))
        proc.on_event(StreamEvent("message.end"))
        return proc.result
