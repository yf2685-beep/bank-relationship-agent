"""Discover BankScope with the official A2A SDK and ask follow-up questions."""

import argparse
import asyncio
import uuid

from a2a.client import ClientConfig, ClientFactory
from a2a.types import Message, Part, Task, TaskQueryParams, TaskState, TextPart
import httpx


async def run(base_url: str, messages: list[str], streaming: bool):
    async with httpx.AsyncClient(timeout=120, trust_env=False) as http:
        client = await ClientFactory.connect(
            base_url,
            client_config=ClientConfig(httpx_client=http, streaming=streaming),
        )
        context_id = None
        for question in messages:
            print("Question:", question)
            message = Message(
                role="user",
                message_id=str(uuid.uuid4()),
                context_id=context_id,
                parts=[Part(root=TextPart(text=question))],
            )
            task = None
            previous_state = None
            async for update in client.send_message(message):
                if not isinstance(update, tuple) or not isinstance(update[0], Task):
                    raise RuntimeError("Expected an A2A Task response from BankScope")
                task, event = update
                if task.status.state != previous_state:
                    print("  state:", task.status.state.value)
                    previous_state = task.status.state
                if event and event.kind == "artifact-update":
                    print("  artifact:", event.artifact.name)
            if task is None or task.status.state != TaskState.completed:
                raise RuntimeError(
                    "The task did not complete; inspect the server configuration and supported queries."
                )
            saved = await client.get_task(TaskQueryParams(id=task.id))
            assert saved.status.state == TaskState.completed
            context_id = saved.context_id
            print("  taskId:", saved.id)
            print("  contextId:", context_id)
            for artifact in saved.artifacts or []:
                for part in artifact.parts:
                    if isinstance(part.root, TextPart):
                        print(part.root.text)
            print()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--stream", action="store_true")
    parser.add_argument(
        "--message",
        action="append",
        help="Repeat to send follow-ups in the same context",
    )
    args = parser.parse_args()
    messages = args.message or [
        "Show Harbor Bank relationship report for 2026Q2",
        "What about its fees?",
    ]
    asyncio.run(run(args.base_url, messages, args.stream))


if __name__ == "__main__":
    main()
