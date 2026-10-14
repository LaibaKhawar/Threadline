import httpx
import pytest
import respx
from pydantic import BaseModel

from app.ai.llm.base import LLMError, LLMMessage
from app.ai.llm.gateway import LLMGateway, set_provider_override
from app.ai.llm.ollama import OllamaProvider
from app.ai.llm.openai_compat import AzureOpenAIProvider, OpenAICompatibleProvider
from app.ai.structured import StructuredOutputError, parse_json_object, structured_generate
from tests.fakes import ScriptedProvider


@respx.mock
def test_ollama_generate_parses_tokens_and_sends_schema() -> None:
    route = respx.post("http://ollama:11434/api/chat").mock(return_value=httpx.Response(200, json={
        "message": {"content": "hello"}, "prompt_eval_count": 12, "eval_count": 3}))
    r = OllamaProvider("http://ollama:11434", schema_mode="grammar").generate([LLMMessage("user", "hi")], model="qwen3", json_schema={"type": "object"})
    assert (r.text, r.input_tokens, r.output_tokens, r.locality) == ("hello", 12, 3, "local")
    body = route.calls[0].request.content
    assert b'"format"' in body and b'"stream":false' in body


@respx.mock
def test_ollama_errors_become_llm_error() -> None:
    respx.post("http://ollama:11434/api/chat").mock(side_effect=httpx.ConnectError("down"))
    with pytest.raises(LLMError):
        OllamaProvider("http://ollama:11434").generate([LLMMessage("user", "hi")], model="m")


@respx.mock
def test_openai_compatible_cost_and_auth_header() -> None:
    route = respx.post("https://api.example/v1/chat/completions").mock(return_value=httpx.Response(200, json={
        "choices": [{"message": {"content": "ok"}}], "usage": {"prompt_tokens": 1000, "completion_tokens": 500}}))
    p = OpenAICompatibleProvider("https://api.example/v1", "sk-test-key-0000000000", input_cost_per_mtok=1.0, output_cost_per_mtok=4.0)
    r = p.generate([LLMMessage("user", "hi")], model="gpt")
    assert r.cost_usd == pytest.approx(0.003) and r.locality == "cloud"
    assert route.calls[0].request.headers["authorization"] == "Bearer sk-test-key-0000000000"


@respx.mock
def test_openai_http_error_hides_body() -> None:
    respx.post("https://api.example/v1/chat/completions").mock(return_value=httpx.Response(401, json={"error": "bad key sk-secret"}))
    with pytest.raises(LLMError) as e:
        OpenAICompatibleProvider("https://api.example/v1", "k").generate([LLMMessage("user", "x")], model="m")
    assert "sk-secret" not in str(e.value)


@respx.mock
def test_azure_deployment_url() -> None:
    route = respx.post("https://az.example/openai/deployments/gpt4/chat/completions").mock(return_value=httpx.Response(200, json={
        "choices": [{"message": {"content": "ok"}}], "usage": {}}))
    AzureOpenAIProvider("https://az.example", "key").generate([LLMMessage("user", "x")], model="gpt4")
    assert route.called and route.calls[0].request.headers["api-key"] == "key"
    assert "api-version=" in str(route.calls[0].request.url)


class Out(BaseModel):
    name: str
    score: float


def test_structured_generate_retries_malformed_output(db, user) -> None:
    fake = ScriptedProvider(responses=["not json", '{"name": "x"}', '```json\n{"name": "x", "score": 0.5}\n```'])
    set_provider_override("local", fake)
    out = structured_generate(LLMGateway(db, user.id), Out, operation="extraction", system="s", user="u")
    assert out == Out(name="x", score=0.5) and len(fake.calls) == 3
    # the retry prompt tells the model what was wrong
    assert "invalid" in fake.calls[1][-1].content


def test_structured_generate_gives_up(db, user) -> None:
    set_provider_override("local", ScriptedProvider(responses=["nope", "nope", "nope"]))
    with pytest.raises(StructuredOutputError):
        structured_generate(LLMGateway(db, user.id), Out, operation="extraction", system="s", user="u")


def test_parse_json_strips_reasoning_tags() -> None:
    assert parse_json_object('<think>hmm</think>{"a": 1}') == {"a": 1}


@respx.mock
def test_ollama_json_mode_is_default() -> None:
    route = respx.post("http://ollama:11434/api/chat").mock(return_value=httpx.Response(200, json={"message": {"content": "{}"}}))
    OllamaProvider("http://ollama:11434").generate([LLMMessage("user", "hi")], model="m", json_schema={"type": "object"})
    assert b'"format":"json"' in route.calls[0].request.content
