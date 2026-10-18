"""Request orchestration: client lookup, cache, agent run, response shaping, request/cost logging."""
from __future__ import annotations

import logging
import time
import uuid

from app.agent.graph import AtlasAgent
from app.cache import TTLCache, cache_key
from app.config import Settings
from app.llm import LLMClient, RequestBudget
from app.logging_setup import log_event
from app.models import ChatRequest, ChatResponse, TokenStats

logger = logging.getLogger(__name__)

CACHEABLE_ROUTES = {"factual", "comparison", "calculation", "aggregate"}


class ClientNotFound(LookupError):
    pass


class CopilotService:
    def __init__(self, settings: Settings, repo, store, llm: LLMClient):
        self.s = settings
        self.repo = repo
        self.store = store
        self.llm = llm
        self.agent = AtlasAgent(settings, repo, store, llm)
        self.cache = TTLCache(settings.cache_ttl_s)

    def chat(self, req: ChatRequest) -> ChatResponse:
        t0 = time.monotonic()
        request_id = str(uuid.uuid4())
        client = self.repo.get_client(req.client_id)
        if client is None:
            raise ClientNotFound(req.client_id)
        entitled = self.repo.entitled_report_ids(client)
        key = cache_key(client["id"], entitled, req.question, req.history)

        cached = self.cache.get(key)
        if cached is not None:
            resp = cached.model_copy(update={
                "request_id": request_id, "cached": True, "latency_ms": int((time.monotonic() - t0) * 1000),
                "cost_usd": 0.0, "tokens": TokenStats(prompt_tokens=0, completion_tokens=0, llm_calls=0)})
            self._log(resp, req, trace=[{"node": "cache_hit"}])
            return resp

        budget = RequestBudget(self.s.max_tokens_per_request, deadline=t0 + self.s.request_timeout_s - 1.5)
        others = [c["company"] for c in self.repo.list_companies() if c["id"] != client["id"]]
        state = self.agent.run({
            "request_id": request_id,
            "client_id": client["id"],
            "company": client["company"],
            "question": req.question,
            "history": list(req.history),
            "entitled": entitled,
            "catalog": self.repo.get_catalog(),
            "other_companies": others,
            "budget": budget,
            "trace": [],
        })

        sql = state.get("sql_result") or {}
        resp = ChatResponse(
            request_id=request_id,
            client_id=client["id"],
            route=state.get("route", "unknown"),
            answer=state["answer"],
            citations=state.get("citations", []),
            confidence=state.get("confidence", 0.0),
            confidence_reasons=state.get("confidence_reasons", []),
            conflicts=state.get("conflicts", []),
            derived_values=state.get("derived", []),
            escalated=bool(state.get("escalated")),
            escalation_id=state.get("escalation_id"),
            locked_reports=state.get("locked_reports", []),
            sql_query=sql.get("query"),
            injection_detected=bool(state.get("injection_events")) or state.get("refusal_kind") == "prompt_injection",
            cached=False,
            latency_ms=int((time.monotonic() - t0) * 1000),
            tokens=TokenStats(prompt_tokens=budget.usage.prompt_tokens,
                              completion_tokens=budget.usage.completion_tokens,
                              llm_calls=len(budget.usage.calls)),
            cost_usd=round(budget.usage.cost_usd, 6),
        )
        if resp.route in CACHEABLE_ROUTES and not resp.escalated:
            self.cache.set(key, resp)
        self._log(resp, req, trace=state.get("trace", []) + [{"llm_calls": budget.usage.calls}])
        return resp

    def _log(self, resp: ChatResponse, req: ChatRequest, trace: list) -> None:
        log_event(logger, "chat_completed", request_id=resp.request_id, client_id=resp.client_id, route=resp.route,
                  confidence=resp.confidence, escalated=resp.escalated, cached=resp.cached,
                  latency_ms=resp.latency_ms, prompt_tokens=resp.tokens.prompt_tokens,
                  completion_tokens=resp.tokens.completion_tokens, cost_usd=resp.cost_usd,
                  injection_detected=resp.injection_detected)
        self.repo.log_request({
            "request_id": resp.request_id, "client_id": resp.client_id, "question": req.question,
            "route": resp.route, "confidence": resp.confidence, "escalated": resp.escalated, "cached": resp.cached,
            "latency_ms": resp.latency_ms, "prompt_tokens": resp.tokens.prompt_tokens,
            "completion_tokens": resp.tokens.completion_tokens, "cost_usd": resp.cost_usd, "trace": trace,
        })
