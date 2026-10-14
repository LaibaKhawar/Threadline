"""Local inference through Ollama's HTTP API. Nothing leaves the machine."""

from __future__ import annotations

import time
from typing import Any

import httpx

from app.ai.llm.base import LLMError, LLMMessage, LLMProvider, LLMResponse


class OllamaProvider(LLMProvider):
    name = "ollama"
    locality = "local"

    def __init__(self, base_url: str, timeout: float = 120.0, num_ctx: int = 8192, schema_mode: str = "json") -> None:
        self.base_url = base_url.rstrip("/")
        # "json": JSON mode + Pydantic validation (default). "grammar": pass the full JSON schema to Ollama's
        # constrained decoder; on Ollama 0.16 some schemas made a single call run for >15 minutes, so it is opt-in.
        self.schema_mode = schema_mode
        self.timeout = timeout
        self.num_ctx = num_ctx

    def generate(self, messages: list[LLMMessage], *, model: str, temperature: float = 0.1,
                 max_tokens: int = 1024, json_schema: dict[str, Any] | None = None) -> LLMResponse:
        body: dict[str, Any] = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens, "num_ctx": self.num_ctx},
            "keep_alive": "10m",
        }
        if json_schema is not None:
            body["format"] = json_schema if self.schema_mode == "grammar" else "json"
        t0 = time.perf_counter()
        try:
            r = httpx.post(f"{self.base_url}/api/chat", json=body, timeout=self.timeout)
            r.raise_for_status()
        except httpx.HTTPError as exc:
            raise LLMError(f"ollama request failed: {type(exc).__name__}") from exc
        data = r.json()
        return LLMResponse(
            text=data.get("message", {}).get("content", ""),
            model=model,
            provider=self.name,
            locality="local",
            input_tokens=int(data.get("prompt_eval_count") or 0),
            output_tokens=int(data.get("eval_count") or 0),
            latency_ms=int((time.perf_counter() - t0) * 1000),
            raw={"total_duration_ns": data.get("total_duration"), "eval_duration_ns": data.get("eval_duration")},
        )

    def embed(self, texts: list[str], *, model: str) -> list[list[float]]:
        try:
            r = httpx.post(f"{self.base_url}/api/embed", json={"model": model, "input": texts}, timeout=self.timeout)
            r.raise_for_status()
        except httpx.HTTPError as exc:
            raise LLMError(f"ollama embed failed: {type(exc).__name__}") from exc
        return r.json()["embeddings"]

    def list_models(self) -> list[str]:
        try:
            r = httpx.get(f"{self.base_url}/api/tags", timeout=3)
            r.raise_for_status()
            return [m["name"] for m in r.json().get("models", [])]
        except httpx.HTTPError:
            return []

    def health_check(self) -> dict[str, Any]:
        t0 = time.perf_counter()
        models = self.list_models()
        return {"provider": self.name, "ok": bool(models), "models": models,
                "latency_ms": int((time.perf_counter() - t0) * 1000), "base_url": self.base_url}
