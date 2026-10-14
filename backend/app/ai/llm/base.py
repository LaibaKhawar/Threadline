"""Provider-neutral LLM interface. Business logic depends on this, never on a vendor SDK."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal

Locality = Literal["local", "cloud"]


@dataclass
class LLMMessage:
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass
class LLMResponse:
    text: str
    model: str
    provider: str
    locality: Locality
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    cost_usd: float = 0.0
    raw: dict[str, Any] = field(default_factory=dict)


class LLMError(RuntimeError):
    """Provider failure (network, timeout, HTTP error). Retryable by callers."""


class LLMProvider(ABC):
    name: str = "base"
    locality: Locality = "local"

    @abstractmethod
    def generate(
        self,
        messages: list[LLMMessage],
        *,
        model: str,
        temperature: float = 0.1,
        max_tokens: int = 1024,
        json_schema: dict[str, Any] | None = None,
    ) -> LLMResponse: ...

    def embed(self, texts: list[str], *, model: str) -> list[list[float]]:
        raise NotImplementedError(f"{self.name} does not provide embeddings")

    @abstractmethod
    def health_check(self) -> dict[str, Any]: ...

    def estimate_cost(self, input_tokens: int, output_tokens: int, model: str) -> float:
        return 0.0

    def list_models(self) -> list[str]:
        return []
