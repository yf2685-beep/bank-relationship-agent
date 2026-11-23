import asyncio
import json
import uuid

from a2a.client import ClientConfig, ClientFactory
from a2a.types import Message, Part, Task, TaskQueryParams, TaskState, TextPart
from fastapi.testclient import TestClient
import httpx
import pytest

from bank_agent.a2a import create_agent_card
from bank_agent.web import create_app


def payload(text, *, context_id=None, blocking=True):
    message = {
        "role": "user",
        "messageId": str(uuid.uuid4()),
        "parts": [{"kind": "text", "text": text}],
    }
    if context_id:
        message["contextId"] = context_id
    return {"message": message, "configuration": {"blocking": blocking}}


def rpc(client, method, params):
    response = client.post(
        "/a2a",
        json={"jsonrpc": "2.0", "id": "test", "method": method, "params": params},
    )
    return response.json()


def data_artifact(task):
    return next(
        part["data"]
        for artifact in task.get("artifacts", [])
        for part in artifact["parts"]
        if part["kind"] == "data"
    )


def test_discovery_and_real_mcp_task(database, monkeypatch):
    monkeypatch.setenv("BANK_AGENT_PUBLIC_URL", "http://testserver")
    with TestClient(create_app()) as client:
        card = client.get("/.well-known/agent-card.json").json()
        assert (
            card["url"] == "http://testserver/a2a"
            and card["protocolVersion"] == "0.3.0"
        )
        assert (
            card["capabilities"]["streaming"]
            and not card["capabilities"]["pushNotifications"]
        )
        assert len(card["skills"]) == 7 and card["defaultInputModes"] == ["text/plain"]
        task = rpc(
            client,
            "message/send",
            payload("Show Harbor Bank relationship report for 2026Q2"),
        )["result"]
        assert task["status"]["state"] == "completed"
        data = data_artifact(task)
        assert data["tool"] == "relationship_report"
        assert (
            data["result"]["scope"] == "harbor" and data["result"]["period"] == "2026Q2"
        )
        assert data["result"]["synthetic"]
        assert any(a["name"] == "answer.txt" for a in task["artifacts"])
        saved = rpc(client, "tasks/get", {"id": task["id"]})["result"]
        assert saved["artifacts"] == task["artifacts"]
        followup = rpc(
            client,
            "message/send",
            payload("What about its fees?", context_id=task["contextId"]),
        )["result"]
        assert (
            followup["id"] != task["id"] and followup["contextId"] == task["contextId"]
        )
        assert data_artifact(followup)["result"]["scope"] == "harbor"
        assert data_artifact(followup)["result"]["period"] == "2026Q2"
        separate = rpc(client, "message/send", payload("Show fees"))["result"]
        assert data_artifact(separate)["result"]["scope"] == "all"


def test_streaming_lifecycle_and_artifacts(database):
    with TestClient(create_app()) as client:
        response = client.post(
            "/a2a",
            json={
                "jsonrpc": "2.0",
                "id": "stream",
                "method": "message/stream",
                "params": payload("Show credit utilization for Harbor in 2026Q3"),
            },
        )
        assert response.headers["content-type"].startswith("text/event-stream")
        events = [
            json.loads(line[6:])["result"]
            for line in response.text.splitlines()
            if line.startswith("data: ")
        ]
        assert (
            events[0]["kind"] == "task" and events[0]["status"]["state"] == "submitted"
        )
        states = [
            event["status"]["state"]
            for event in events
            if event["kind"] == "status-update"
        ]
        assert states[0] == "working" and states[-1] == "completed"
        assert events[-1]["final"] is True
        results = [
            event["artifact"] for event in events if event["kind"] == "artifact-update"
        ]
        assert [a["name"] for a in results] == ["credit_exposure.json", "answer.txt"]
        assert (
            results[0]["parts"][0]["data"]["result"]["banks"][0]["utilization"]
            == "82.00"
        )


def test_failed_task_preserves_context_and_unknown_ids(database):
    with TestClient(create_app()) as client:
        task = rpc(
            client,
            "message/send",
            payload("Show Harbor relationship report for 2026Q2"),
        )["result"]
        failed = rpc(
            client,
            "message/send",
            payload(
                "Show Alder relationship report for 2027Q1",
                context_id=task["contextId"],
            ),
        )["result"]
        assert failed["status"]["state"] == "failed" and not failed.get("artifacts")
        followup = rpc(
            client,
            "message/send",
            payload("What about its fees?", context_id=task["contextId"]),
        )["result"]
        assert data_artifact(followup)["result"]["scope"] == "harbor"
        assert rpc(client, "tasks/get", {"id": "not-a-task"})["error"]["code"] == -32001
        assert (
            rpc(client, "tasks/cancel", {"id": task["id"]})["error"]["code"] == -32002
        )
        denied = rpc(client, "message/send", payload("Delete all accounts"))["result"]
        assert denied["status"]["state"] == "completed"
        assert [a["name"] for a in denied["artifacts"]] == ["answer.txt"]


@pytest.mark.parametrize(
    "parts",
    [
        [],
        [{"kind": "text", "text": " "}],
        [{"kind": "text", "text": "x" * 2001}],
        [{"kind": "data", "data": {"sql": "DELETE FROM accounts"}}],
    ],
)
def test_invalid_input_is_a_protocol_error(database, parts):
    with TestClient(create_app()) as client:
        params = payload("placeholder")
        params["message"]["parts"] = parts
        response = rpc(client, "message/send", params)
        assert response["error"]["code"] == -32602


@pytest.mark.parametrize(
    "url",
    [
        "file:///tmp/db",
        "http://user:password@example.com",
        "https://example.com/?secret=1",
        "https://example.com/#fragment",
    ],
)
def test_card_rejects_invalid_advertised_urls(monkeypatch, url):
    monkeypatch.setenv("BANK_AGENT_PUBLIC_URL", url)
    with pytest.raises(ValueError):
        create_agent_card()


@pytest.mark.parametrize("streaming", [False, True])
def test_official_a2a_client_can_discover_send_and_get(
    database, monkeypatch, streaming
):
    monkeypatch.setenv("BANK_AGENT_PUBLIC_URL", "http://bankscope.test")

    async def run():
        app = create_app()
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://bankscope.test"
            ) as http:
                client = await ClientFactory.connect(
                    "http://bankscope.test",
                    client_config=ClientConfig(httpx_client=http, streaming=streaming),
                )
                message = Message(
                    role="user",
                    message_id=str(uuid.uuid4()),
                    parts=[
                        Part(
                            root=TextPart(
                                text="Show Harbor credit utilization for 2026Q3"
                            )
                        )
                    ],
                )
                updates = [event async for event in client.send_message(message)]
                final = updates[-1][0]
                assert (
                    isinstance(final, Task)
                    and final.status.state == TaskState.completed
                )
                saved = await client.get_task(TaskQueryParams(id=final.id))
                assert saved.id == final.id and saved.artifacts
                assert (
                    saved.artifacts[0]
                    .parts[0]
                    .root.data["result"]["banks"][0]["utilization"]
                    == "82.00"
                )

    asyncio.run(run())


def test_cancel_running_task_and_rollback_context(database, monkeypatch):
    async def run():
        app = create_app()
        async with app.router.lifespan_context(app):
            started = asyncio.Event()
            stopped = asyncio.Event()
            original = app.state.agent.stream

            async def slow(text, state):
                state.update(bank="harbor", period="2026Q2")
                yield {"type": "plan", "text": "Controlled long-running test task"}
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    stopped.set()

            monkeypatch.setattr(app.state.agent, "stream", slow)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as http:
                response = await http.post(
                    "/a2a",
                    json={
                        "jsonrpc": "2.0",
                        "id": "start",
                        "method": "message/send",
                        "params": payload("Show report", blocking=False),
                    },
                )
                task = response.json()["result"]
                await asyncio.wait_for(started.wait(), timeout=3)
                canceled = await http.post(
                    "/a2a",
                    json={
                        "jsonrpc": "2.0",
                        "id": "cancel",
                        "method": "tasks/cancel",
                        "params": {"id": task["id"]},
                    },
                )
                assert canceled.json()["result"]["status"]["state"] == "canceled"
                await asyncio.wait_for(stopped.wait(), timeout=3)
                monkeypatch.setattr(app.state.agent, "stream", original)
                followup = await http.post(
                    "/a2a",
                    json={
                        "jsonrpc": "2.0",
                        "id": "follow",
                        "method": "message/send",
                        "params": payload("Show fees", context_id=task["contextId"]),
                    },
                )
                assert (
                    data_artifact(followup.json()["result"])["result"]["scope"] == "all"
                )
                status = await http.post(
                    "/a2a",
                    json={
                        "jsonrpc": "2.0",
                        "id": "get",
                        "method": "tasks/get",
                        "params": {"id": task["id"]},
                    },
                )
                assert status.json()["result"]["status"]["state"] == "canceled"

    asyncio.run(asyncio.wait_for(run(), timeout=10))
