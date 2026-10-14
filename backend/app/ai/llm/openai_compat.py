"""OpenAI-compatible chat completions (OpenAI, Groq, Together, vLLM, LM Studio, Azure OpenAI)."""

from __future__ import annotations

import time
from typing import Any

import httpx

from app.ai.llm.base import LLMError, LLMMessage, LLMProvider, LLMResponse


class OpenAICompatibleProvider(LLMProvider):
    name = "openai_compatible"

    def __init__(self, base_url: str, api_key: str, *, locality: str = "cloud", timeout: float = 60.0,
                 input_cost_per_mtok: float = 0.0, output_cost_per_mtok: float = 0.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key  # held in memory only; never logged
        self.locality = "cloud" if locality == "cloud" else "local"  # a self-hosted vLLM can be local
        self.timeout = timeout
        self.in_cost = input_cost_per_mtok
        self.out_cost = output_cost_per_mtok

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}

    def generate(self, messages: list[LLMMessage], *, model: str, temperature: float = 0.1,
                 max_tokens: int = 1024, json_schema: dict[str, Any] | None = None) -> LLMResponse:
        body: dict[str, Any] = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_schema is not None:
            body["response_format"] = {"type": "json_object"}
        t0 = time.perf_counter()
        try:
            r = httpx.post(self._url("/chat/completions"), json=body, headers=self._headers(), timeout=self.timeout)
            r.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise LLMError(f"provider returned HTTP {exc.response.status_code}") from exc
        except httpx.HTTPError as exc:
            raise LLMError(f"provider request failed: {type(exc).__name__}") from exc
        data = r.json()
        usage = data.get("usage") or {}
        it, ot = int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0)
        return LLMResponse(
            text=data["choices"][0]["message"].get("content") or "",
            model=model,
            provider=self.name,
            locality=self.locality,  # type: ignore[arg-type]
            input_tokens=it,
            output_tokens=ot,
            latency_ms=int((time.perf_counter() - t0) * 1000),
            cost_usd=self.estimate_cost(it, ot, model),
        )

    def estimate_cost(self, input_tokens: int, output_tokens: int, model: str) -> float:
        return round(input_tokens / 1e6 * self.in_cost + output_tokens / 1e6 * self.out_cost, 6)

    def list_models(self) -> list[str]:
        try:
            r = httpx.get(self._url("/models"), headers=self._headers(), timeout=5)
            r.raise_for_status()
            return [m["id"] for m in r.json().get("data", [])]
        except httpx.HTTPError:
            return []

    def health_check(self) -> dict[str, Any]:
        models = self.list_models()
        return {"provider": self.name, "ok": bool(models), "models": models[:20], "base_url": self.base_url}


class AzureOpenAIProvider(OpenAICompatibleProvider):
    """Azure uses deployment-scoped URLs and an api-key header."""

    name = "azure_openai"

    def __init__(self, endpoint: str, api_key: str, api_version: str = "2024-10-21", **kw: Any) -> None:
        super().__init__(endpoint, api_key, **kw)
        self.api_version = api_version

    def _headers(self) -> dict[str, str]:
        return {"api-key": self._api_key}

    def generate(self, messages: list[LLMMessage], *, model: str, **kw: Any) -> LLMResponse:
        original = self.base_url
        self.base_url = f"{original}/openai/deployments/{model}"
        try:
            resp = super().generate(messages, model=model, **kw)
        finally:
            self.base_url = original
        return resp

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}?api-version={self.api_version}"
