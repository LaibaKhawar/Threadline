"""Schema-constrained generation: JSON in, Pydantic-validated object out, or a clear failure."""

from __future__ import annotations

import json
import re
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from app.ai.llm.base import LLMMessage
from app.ai.llm.gateway import LLMGateway

T = TypeVar("T", bound=BaseModel)


class StructuredOutputError(ValueError):
    def __init__(self, message: str, attempts: int, last_output: str) -> None:
        super().__init__(message)
        self.attempts = attempts
        self.last_output = last_output[:500]


def parse_json_object(text: str) -> Any:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    start = min([i for i in (text.find("{"), text.find("[")) if i >= 0], default=-1)
    if start < 0:
        raise ValueError("no JSON object in output")
    return json.loads(text[start:])


def structured_generate(
    gateway: LLMGateway,
    schema: type[T],
    *,
    operation: str,
    system: str,
    user: str,
    integration_ids: set[str | None] | None = None,
    purpose: str = "extraction",
    max_attempts: int = 3,
    max_tokens: int = 1500,
    run_id: str | None = None,
) -> T:
    messages = [LLMMessage("system", system), LLMMessage("user", user)]
    last = ""
    for attempt in range(1, max_attempts + 1):
        resp = gateway.complete(operation, messages, integration_ids=integration_ids, purpose=purpose,
                                json_schema=schema.model_json_schema(), max_tokens=max_tokens, run_id=run_id,
                                temperature=0.0)
        last = resp.text
        try:
            return schema.model_validate(parse_json_object(resp.text))
        except (ValueError, ValidationError) as exc:
            err = str(exc)[:600]
            messages = [*messages, LLMMessage("assistant", resp.text[:2000]),
                        LLMMessage("user", f"That output was invalid: {err}\nReturn only JSON matching the schema.")]
            if attempt == max_attempts:
                raise StructuredOutputError(f"invalid structured output after {attempt} attempts", attempt, last) from exc
    raise StructuredOutputError("unreachable", max_attempts, last)
