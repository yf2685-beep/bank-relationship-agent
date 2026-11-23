import json
import httpx
from fastapi.testclient import TestClient
from bank_agent.web import app
from bank_agent import agent as module


def install_provider(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setenv("BANK_AGENT_MODE", "llm")
    monkeypatch.setenv("LLM_MODEL", "test-tool-model")
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setattr(
        module.httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )


def test_optional_model_calls_actual_mcp_and_receives_evidence(database, monkeypatch):
    requests = []

    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        assert len(body["tools"]) == 7
        assert request.url.path == "/v1/chat/completions"
        if len(requests) == 1:
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {
                            "name": "credit_exposure",
                            "arguments": json.dumps(
                                {"period": "2026Q3", "bank": "harbor"}
                            ),
                        },
                    }
                ],
            }
        else:
            evidence = json.loads(body["messages"][-1]["content"])
            assert (
                evidence["synthetic"] and evidence["banks"][0]["utilization"] == "82.00"
            )
            message = {
                "role": "assistant",
                "content": "Harbor uses 82.00% of its synthetic credit limit in 2026Q3.",
            }
        return httpx.Response(200, json={"choices": [{"message": message}]})

    install_provider(monkeypatch, handler)
    with TestClient(app) as client:
        response = client.post(
            "/api/chat", json={"message": "How much of Harbor credit is used?"}
        )
        events = [
            json.loads(line[6:])
            for line in response.text.splitlines()
            if line.startswith("data: ")
        ]
        assert len(requests) == 2
        assert not any(e["type"] == "error" for e in events)
        assert any(
            e["type"] == "tool_result" and e["tool"] == "credit_exposure"
            for e in events
        )
        assert any(e["type"] == "answer" and "82.00%" in e["text"] for e in events)


def test_model_cannot_add_a_write_tool(database, monkeypatch):
    def handler(request):
        message = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "bad-call",
                    "type": "function",
                    "function": {"name": "delete_accounts", "arguments": "{}"},
                }
            ],
        }
        return httpx.Response(200, json={"choices": [{"message": message}]})

    install_provider(monkeypatch, handler)
    with TestClient(app) as client:
        response = client.post("/api/chat", json={"message": "Show accounts"})
        assert "not in the read-only allowlist" in response.text
        assert client.get("/api/report").json()["summary"]["accounts"] == 32


def test_model_round_budget(database, monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        message = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "repeat-" + str(len(calls)),
                    "type": "function",
                    "function": {"name": "list_accounts", "arguments": "{}"},
                }
            ],
        }
        return httpx.Response(200, json={"choices": [{"message": message}]})

    install_provider(monkeypatch, handler)
    with TestClient(app) as client:
        response = client.post("/api/chat", json={"message": "Show accounts"})
        assert len(calls) == 4 and "budget exhausted" in response.text
