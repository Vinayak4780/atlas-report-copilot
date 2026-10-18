"""Groq chat wrapper with a per-request token budget, deadline-aware timeouts, model fallback
and cost accounting."""
from __future__ import annotations

import logging
import time

from app.config import Settings
from app.domain import TokenUsage
from app.logging_setup import log_event

logger = logging.getLogger(__name__)

# USD per 1M tokens (input, output). Groq on-demand list prices.
PRICING = {
    "llama-3.3-70b-versatile": (0.59, 0.79),
    "llama-3.1-8b-instant": (0.05, 0.08),
}


class LLMUnavailable(RuntimeError):
    """Raised when no model could answer (missing key, rate limit, timeout, budget)."""


class RequestBudget:
    """Token cap + wall-clock deadline for one /chat request."""

    def __init__(self, max_tokens: int, deadline: float):
        self.max_tokens = max_tokens
        self.deadline = deadline
        self.usage = TokenUsage()

    @property
    def remaining_tokens(self) -> int:
        return self.max_tokens - self.usage.prompt_tokens - self.usage.completion_tokens

    @property
    def remaining_seconds(self) -> float:
        return self.deadline - time.monotonic()

    def add(self, model: str, prompt: int, completion: int, purpose: str, ms: int) -> None:
        price_in, price_out = PRICING.get(model, (0.0, 0.0))
        cost = (prompt * price_in + completion * price_out) / 1_000_000
        self.usage.prompt_tokens += prompt
        self.usage.completion_tokens += completion
        self.usage.cost_usd += cost
        self.usage.calls.append({"purpose": purpose, "model": model, "prompt_tokens": prompt,
                                 "completion_tokens": completion, "cost_usd": round(cost, 6), "ms": ms})


class LLMClient:
    def __init__(self, settings: Settings):
        self.s = settings
        self.enabled = bool(settings.groq_api_key)
        self._client = None
        if self.enabled:
            from groq import Groq

            self._client = Groq(api_key=settings.groq_api_key, max_retries=0, timeout=settings.llm_timeout_s)

    def complete(self, *, system: str, user: str, budget: RequestBudget, purpose: str,
                 model: str | None = None, max_tokens: int | None = None, json_mode: bool = False) -> str:
        if not self.enabled or self._client is None:
            raise LLMUnavailable("GROQ_API_KEY is not configured")
        import groq

        est_prompt = (len(system) + len(user)) // 4 + 32
        out_tokens = min(max_tokens or self.s.max_output_tokens, budget.remaining_tokens - est_prompt)
        if out_tokens < 64:
            raise LLMUnavailable(f"per-request token cap reached ({self.s.max_tokens_per_request})")

        primary = model or self.s.llm_model
        candidates = [primary] + ([self.s.llm_fallback_model] if self.s.llm_fallback_model != primary else [])
        last_error: Exception | None = None
        for m in candidates:
            timeout = min(self.s.llm_timeout_s, budget.remaining_seconds - 1.0)
            if timeout < 2:
                raise LLMUnavailable("request deadline reached")
            kwargs = {
                "model": m,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "temperature": 0,
                "max_tokens": out_tokens,
                "timeout": timeout,
            }
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            t0 = time.monotonic()
            try:
                resp = self._client.chat.completions.create(**kwargs)
            except (groq.RateLimitError, groq.APITimeoutError, groq.APIConnectionError,
                    groq.InternalServerError) as e:
                last_error = e
                log_event(logger, "llm_call_failed", logging.WARNING, model=m, purpose=purpose,
                          error=type(e).__name__)
                continue
            except groq.APIStatusError as e:
                last_error = e
                log_event(logger, "llm_call_failed", logging.WARNING, model=m, purpose=purpose,
                          error=f"{type(e).__name__}:{e.status_code}")
                continue
            ms = int((time.monotonic() - t0) * 1000)
            usage = resp.usage
            budget.add(m, getattr(usage, "prompt_tokens", 0) or 0, getattr(usage, "completion_tokens", 0) or 0,
                       purpose, ms)
            return (resp.choices[0].message.content or "").strip()
        raise LLMUnavailable(f"all models failed: {type(last_error).__name__ if last_error else 'unknown'}")
