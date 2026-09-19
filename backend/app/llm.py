"""The Anthropic layer: model routing, prompt assembly, caching and cost.

Two models are in play. Deep strategic work (brand heart, positioning, the
13-module plan, every review) runs on Opus; fast generative work (hooks, copy
variants, short answers) runs on Sonnet. A module declares its tier; the
caller may override it per run.

Prompt layout is deliberate, because prompt caching is a prefix match and any
byte that moves invalidates everything behind it:

    system[0] = the skill text          -- stable per module, cached
    system[1] = operating rules + brand -- stable per brand, cached
    messages  = the request itself      -- volatile, never cached

That ordering is what makes a second run against the same brand cheap.
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import anthropic

from .config import settings

log = logging.getLogger(__name__)

# USD per million tokens, from the Anthropic pricing table.
PRICING: dict[str, tuple[float, float]] = {
    "claude-opus-5": (5.00, 25.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-haiku-4-5": (1.00, 5.00),
}
CACHE_READ_MULTIPLIER = 0.10
CACHE_WRITE_MULTIPLIER = 1.25

FALLBACK_BETA = "server-side-fallback-2026-07-01"

# Set to False for the process lifetime if the account cannot use the beta,
# so one rejection does not cost every later request a failed round trip.
_fallback_supported = True

_client: anthropic.AsyncAnthropic | None = None


def client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        if not settings.anthropic_api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set — the dashboard cannot generate anything without it."
            )
        _client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key, timeout=900.0)
    return _client


def model_for(tier: str, override: str | None = None) -> str:
    if override in PRICING:
        return override
    return settings.model_fast if tier == "fast" else settings.model_deep


@dataclass
class Usage:
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    def add(self, other: Usage) -> None:
        self.model = other.model or self.model
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cache_read_tokens += other.cache_read_tokens
        self.cache_write_tokens += other.cache_write_tokens

    @property
    def cost_usd(self) -> float:
        rate_in, rate_out = PRICING.get(self.model, PRICING["claude-opus-5"])
        return (
            self.input_tokens * rate_in
            + self.cache_read_tokens * rate_in * CACHE_READ_MULTIPLIER
            + self.cache_write_tokens * rate_in * CACHE_WRITE_MULTIPLIER
            + self.output_tokens * rate_out
        ) / 1_000_000


@dataclass
class Chunk:
    """One streamed event, normalised for the SSE transport."""

    kind: str  # text | thinking | usage | error
    text: str = ""
    usage: Usage | None = None


@dataclass
class Request:
    skill_text: str
    context_text: str
    task: str
    model: str
    effort: str = "high"
    max_tokens: int = 32000
    images: list[tuple[str, str]] = field(default_factory=list)  # (media_type, base64)
    image_labels: list[str] = field(default_factory=list)
    prior: list[dict[str, Any]] = field(default_factory=list)

    def build(self) -> dict[str, Any]:
        system = [
            {"type": "text", "text": self.skill_text, "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": self.context_text, "cache_control": {"type": "ephemeral"}},
        ]

        content: list[dict[str, Any]] = []
        for index, (media_type, data) in enumerate(self.images):
            if index < len(self.image_labels):
                content.append({"type": "text", "text": self.image_labels[index]})
            content.append(
                {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}}
            )
        content.append({"type": "text", "text": self.task})

        return {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": system,
            "messages": [*self.prior, {"role": "user", "content": content}],
            "thinking": {"type": "adaptive", "display": "summarized"},
            "output_config": {"effort": self.effort},
        }


def _usage_from(message: Any, model: str) -> Usage:
    raw = getattr(message, "usage", None)
    if raw is None:
        return Usage(model=model)
    return Usage(
        model=getattr(message, "model", model) or model,
        input_tokens=getattr(raw, "input_tokens", 0) or 0,
        output_tokens=getattr(raw, "output_tokens", 0) or 0,
        cache_read_tokens=getattr(raw, "cache_read_input_tokens", 0) or 0,
        cache_write_tokens=getattr(raw, "cache_creation_input_tokens", 0) or 0,
    )


async def stream(request: Request) -> AsyncIterator[Chunk]:
    """Stream one completion, yielding text, reasoning summaries, then usage."""
    global _fallback_supported

    params = request.build()
    use_fallback = settings.enable_refusal_fallback and _fallback_supported

    while True:
        try:
            if use_fallback:
                manager = client().beta.messages.stream(
                    **params, betas=[FALLBACK_BETA], fallbacks="default"
                )
            else:
                manager = client().messages.stream(**params)

            async with manager as events:
                async for event in events:
                    if event.type != "content_block_delta":
                        continue
                    if event.delta.type == "text_delta":
                        yield Chunk("text", event.delta.text)
                    elif event.delta.type == "thinking_delta":
                        yield Chunk("thinking", event.delta.thinking)
                final = await events.get_final_message()

            if getattr(final, "stop_reason", None) == "refusal":
                detail = getattr(getattr(final, "stop_details", None), "explanation", "")
                yield Chunk("error", f"الموديل رفض تنفيذ الطلب. {detail}".strip())
                return

            yield Chunk("usage", usage=_usage_from(final, request.model))
            return

        except anthropic.BadRequestError as exc:
            # The account may not carry the fallback beta; that is not fatal.
            message = str(exc).lower()
            if use_fallback and ("fallback" in message or "beta" in message):
                log.warning("refusal fallback unavailable, continuing without it: %s", exc)
                _fallback_supported = False
                use_fallback = False
                continue
            raise
