"""Validate real GigaChat SDK 0.2.4 request models without network access."""
import json
from types import SimpleNamespace

from gigachat.models import FunctionCall, MessagesRole

from llm import GigaChatLLM
from tools import tool_schemas


class FakeClient:
    def __init__(self, outputs):
        self.outputs = iter(outputs)
        self.requests = []

    def chat(self, request):
        self.requests.append(request)
        message = next(self.outputs)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def test_gigachat_function_call_and_result_history_are_valid():
    llm = object.__new__(GigaChatLLM)
    llm.model = "GigaChat-2-Pro"
    llm.client = FakeClient([
        SimpleNamespace(function_call=FunctionCall(
            name="get_spending_summary",
            arguments={"date_from": "2026-10-01", "date_to": "2026-10-31", "category": "taxi"},
        ), content=""),
        SimpleNamespace(function_call=None, content="На такси 600 ₽."),
    ])
    messages = [
        {"role": "system", "content": "Считай только инструментом"},
        {"role": "user", "content": "Сколько такси в октябре?"},
    ]
    result = llm.chat(messages, tool_schemas())
    assert result["tool_calls"][0]["name"] == "get_spending_summary"
    assert all(f.name for f in llm.client.requests[0].functions)
    assert llm.client.requests[0].functions[0].parameters.properties["date_from"]["type"] == "string"

    messages.append({"role": "assistant", "content": None, "tool_calls": [{
        "id": result["tool_calls"][0]["id"], "type": "function",
        "function": {"name": "get_spending_summary",
                     "arguments": result["tool_calls"][0]["arguments"]},
    }]})
    messages.append({"role": "tool", "tool_call_id": result["tool_calls"][0]["id"],
                     "content": json.dumps({"result": {"total_rub": 600.0}})})
    followup = llm.chat(messages, tool_schemas())
    assert "600" in followup["content"]
    history = llm.client.requests[1].messages
    assert history[-2].role == MessagesRole.ASSISTANT.value
    assert isinstance(history[-2].function_call, FunctionCall)
    assert history[-1].role == MessagesRole.FUNCTION.value
    assert history[-1].name == "get_spending_summary"


def test_gigachat_client_has_explicit_timeouts_and_ca(monkeypatch, tmp_path):
    import gigachat

    cert = tmp_path / "root.crt"
    cert.write_text("test only", encoding="utf-8")
    data = {}
    def fake_client(**kwargs):
        data.update(kwargs)
        return object()
    monkeypatch.setattr(gigachat, "GigaChat", fake_client)
    monkeypatch.setenv("GIGACHAT_CREDENTIALS", "not-a-real-key")
    monkeypatch.setenv("GIGACHAT_CA_BUNDLE_FILE", str(cert))
    monkeypatch.setenv("GIGACHAT_TIMEOUT", "20")
    GigaChatLLM("GigaChat-2-Pro")
    assert data["timeout"] == 20.0
    assert data["max_retries"] == 0
    assert data["ca_bundle_file"] == str(cert)
