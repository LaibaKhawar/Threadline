"""LLM gateway: the only path from application code to a model.

Responsibilities: privacy routing, model selection, retries with backoff, cost/token accounting,
audit rows (llm_calls) and metrics. Business logic asks for an *operation*; it never picks a vendor.
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy.orm import Session

from app.ai.llm.base import LLMError, LLMMessage, LLMProvider, LLMResponse
from app.ai.llm.ollama import OllamaProvider
from app.ai.llm.openai_compat import OpenAICompatibleProvider
from app.core.config import get_settings
from app.core.errors import PrivacyViolation
from app.core.logging import get_logger
from app.core.metrics import LLM_CALLS, LLM_LATENCY
from app.db.models import LLMCall, UserSettings
from app.privacy.policy import PrivacyPolicy, RouteDecision

log = get_logger(__name__)

# Tests and evaluations can register providers here (e.g. a scripted provider) instead of HTTP ones.
_PROVIDER_OVERRIDES: dict[str, LLMProvider] = {}


def set_provider_override(locality: str, provider: LLMProvider | None) -> None:
    if provider is None:
        _PROVIDER_OVERRIDES.pop(locality, None)
    else:
        _PROVIDER_OVERRIDES[locality] = provider


def local_provider() -> LLMProvider:
    if "local" in _PROVIDER_OVERRIDES:
        return _PROVIDER_OVERRIDES["local"]
    s = get_settings()
    return OllamaProvider(s.ollama_base_url, timeout=s.llm_timeout_seconds, schema_mode=s.ollama_schema_mode)


def cloud_provider() -> LLMProvider | None:
    if "cloud" in _PROVIDER_OVERRIDES:
        return _PROVIDER_OVERRIDES["cloud"]
    s = get_settings()
    if not s.cloud_configured:
        return None
    return OpenAICompatibleProvider(s.cloud_base_url, s.cloud_api_key, locality="cloud",
                                    input_cost_per_mtok=s.cloud_input_cost_per_mtok,
                                    output_cost_per_mtok=s.cloud_output_cost_per_mtok)


class LLMGateway:
    def __init__(self, db: Session, user_id: str) -> None:
        self.db = db
        self.user_id = user_id
        self.policy = PrivacyPolicy(db, user_id)
        self.user_settings = db.get(UserSettings, user_id)

    def model_for(self, purpose: str, locality: str) -> str:
        s = get_settings()
        if locality == "cloud":
            return s.cloud_model
        us = self.user_settings
        if purpose == "extraction":
            return (us.extraction_model if us and us.extraction_model else s.extraction_model)
        return (us.reasoning_model if us and us.reasoning_model else s.reasoning_model)

    def route(self, operation: str, integration_ids: set[str | None]) -> RouteDecision:
        for iid in integration_ids:
            if not self.policy.local_ai_allowed(iid):
                raise PrivacyViolation("a source in this context does not allow AI processing")
        return self.policy.route(operation, integration_ids)

    def complete(
        self,
        operation: str,
        messages: list[LLMMessage],
        *,
        integration_ids: set[str | None] | None = None,
        purpose: str = "reasoning",
        json_schema: dict[str, Any] | None = None,
        temperature: float = 0.1,
        max_tokens: int = 1024,
        run_id: str | None = None,
        retries: int = 1,
    ) -> LLMResponse:
        decision = self.route(operation, integration_ids or set())
        provider = cloud_provider() if decision.locality == "cloud" else local_provider()
        if provider is None:  # cloud chosen but unavailable: fall back to local, never the reverse
            provider = local_provider()
        if decision.locality == "local" and provider.locality != "local":
            raise PrivacyViolation("refusing to send local-only content to a non-local provider")
        model = self.model_for(purpose, provider.locality)
        attempt, delay = 0, 1.0
        while True:
            attempt += 1
            t0 = time.perf_counter()
            try:
                resp = provider.generate(messages, model=model, temperature=temperature,
                                         max_tokens=max_tokens, json_schema=json_schema)
                self._record(provider, model, operation, "ok", resp, run_id, integration_ids, None)
                return resp
            except LLMError as exc:
                elapsed = int((time.perf_counter() - t0) * 1000)
                self._record(provider, model, operation, "error", None, run_id, integration_ids, str(exc), elapsed)
                if attempt > retries:
                    raise
                time.sleep(delay)
                delay *= 2

    def _record(self, provider: LLMProvider, model: str, operation: str, status: str, resp: LLMResponse | None,
                run_id: str | None, integration_ids: set[str | None] | None, error: str | None,
                latency_ms: int = 0) -> None:
        LLM_CALLS.labels(provider.name, model, operation, status).inc()
        if resp:
            LLM_LATENCY.labels(provider.name, operation).observe(resp.latency_ms / 1000)
        kinds = sorted({self.policy.sources[i].kind for i in (integration_ids or set()) if i in self.policy.sources})
        self.db.add(LLMCall(
            user_id=self.user_id, run_id=run_id, provider=provider.name, model=model, locality=provider.locality,
            operation=operation, status=status,
            input_tokens=resp.input_tokens if resp else 0, output_tokens=resp.output_tokens if resp else 0,
            cost_usd=resp.cost_usd if resp else 0.0, latency_ms=resp.latency_ms if resp else latency_ms,
            source_types=kinds, error=error,
        ))
        self.db.flush()
        log.info("llm_call", provider=provider.name, model=model, operation=operation, status=status,
                 locality=provider.locality, latency_ms=resp.latency_ms if resp else latency_ms,
                 input_tokens=resp.input_tokens if resp else 0, output_tokens=resp.output_tokens if resp else 0)
