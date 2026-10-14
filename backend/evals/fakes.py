"""Test doubles. Only used by tests; production code never references these."""

from __future__ import annotations

from typing import Any

from app.ai.llm.base import LLMError, LLMMessage, LLMProvider, LLMResponse


class ScriptedProvider(LLMProvider):
    """Returns queued responses (or a function of the prompt) and records every call."""

    def __init__(self, name: str = "scripted", locality: str = "local", responses: list[str] | None = None,
                 fn: Any = None, fail: bool = False) -> None:
        self.name = name
        self.locality = locality  # type: ignore[assignment]
        self.responses = list(responses or [])
        self.fn = fn
        self.fail = fail
        self.calls: list[list[LLMMessage]] = []

    def generate(self, messages: list[LLMMessage], *, model: str, temperature: float = 0.1, max_tokens: int = 1024,
                 json_schema: dict[str, Any] | None = None) -> LLMResponse:
        self.calls.append(messages)
        if self.fail:
            raise LLMError("scripted failure")
        text = self.fn(messages) if self.fn else (self.responses.pop(0) if self.responses else "")
        return LLMResponse(text=text, model=model, provider=self.name, locality=self.locality, input_tokens=10, output_tokens=5)

    def health_check(self) -> dict[str, Any]:
        return {"ok": True, "models": ["scripted"]}
