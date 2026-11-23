"""A2A 0.3 JSON-RPC adapter for the existing treasury agent and MCP tools."""

import asyncio
from collections import OrderedDict
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, field
import os
from urllib.parse import urlparse

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.apps import A2AStarletteApplication
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentSkill,
    DataPart,
    InvalidParamsError,
    Part,
    Role,
    TaskNotCancelableError,
    TaskState,
    TextPart,
)
from a2a.utils import new_agent_text_message, new_task
from a2a.utils.errors import ServerError

from .agent import TreasuryAgent

SKILLS = [
    (
        "relationship_report",
        "Bank relationship report",
        "Cash, flows, costs and exposures for a bank or portfolio.",
        "Show the overall relationship report for 2026Q3",
    ),
    (
        "compare_banks",
        "Compare banking partners",
        "Compare banks for the same quarter and USD basis.",
        "Compare Alder and Harbor in 2026Q3",
    ),
    (
        "list_accounts",
        "Account registry",
        "List fictional active or dormant accounts.",
        "List dormant accounts",
    ),
    (
        "fee_analysis",
        "Bank fee analysis",
        "Compare quarterly fees and fee-to-outflow basis points.",
        "Compare fees for all banks in 2026Q3",
    ),
    (
        "payment_activity",
        "Payment activity",
        "Analyze gross outgoing payments and transaction counts.",
        "Show payment outflows for Harbor in 2026Q3",
    ),
    (
        "credit_exposure",
        "Credit utilization",
        "Analyze credit limits and utilization at quarter end.",
        "Show Harbor credit utilization for 2026Q3",
    ),
    (
        "debt_investments",
        "Debt and investment positions",
        "Show separate debt and investment snapshots.",
        "Show debt and investments for 2026Q3",
    ),
]


def create_agent_card() -> AgentCard:
    base = os.environ.get("BANK_AGENT_PUBLIC_URL", "http://127.0.0.1:8000").rstrip("/")
    parsed = urlparse(base)
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "BANK_AGENT_PUBLIC_URL must be an HTTP(S) base URL without credentials, query or fragment."
        )
    return AgentCard(
        name="BankScope — Bank Relationship Agent",
        description="Read-only analysis of generated USD treasury records. Default local mode uses deterministic intent rules; optional model mode uses your configured provider. No live bank access.",
        url=base + "/a2a",
        version="0.2.0",
        protocol_version="0.3.0",
        preferred_transport="JSONRPC",
        documentation_url="https://github.com/yf2685-beep/bank-relationship-agent/blob/main/docs/A2A.md",
        capabilities=AgentCapabilities(
            streaming=True, push_notifications=False, state_transition_history=False
        ),
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain", "application/json"],
        skills=[
            AgentSkill(
                id=identifier,
                name=name,
                description=description,
                tags=["treasury", "read-only", "synthetic-data"],
                examples=[example],
            )
            for identifier, name, description, example in SKILLS
        ],
    )


@dataclass
class Conversation:
    state: dict = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    users: int = 0


@dataclass
class ActiveRun:
    updater: TaskUpdater
    gate: asyncio.Lock = field(default_factory=asyncio.Lock)
    canceled: bool = False


class BankAgentExecutor(AgentExecutor):
    """Translate standard A2A tasks into the same stream used by the web UI."""

    def __init__(self, get_agent: Callable[[], TreasuryAgent]):
        self.get_agent = get_agent
        self.contexts: OrderedDict[str, Conversation] = OrderedDict()
        self.active: dict[str, ActiveRun] = {}
        self.producers: set[asyncio.Task] = set()

    def _conversation(self, context_id: str) -> Conversation:
        if context_id not in self.contexts:
            if len(self.contexts) >= 128:
                idle = next(
                    (key for key, value in self.contexts.items() if value.users == 0),
                    None,
                )
                if idle is None:
                    raise ValueError(
                        "All conversation slots are busy; try again later."
                    )
                del self.contexts[idle]
            self.contexts[context_id] = Conversation()
        self.contexts.move_to_end(context_id)
        conversation = self.contexts[context_id]
        conversation.users += 1
        return conversation

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        message = context.message
        text = context.get_user_input().strip()
        if (
            not message
            or message.role != Role.user
            or not message.parts
            or any(not isinstance(part.root, TextPart) for part in message.parts)
            or not text
            or len(text) > 2000
            or len(context.context_id or "") > 256
        ):
            raise ServerError(
                InvalidParamsError(
                    message="Send a user message containing 1–2000 text characters; contextId is limited to 256 characters. Files and data inputs are not supported."
                )
            )
        task = context.current_task or new_task(message)
        updater = TaskUpdater(event_queue, task.id, task.context_id)
        run = ActiveRun(updater)
        self.active[task.id] = run
        producer = asyncio.current_task()
        self.producers.add(producer)
        conversation = None

        def note(value):
            return new_agent_text_message(
                value, context_id=task.context_id, task_id=task.id
            )

        try:
            if not context.current_task:
                await event_queue.enqueue_event(task)
            await updater.start_work(
                note(
                    "Analyzing generated treasury records through read-only MCP tools."
                )
            )
            conversation = self._conversation(task.context_id)
            async with conversation.lock:
                # Failed and canceled turns must not overwrite successful context.
                state = deepcopy(conversation.state)
                async for event in self.get_agent().stream(text, state):
                    async with run.gate:
                        if run.canceled:
                            return
                        kind = event["type"]
                        if kind in ("plan", "tool_start"):
                            description = (
                                event.get("text") or "Calling " + event["tool"]
                            )
                            await updater.update_status(
                                TaskState.working,
                                note(description),
                                metadata={"bankscope": event},
                            )
                        elif kind == "tool_result":
                            await updater.add_artifact(
                                [
                                    Part(
                                        root=DataPart(
                                            data={
                                                "tool": event["tool"],
                                                "result": event["data"],
                                            }
                                        )
                                    )
                                ],
                                name=event["tool"] + ".json",
                                metadata={"synthetic": True},
                                last_chunk=True,
                            )
                        elif kind == "answer":
                            await updater.add_artifact(
                                [Part(root=TextPart(text=event["text"]))],
                                name="answer.txt",
                                last_chunk=True,
                            )
                        elif kind == "error":
                            raise ValueError(event["text"])
                async with run.gate:
                    if not run.canceled:
                        await updater.complete(
                            note("Analysis complete. Results use synthetic data.")
                        )
                        conversation.state = state
        except asyncio.CancelledError:
            raise
        except Exception:
            # Provider exceptions can include endpoints or headers. Keep them out
            # of publicly retrievable A2A task history and status messages.
            async with run.gate:
                if not run.canceled:
                    await updater.failed(
                        note(
                            "Analysis failed. Check the supported bank, quarter and local model configuration, then submit a new task."
                        )
                    )
        finally:
            if conversation:
                conversation.users -= 1
            self.active.pop(task.id, None)
            self.producers.discard(producer)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        run = self.active.get(context.task_id)
        if run is None:
            raise ServerError(TaskNotCancelableError())
        async with run.gate:
            try:
                await run.updater.cancel(
                    new_agent_text_message(
                        "Analysis canceled.",
                        context_id=context.context_id,
                        task_id=context.task_id,
                    )
                )
            except RuntimeError as exc:
                raise ServerError(TaskNotCancelableError()) from exc
            run.canceled = True
        # DefaultRequestHandler cancels the producer after this final event.

    async def shutdown(self):
        producers = list(self.producers)
        for producer in producers:
            producer.cancel()
        if producers:
            await asyncio.gather(*producers, return_exceptions=True)


def install_a2a(app) -> BankAgentExecutor:
    executor = BankAgentExecutor(lambda: app.state.agent)
    task_store = InMemoryTaskStore()
    handler = DefaultRequestHandler(agent_executor=executor, task_store=task_store)
    server = A2AStarletteApplication(
        agent_card=create_agent_card(),
        http_handler=handler,
        max_content_length=65536,
    )
    app.router.routes.extend(server.routes(rpc_url="/a2a"))
    app.state.a2a_executor = executor
    return executor
